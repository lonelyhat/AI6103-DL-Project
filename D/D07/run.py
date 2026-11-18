"""CPU-only D07: exact-budget selection, replay, and post-selection A02 metrics."""
from __future__ import annotations
import argparse
from collections import defaultdict
from contextlib import contextmanager
import csv
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import time

from D.D01.selection import Config, HFTokenizer, digest, render_context
from D.D02.materials import select_ranked
from D.D02.prepare_materials import read_jsonl, sha, write_bundle
from D.D06.prepare import verify_r
from D.selection_batch import prepare_results
from D.verify_selection import verify_record

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PUBLIC = ROOT / 'A-数据线/A01/output/public'
MODEL = 'meta-llama/Llama-3.1-8B-Instruct'
METHODS = ('R', 'MMR', 'C', 'Q', 'FL')


class CachedCounter:
    """Cache exact token counts, not approximations; bound cache per question."""
    def __init__(self, counter):
        self.name = counter.name
        self.fingerprint = counter.fingerprint
        self.count = lru_cache(maxsize=2048)(counter.count)


def save(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)


@contextmanager
def lock_output(out):
    lock = out / '.writer.lock'
    with lock.open('x', encoding='utf-8') as f:
        json.dump(dict(pid=os.getpid(), host=socket.gethostname()), f)
    try:
        yield
    finally:
        lock.unlink()


def make_cases(parameters, budgets):
    if (len(set(budgets)) != len(budgets) or not budgets
            or any(type(b) is not int or b <= 0 for b in budgets)):
        raise ValueError('budgets must be distinct positive integers')
    methods = {m['strategy']: m for m in parameters['methods']}
    if len(methods) != len(parameters['methods']) or set(methods) != set(METHODS):
        raise ValueError('D06 must provide exactly five methods')
    cases = []
    for budget in sorted(budgets):
        for strategy in METHODS:
            m = methods[strategy]
            weights = Config(m['redundancy_weight'], m['coverage_weight'])
            if (strategy in ('R', 'FL') and weights != Config(0, 0)
                    or strategy != 'Q' and weights.coverage_weight != 0):
                raise ValueError('inactive weights must be zero')
            cases.append(dict(strategy=strategy, condition='main', budget_tokens=budget,
                              redundancy_weight=weights.redundancy_weight,
                              coverage_weight=weights.coverage_weight))
        q = methods['Q']
        cases.append(dict(strategy='Q', condition='coverage_off', budget_tokens=budget,
                          redundancy_weight=float(q['redundancy_weight']), coverage_weight=0.))
    return cases


def select_case(candidate, question, turns, counter, case):
    """No evidence/answer input is accepted by this selection adapter."""
    declared = candidate.get('budget_tokens')
    if declared not in (None, 2048):
        raise ValueError('unexpected B candidate provenance budget')
    if (candidate.get('strategy') is not None or candidate.get('config_version') != 'a01-v2'
            or candidate.get('stage') != 'dev' or candidate.get('index') not in ('K0', 'K1')):
        raise ValueError('require unselected dev a01-v2 K0/K1 candidates')
    # The original candidate file remains immutable. The budget intervention is
    # explicit in the frozen D07 plan and each shard's provenance receipt.
    adapted = dict(candidate, budget_tokens=case['budget_tokens'])
    request = dict(adapted)
    for key, value in question.items():
        if key in request and request[key] != value:
            raise ValueError('candidate/public question conflict')
        request[key] = value
    tick = time.perf_counter()
    if case['strategy'] == 'R':
        row = select_ranked(request, turns, counter)
        row['history_file'] = f'materials/R-{request["question_id"]}.txt'
    else:
        settings = dict(case, stage='dev', index=request['index'],
                        question_ids=[request['question_id']], strategies=[case['strategy']])
        row = prepare_results([adapted], [question], lambda _: turns, counter, settings)[0]
    return row, request, time.perf_counter() - tick


def replay(row, request, turns, counter, case):
    if row['strategy'] != case['strategy']:
        raise ValueError('shard strategy differs')
    if case['strategy'] == 'R':
        verify_r(row, request, turns, counter)
        for key in ('question_id', 'question', 'question_date', 'stage', 'index', 'budget_tokens'):
            if row.get(key) != request.get(key):
                raise ValueError('R identity differs')
        records = {t['turn_id']: t for t in turns}
        ordered = sorted((records[t] for t in row['selection_order']), key=lambda t: (t['sort_key'], t['turn_id']))
        if (row['selected_turn_ids'] != [t['turn_id'] for t in ordered]
                or row['selected_message_ids'] != list(dict.fromkeys(m['message_id'] for t in ordered for m in t['messages']))
                or row['config_id'] != digest(row['config'])
                or row['config']['tokenizer_fingerprint'] != counter.fingerprint):
            raise ValueError('R material/config identity differs')
    else:
        verify_record(row, request, turns, counter,
                      Config(case['redundancy_weight'], case['coverage_weight']))


def baseline_key(row):
    conf = row.get('selection_config', row.get('config'))
    return (row['question_id'], row['index'], row['strategy'],
            float(conf.get('redundancy_weight', 0)), float(conf.get('coverage_weight', 0)))


def check_baseline(row, baseline):
    if row['budget_tokens'] != 2048:
        return False
    if baseline_key(row) not in baseline:
        raise ValueError('missing D06 2048 baseline configuration')
    old = baseline[baseline_key(row)]
    for field in ('selected_turn_ids', 'selected_message_ids', 'context_tokens', 'history_sha256'):
        # E handoff omits selected_message_ids; compare all fields it preserves.
        if field in old and old[field] != row[field]:
            raise ValueError('D07 2048 differs from D06: ' + field)
    if row['history_text'] != old['context'] or row['config_id'] != old['selection_config_id']:
        raise ValueError('D07 2048 text/config differs from D06')
    return True


def evidence_module():
    spec = importlib.util.spec_from_file_location('d07_a02', ROOT / 'A-数据线/A02/evidence_metrics.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metric_row(row, candidate_metrics, evidence, case, elapsed):
    # Gold evidence is only evaluated after selection and decision replay.
    metric = evidence.retention(row['question_id'], row['selected_turn_ids'])
    if metric['is_abstention'] or not metric['has_evidence']:
        raise ValueError('D07 main development questions require answerable evidence')
    return dict(question_id=row['question_id'], index=row['index'], strategy=row['strategy'],
                condition=case['condition'], budget_tokens=row['budget_tokens'],
                redundancy_weight=case['redundancy_weight'], coverage_weight=case['coverage_weight'],
                config_id=row['config_id'], history_sha256=row['history_sha256'],
                context_tokens=row['context_tokens'], selected_turns=len(row['selected_turn_ids']),
                empty_material=not row['selected_turn_ids'], selection_elapsed_s=elapsed,
                n_evidence_msgs=metric['n_evidence_msgs'], n_retained_msgs=metric['n_retained_msgs'],
                msg_retention=metric['msg_retention'], all_retained=metric['all_retained'],
                any_retained=metric['any_retained'], missing_message_ids=metric['missing_message_ids'],
                candidate_msg_retention=candidate_metrics['msg_retention'],
                candidate_all_retained=candidate_metrics['all_retained'])


def summarize_metrics(rows, qids, cases):
    expected = {(q, i, c['strategy'], c['condition'], c['budget_tokens'])
                for q in qids for i in ('K0', 'K1') for c in cases}
    by_id = {(r['question_id'], r['index'], r['strategy'], r['condition'], r['budget_tokens']): r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != expected:
        raise ValueError('missing/duplicate/extra D07 metric records')
    groups = defaultdict(list)
    for row in rows:
        if not 0 <= row['msg_retention'] <= 1 or row['context_tokens'] > row['budget_tokens']:
            raise ValueError('invalid retention/budget metric')
        groups[(row['index'], row['strategy'], row['condition'], row['budget_tokens'])].append(row)
    summaries = []
    for (index, strategy, condition, budget), group in sorted(groups.items()):
        summaries.append(dict(index=index, strategy=strategy, condition=condition, budget_tokens=budget,
            questions=len(group), redundancy_weight=group[0]['redundancy_weight'], coverage_weight=group[0]['coverage_weight'],
            mean_msg_retention=sum(r['msg_retention'] for r in group)/len(group),
            all_retained_rate=sum(r['all_retained'] for r in group)/len(group),
            any_retained_rate=sum(r['any_retained'] for r in group)/len(group),
            mean_context_tokens=sum(r['context_tokens'] for r in group)/len(group),
            empty_materials=sum(r['empty_material'] for r in group),
            candidate_all_retained_rate=sum(r['candidate_all_retained'] for r in group)/len(group)))
    pairs, pair_groups = [], defaultdict(list)
    for qid in qids:
        for index in ('K0', 'K1'):
            for budget in sorted({c['budget_tokens'] for c in cases}):
                on, off = [by_id[(qid, index, 'Q', condition, budget)] for condition in ('main', 'coverage_off')]
                if on['redundancy_weight'] != off['redundancy_weight'] or off['coverage_weight'] != 0:
                    raise ValueError('coverage ablation changed another weight')
                pair = dict(question_id=qid, index=index, budget_tokens=budget,
                            redundancy_weight=on['redundancy_weight'], gamma_on=on['coverage_weight'], gamma_off=0.,
                            retention_on=on['msg_retention'], retention_off=off['msg_retention'],
                            retention_delta=on['msg_retention']-off['msg_retention'],
                            all_retained_on=on['all_retained'], all_retained_off=off['all_retained'],
                            context_tokens_on=on['context_tokens'], context_tokens_off=off['context_tokens'],
                            history_changed=on['history_sha256'] != off['history_sha256'],
                            config_id_on=on['config_id'], config_id_off=off['config_id'])
                pairs.append(pair)
                pair_groups[index, budget].append(pair)
    pair_summary = [dict(index=index, budget_tokens=budget, questions=len(group),
                        mean_retention_delta=sum(r['retention_delta'] for r in group)/len(group),
                        all_retained_rate_delta=sum(int(r['all_retained_on'])-int(r['all_retained_off']) for r in group)/len(group),
                        improved=sum(r['retention_delta'] > 0 for r in group),
                        worsened=sum(r['retention_delta'] < 0 for r in group),
                        tied=sum(r['retention_delta'] == 0 for r in group))
                    for (index, budget), group in sorted(pair_groups.items())]
    return summaries, pairs, pair_summary


def write_csv(path, rows):
    temp = path.with_suffix('.csv.tmp')
    with temp.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def run(args):
    started = time.perf_counter()
    params = json.loads(args.parameters.read_text())
    old_plan = json.loads(args.d06_plan.read_text())
    if (params.get('status') != 'development_parameter_selection_complete'
            or params['source_plan_id'] != digest(old_plan)):
        raise ValueError('require completed D06 parameters and the original frozen plan')
    qids = args.question_ids or params['question_ids']
    if not qids or len(set(qids)) != len(qids) or not set(qids) <= set(params['question_ids']):
        raise ValueError('require distinct D06 development questions')
    cases = make_cases(params, args.budgets)
    inputs = {}
    for index, path in (('K0', args.k0), ('K1', args.k1)):
        candidates = read_jsonl(path)
        if len({r['question_id'] for r in candidates}) != len(candidates):
            raise ValueError('duplicate candidate questions')
        if {r['question_id'] for r in candidates} != set(params['question_ids']):
            raise ValueError('candidate question set differs from D06')
        if any(r['index'] != index for r in candidates):
            raise ValueError('candidate index conflict')
        inputs[index] = {r['question_id']: r for r in candidates}
        key = path.resolve().relative_to(ROOT).as_posix()
        if sha(path) != old_plan['files_sha256'][key]:
            raise ValueError('candidate file changed since D06')
    questions = {q['question_id']: q for q in read_jsonl(PUBLIC / 'dev_questions.jsonl')}
    data = [PUBLIC / 'dev_questions.jsonl'] + [PUBLIC / 'turns' / (q + '.jsonl') for q in qids]
    for path in data:
        if sha(path) != old_plan['files_sha256'][path.relative_to(ROOT).as_posix()]:
            raise ValueError('public data changed since D06')
    baseline_hashes = [h for p, h in params['provenance_sha256'].items() if p.endswith('/D/D06/output/dev34-grid-v1/reader_inputs.jsonl')]
    if len(baseline_hashes) != 1 or sha(args.baseline_inputs) != baseline_hashes[0]:
        raise ValueError('D06 baseline input hash differs')
    baseline_rows = read_jsonl(args.baseline_inputs)
    baseline = {baseline_key(r): r for r in baseline_rows}
    if len(baseline) != len(baseline_rows):
        raise ValueError('duplicate D06 baseline')
    raw_counter = HFTokenizer(args.tokenizer)
    raw_counter.name = MODEL
    counter = CachedCounter(raw_counter)
    if counter.fingerprint != old_plan['tokenizer_fingerprint']:
        raise ValueError('tokenizer differs from D06/E')
    a02 = evidence_module()
    evidence = a02.Evidence()
    files = [args.parameters, args.d06_plan, args.baseline_inputs, args.k0, args.k1, *data,
             ROOT / 'A-数据线/A01/output/eval/dev_eval.jsonl', ROOT / 'A-数据线/A02/evidence_metrics.py',
             Path(__file__), ROOT / 'D/D01/selection.py', ROOT / 'D/D02/materials.py',
             ROOT / 'D/D02/prepare_materials.py', ROOT / 'D/selection_batch.py',
             ROOT / 'D/verify_selection.py', ROOT / 'D/D06/prepare.py']
    files += [evidence.root / 'map' / (q + suffix) for q in qids for suffix in ('.turns.jsonl', '.messages.jsonl')]
    hashes = {p.resolve().relative_to(ROOT).as_posix(): sha(p) for p in files}
    plan = dict(version='d07-v1', stage='dev', question_ids=qids, indices=['K0', 'K1'], cases=cases,
                expected_records=len(qids)*2*len(cases), d06_plan_id=digest(old_plan),
                tokenizer=MODEL, tokenizer_fingerprint=counter.fingerprint, files_sha256=hashes,
                candidate_budget_policy='preserve original B files; explicitly intervene on selection budget',
                parameter_policy='fixed D06 winners; only Q gamma is zeroed in coverage_off; no retuning',
                evaluation_policy='A02 message-union evidence metrics after selection/replay only',
                model_inference=False, scoring_api=False)
    if args.check_only:
        print(json.dumps(dict(status='inputs_ready', questions=len(qids), records=plan['expected_records'],
                              budgets=sorted(args.budgets), cases_per_index=len(cases)), indent=2))
        return
    out = args.output_dir.resolve()
    if out == HERE or not out.is_relative_to(HERE / 'output') or any(p.resolve().is_relative_to(out) for p in files):
        raise ValueError('output must be a new directory inside D/D07/output')
    if out.exists():
        if not args.resume or json.loads((out / 'plan.json').read_text()) != plan:
            raise ValueError('existing output requires --resume with identical frozen inputs/source/config')
    else:
        if args.resume:
            raise ValueError('resume output does not exist')
        out.mkdir(parents=True)
        save(out / 'plan.json', plan)
    with lock_output(out):
        metrics, baseline_checks, reused = [], 0, 0
        for index in ('K0', 'K1'):
            for qid in qids:
                turns = read_jsonl(PUBLIC / 'turns' / (qid + '.jsonl'))
                candidate = inputs[index][qid]
                candidate_metrics = evidence.retention(qid, [r['turn_id'] for r in candidate['candidates']])
                counter.count.cache_clear()
                for case in cases:
                    label = case['strategy'] if case['condition'] == 'main' else 'Q_no_coverage'
                    shard = out / 'shards' / index / qid / str(case['budget_tokens']) / label
                    if shard.exists():
                        manifest = json.loads((shard / 'batch_manifest.json').read_text())
                        if (manifest['plan_id'] != digest(plan) or manifest['case'] != case
                                or manifest['selection_sha256'] != sha(shard / 'selections.jsonl')):
                            raise ValueError('changed D07 shard')
                        rows = read_jsonl(shard / 'selections.jsonl')
                        if len(rows) != 1:
                            raise ValueError('invalid shard record count')
                        row = rows[0]
                        request = dict(candidate, budget_tokens=case['budget_tokens'])
                        request.update(questions[qid])
                        elapsed = manifest['selection_elapsed_s']
                        reused += 1
                    else:
                        row, request, elapsed = select_case(candidate, questions[qid], turns, counter, case)
                    replay(row, request, turns, counter, case)
                    baseline_match = check_baseline(row, baseline)
                    baseline_checks += int(baseline_match)
                    metric = metric_row(row, candidate_metrics, evidence, case, elapsed)
                    if not shard.exists():
                        serialized = (json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n').encode()
                        write_bundle(shard, [row], dict(plan_id=digest(plan), case=case,
                            candidate_original_budget=candidate.get('budget_tokens'), experiment_budget=case['budget_tokens'],
                            selection_sha256=hashlib.sha256(serialized).hexdigest(), selection_elapsed_s=elapsed,
                            replay_passed=True, baseline_2048_match=baseline_match))
                    if (shard / row['history_file']).read_bytes() != row['history_text'].encode():
                        raise ValueError('saved material differs')
                    metrics.append(metric)
                    print(f'{len(metrics)}/{plan["expected_records"]} {index} {qid} {case["budget_tokens"]} {label}: '
                          f'{row["context_tokens"]} tokens, evidence={metric["msg_retention"]:.3f}', flush=True)
        if any(sha(ROOT / name) != expected for name, expected in hashes.items()):
            raise ValueError('source/data changed during D07')
        summaries, pairs, pair_summary = summarize_metrics(metrics, qids, cases)
        with (out / 'evidence_metrics.jsonl.tmp').open('w', encoding='utf-8') as f:
            for row in metrics:
                f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        (out / 'evidence_metrics.jsonl.tmp').replace(out / 'evidence_metrics.jsonl')
        write_csv(out / 'budget_evidence.csv', summaries)
        write_csv(out / 'coverage_ablation_pairs.csv', pairs)
        write_csv(out / 'coverage_ablation_summary.csv', pair_summary)
        report = dict(status='complete', scope='D07 development evidence diagnostics only',
                      questions=len(qids), records=len(metrics), budgets=sorted(args.budgets),
                      baseline_2048_checks=baseline_checks, empty_materials=sum(r['empty_material'] for r in metrics),
                      coverage_pairs=len(pairs), plan_id=digest(plan),
                      elapsed_s=time.perf_counter()-started, reused_shards=reused,
                      model_inference=False, scoring_api=False, parameter_retuning=False)
        save(out / ('resume_summary.json' if args.resume else 'summary.json'), report)
        lines = ['# D07 预算与覆盖奖励诊断', '',
                 f'{len(qids)}道开发题；K0/K1；固定D06参数；预算为{sorted(args.budgets)}。',
                 '证据按A02的消息并集去重统计；不生成回答、不评分、不重新调参。空材料保留在分母。', '',
                 '| 索引 | 方法 | 条件 | 预算 | 平均消息证据保留率 | 证据齐全率 |',
                 '|---|---|---|---:|---:|---:|']
        lines += [f'| {r["index"]} | {r["strategy"]} | {r["condition"]} | {r["budget_tokens"]} | '
                  f'{r["mean_msg_retention"]:.2%} | {r["all_retained_rate"]:.2%} |' for r in summaries]
        lines += ['', 'coverage_off仅将Q的gamma置0，lambda及其余设置不变。消融同题差值见coverage_ablation_pairs.csv。',
                  '这些是开发集证据诊断，不能据此声称回答正确率改善；预算增大时贪心选择集合不保证嵌套。',
                  'D07不改变D06选参结果；正式预算及范围仍由G02确定。', '']
        (out / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tokenizer', default=str(ROOT.parent / 'model_cache/Llama-3.1-8B-Instruct-tokenizer'))
    p.add_argument('--parameters', type=Path, default=ROOT / 'D/D06/output/dev34-parameter-selection-v1/selected_parameters.json')
    p.add_argument('--d06-plan', type=Path, default=ROOT / 'D/D06/delivery/plan.json')
    p.add_argument('--baseline-inputs', type=Path, default=ROOT / 'D/D06/output/dev34-grid-v1/reader_inputs.jsonl')
    p.add_argument('--k0', type=Path, default=ROOT / 'B-检索线/B03/candidates/dev_K0.jsonl')
    p.add_argument('--k1', type=Path, default=ROOT / 'B-检索线/B05/candidates/dev_K1.jsonl')
    p.add_argument('--budgets', type=int, nargs='+', default=[1024, 2048, 4096])
    p.add_argument('--question-ids', nargs='+')
    p.add_argument('--output-dir', type=Path, default=HERE / 'output/dev34-budgets-v1')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--check-only', action='store_true')
    run(p.parse_args())


if __name__ == '__main__':
    main()
