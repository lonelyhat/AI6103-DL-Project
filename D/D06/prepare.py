"""Freeze paired development sweeps, resume verified shards, export E03 inputs."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

from D.D01.selection import Config, HFTokenizer, digest, render_context, validate
from D.D02.materials import select_ranked
from D.D02.prepare_materials import read_jsonl, sha, write_bundle
from D.selection_batch import prepare_results
from D.verify_selection import verify_record

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'A-数据线/A01/output/public'
MODEL = 'meta-llama/Llama-3.1-8B-Instruct'


def e_module(name):
    directory = ROOT / 'E/E03'
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location('d06_e_' + name, directory / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def grid(lambdas, gammas):
    if not lambdas or not gammas:
        raise ValueError('nonempty parameter grids required')
    lambdas = sorted({Config(x, 0).redundancy_weight for x in lambdas})
    gammas = sorted({Config(0, x).coverage_weight for x in gammas})
    return ([dict(strategy='R', redundancy_weight=0., coverage_weight=0.)]
            + [dict(strategy=s, redundancy_weight=l, coverage_weight=0.)
               for s in ('MMR', 'C') for l in lambdas]
            + [dict(strategy='Q', redundancy_weight=l, coverage_weight=g)
               for l in lambdas for g in gammas]
            + [dict(strategy='FL', redundancy_weight=0., coverage_weight=0.)])


def paired_inputs(k0, k1, qids):
    result = {}
    for index, path in (('K0', k0), ('K1', k1)):
        rows = read_jsonl(path)
        ids = [r['question_id'] for r in rows]
        if len(set(ids)) != len(ids) or not set(qids) <= set(ids):
            raise ValueError(f'{index}: duplicate or missing questions')
        if any(r.get('stage') != 'dev' or r.get('index') != index for r in rows):
            raise ValueError(f'{index}: wrong candidate stage/index')
        result[index] = {r['question_id']: r for r in rows}
    if set(result['K0']) != set(result['K1']):
        raise ValueError('K0/K1 must cover the same development questions')
    return result


def verify_r(row, request, turns, counter):
    records = validate(request, turns)
    selected = []
    for c in sorted(request['candidates'], key=lambda c: (c['rank'], c['turn_id'])):
        proposal = selected + [c['turn_id']]
        if counter.count(render_context([records[t] for t in proposal])) <= request['budget_tokens']:
            selected = proposal
    history = render_context([records[t] for t in selected])
    import hashlib
    if (selected != row['selection_order'] or history != row['history_text']
            or hashlib.sha256(history.encode()).hexdigest() != row['history_sha256']
            or counter.count(history) != row['context_tokens']):
        raise ValueError('R rank/skip replay failed')


def save(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)


def run(args):
    started = time.perf_counter()
    if args.tokenizer.startswith('demo:'):
        raise ValueError('actual reader tokenizer required')
    counter = HFTokenizer(args.tokenizer)
    counter.name = MODEL
    expected = json.loads((ROOT / 'E/E03/results/dev5-k0-v1/config.json').read_text())['tokenizer_fingerprint']
    if counter.fingerprint != expected:
        raise ValueError('local tokenizer differs from accepted E03 tokenizer')
    qids = args.question_ids
    if args.all_questions:
        qids = [r['question_id'] for r in read_jsonl(args.k0)]
    if not qids or len(set(qids)) != len(qids):
        raise ValueError('distinct nonempty questions required')
    inputs = paired_inputs(args.k0, args.k1, qids)
    questions = read_jsonl(PUBLIC / 'dev_questions.jsonl')
    public = {r['question_id']: r for r in questions}
    if not set(qids) <= set(public) or any('/' in q or '\\' in q for q in qids):
        raise ValueError('unknown public development question')
    configs = grid(args.lambdas, args.gammas)
    files = [args.k0, args.k1, PUBLIC / 'dev_questions.jsonl']
    files += [PUBLIC / 'turns' / (q + '.jsonl') for q in qids]
    files += [Path(__file__), ROOT / 'D/D01/selection.py', ROOT / 'D/D02/materials.py',
              ROOT / 'D/D02/prepare_materials.py', ROOT / 'D/selection_batch.py', ROOT / 'D/verify_selection.py']
    files += [ROOT / 'E/E03' / f for f in ('prepare_inputs.py', 'batch.py')]
    files += [ROOT / 'E/E02/run_generation.py']
    def location(p):
        p = p.resolve()
        return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
    hashes = {location(p): sha(p) for p in files}
    plan = dict(version='d06-v1', question_ids=qids, indices=['K0', 'K1'], budget_tokens=2048,
                configs=configs, tokenizer=MODEL, tokenizer_fingerprint=counter.fingerprint,
                files_sha256=hashes, expected_records=len(qids)*2*len(configs),
                selection_rule='pending F03 calibration; no parameters selected',
                proposed_tie_rule='mean paired K0/K1 accuracy; then lower lambda, then lower gamma',
                stopping_rule='evaluate entire frozen grid; no early stopping')
    out = args.output_dir.resolve()
    if out == ROOT or not out.is_relative_to(ROOT / 'D') or any(p.resolve().is_relative_to(out) for p in files):
        raise ValueError('output must be a new directory inside D, away from inputs/source')
    if out.exists():
        if not args.resume or json.loads((out / 'plan.json').read_text()) != plan:
            raise ValueError('existing output requires --resume and identical plan/input/source')
    else:
        if args.resume:
            raise ValueError('resume output does not exist')
        out.mkdir(parents=True)
        save(out / 'plan.json', plan)
    paths, durations = [], []
    for index in ('K0', 'K1'):
        for qid in qids:
            turns = read_jsonl(PUBLIC / 'turns' / (qid + '.jsonl'))
            request = dict(inputs[index][qid])
            if request.get('config_version') != 'a01-v2' or request.get('strategy') is not None:
                raise ValueError('unselected a01-v2 candidates required')
            if request.get('budget_tokens') not in (None, 2048):
                raise ValueError('candidate budget differs')
            for k, v in public[qid].items():
                if k in request and request[k] != v:
                    raise ValueError('public/candidate metadata conflict')
                request[k] = v
            request['budget_tokens'] = 2048
            for setting in configs:
                tick = time.perf_counter()
                shard = out / 'shards' / index / qid / digest(setting)[:16]
                strategy = setting['strategy']
                if shard.exists():
                    manifest = json.loads((shard / 'batch_manifest.json').read_text())
                    if manifest['plan_id'] != digest(plan) or manifest['selection_sha256'] != sha(shard / 'selections.jsonl'):
                        raise ValueError('changed resume shard')
                    rows = read_jsonl(shard / 'selections.jsonl')
                    if len(rows) != 1:
                        raise ValueError('invalid shard count')
                    row = rows[0]
                elif strategy == 'R':
                    row = select_ranked(request, turns, counter)
                    row['history_file'] = f'materials/R-{qid}.txt'
                else:
                    settings = dict(setting, question_ids=[qid], strategies=[strategy],
                                    stage='dev', index=index, budget_tokens=2048)
                    row = prepare_results([inputs[index][qid]], questions, lambda _: turns, counter, settings)[0]
                for key in ('question_id', 'index', 'stage', 'budget_tokens', 'question', 'question_date'):
                    if row[key] != request.get(key):
                        raise ValueError('shard identity mismatch')
                if row['strategy'] != strategy or row['config_id'] != digest(row['config']):
                    raise ValueError('shard strategy/config mismatch')
                if strategy == 'R':
                    verify_r(row, request, turns, counter)
                else:
                    verify_record(row, request, turns, counter,
                                  Config(setting['redundancy_weight'], setting['coverage_weight']))
                if not row['selected_turn_ids'] or row['context_tokens'] > 2048:
                    raise ValueError('empty or over-budget material')
                if not shard.exists():
                    write_bundle(shard, [row], dict(plan_id=digest(plan), setting=setting,
                                 verification='decision replay passed', elapsed_s=time.perf_counter()-tick))
                    manifest = json.loads((shard / 'batch_manifest.json').read_text())
                    manifest['selection_sha256'] = sha(shard / 'selections.jsonl')
                    save(shard / 'batch_manifest.json', manifest)
                if (shard / row['history_file']).read_bytes() != row['history_text'].encode():
                    raise ValueError('saved material changed')
                paths.append(shard / 'selections.jsonl')
                durations.append(time.perf_counter()-tick)
                print(f'{len(paths)}/{plan["expected_records"]} {index} {qid} {setting} {durations[-1]:.2f}s', flush=True)
    if any(sha(p) != hashes[location(p)] for p in files):
        raise ValueError('input/source changed during sweep')
    output = out / 'reader_inputs.jsonl'
    if output.exists():
        receipt = json.loads((out / 'handoff.json').read_text())
        if sha(output) != receipt['input_sha256'] or len(read_jsonl(output)) != plan['expected_records']:
            raise ValueError('reader handoff changed')
    else:
        receipt = e_module('prepare_inputs').build(paths, PUBLIC / 'turns', output)
        save(out / 'handoff.json', receipt)
    elapsed = time.perf_counter()-started
    report = dict(status='waiting_for_E_and_F03', records=len(paths), elapsed_s=elapsed,
                  mode='resume_replay' if args.resume else 'prepare_and_replay',
                  mean_record_s=sum(durations)/len(durations), plan_id=digest(plan),
                  estimated_5_question_s=None if args.resume else elapsed*5/len(qids),
                  estimated_34_question_s=None if args.resume else elapsed*34/len(qids),
                  note='fresh-run linear CPU estimate only; excludes E inference, F scoring, queue time')
    save(out / ('resume_summary.json' if args.resume else 'summary.json'), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--k0', type=Path, default=ROOT / 'B-检索线/B03/candidates/dev_K0.jsonl')
    p.add_argument('--k1', type=Path, default=ROOT / 'B-检索线/B05/candidates/dev_K1.jsonl')
    p.add_argument('--tokenizer', required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--all-questions', action='store_true')
    p.add_argument('--question-ids', nargs='+', default=['2318644b', '1cea1afa', 'gpt4_7a0daae1', '4c36ccef', 'c960da58'])
    p.add_argument('--lambdas', nargs='+', type=float, default=[0, .5, 1])
    p.add_argument('--gammas', nargs='+', type=float, default=[0, .5, 1])
    run(p.parse_args())


if __name__ == '__main__':
    main()
