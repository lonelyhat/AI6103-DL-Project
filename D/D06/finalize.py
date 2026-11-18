"""Recover the E handoff from a fully generated D06 sweep without reselection."""
import argparse
import json
from pathlib import Path
import time

from D.D01.selection import digest, render_context, validate, HFTokenizer
from D.D02.prepare_materials import read_jsonl, sha
from D.D06.prepare import ROOT, PUBLIC, MODEL, e_module, save

# Exact, reviewed physical-line parsing correction. No selection or data changes
# are allowed when recovering a frozen plan; retain both hashes in the receipt.
JSONL_FIXES = {
    'E/E03/prepare_inputs.py': (
        'dfe05fb0f984ce10a54d7215ff16f5d00d2f8004076b6403e0924d441f8bbfce',
        'e38700684261f70a58b29a100570e7376f508e97ec23b1da70a2b928212cbc5f'),
    'E/E03/batch.py': (
        '32ce9984f6874a901a5e9876c1e703ddee962d4869264e8821ca8d676f61c8d0',
        'fe07e7cf8812197eadc60b3efb6ec39fd4f8a3ef1137239342450f8d104a9d67'),
}


def verify_sources(plan):
    changes = {}
    for name, old in plan['files_sha256'].items():
        path = ROOT / name
        current = sha(path)
        if current != old:
            if JSONL_FIXES.get(name) != (old, current):
                raise ValueError(f'input/selection source changed: {name}')
            changes[name] = dict(original_sha256=old, corrected_sha256=current)
    return changes


def collect(out, plan, counter):
    """Verify every previously replayed shard and original material; no select()."""
    qids = plan['question_ids']
    if (plan['version'] != 'd06-v1' or len(set(qids)) != len(qids)
            or plan['indices'] != ['K0', 'K1'] or plan['budget_tokens'] != 2048
            or len({digest(s) for s in plan['configs']}) != len(plan['configs'])
            or not plan['configs']):
        raise ValueError('invalid frozen plan')
    fingerprint = counter.fingerprint
    if plan['tokenizer'] != counter.name or plan['tokenizer_fingerprint'] != fingerprint:
        raise ValueError('tokenizer differs from frozen selection run')
    paths = []
    public = {q['question_id']: q for q in read_jsonl(PUBLIC / 'dev_questions.jsonl')}
    candidates = {index: {r['question_id']: r for r in read_jsonl(ROOT / file)}
                  for index, file in (
                      ('K0', 'B-检索线/B03/candidates/dev_K0.jsonl'),
                      ('K1', 'B-检索线/B05/candidates/dev_K1.jsonl'))}
    for index in plan['indices']:
        for qid in qids:
            if qid not in public or '/' in qid or '\\' in qid:
                raise ValueError('invalid question identity')
            turns = read_jsonl(PUBLIC / 'turns' / (qid + '.jsonl'))
            request = dict(candidates[index][qid])
            for k, v in public[qid].items():
                if k in request and request[k] != v:
                    raise ValueError('conflicting public metadata')
                request[k] = v
            request['budget_tokens'] = plan['budget_tokens']
            records = validate(request, turns)
            ranked = sorted(request['candidates'], key=lambda c: (c['rank'], c['turn_id']))
            expected_input = digest(dict(request=request, candidate_turns=[records[c['turn_id']] for c in ranked]))
            for setting in plan['configs']:
                folder = out / 'shards' / index / qid / digest(setting)[:16]
                path = folder / 'selections.jsonl'
                manifest = json.loads((folder / 'batch_manifest.json').read_text())
                if (manifest['plan_id'] != digest(plan) or manifest['setting'] != setting
                        or manifest.get('verification') != 'decision replay passed'
                        or manifest['selection_sha256'] != sha(path)):
                    raise ValueError(f'changed/unverified shard: {path}')
                rows = read_jsonl(path)
                if len(rows) != 1:
                    raise ValueError('one record per shard required')
                row = rows[0]
                for key in ('question_id', 'question', 'question_date', 'stage', 'index', 'budget_tokens'):
                    if row[key] != request.get(key):
                        raise ValueError(f'shard identity mismatch: {key}')
                config = row['config']
                if (row['strategy'] != setting['strategy'] or row['config_id'] != digest(config)
                        or row['input_sha256'] != expected_input or row['status'] != 'ready_for_reader'
                        or config['tokenizer_fingerprint'] != fingerprint):
                    raise ValueError('shard config/input identity mismatch')
                if setting['strategy'] != 'R':
                    for key in ('redundancy_weight', 'coverage_weight'):
                        if config[key] != setting[key]:
                            raise ValueError('shard parameter mismatch')
                if not row['selected_turn_ids'] or not set(row['selected_turn_ids']) <= {c['turn_id'] for c in ranked}:
                    raise ValueError('invalid selected turns')
                history = render_context([records[t] for t in row['selected_turn_ids']])
                expected_file = f'materials/{row["strategy"]}-{qid}.txt'
                if (row['history_file'] != expected_file or history != row['history_text']
                        or (folder / expected_file).read_bytes() != history.encode()
                        or counter.count(history) != row['context_tokens'] or row['context_tokens'] > 2048):
                    raise ValueError('material or exact token budget mismatch')
                paths.append(path)
            print(f'Validated {index} {qid}: {len(paths)}/{plan["expected_records"]}', flush=True)
    if len(paths) != plan['expected_records']:
        raise ValueError('incomplete sweep')
    return paths


def finalize(out, tokenizer):
    out = out.resolve()
    if not out.is_relative_to(ROOT / 'D'):
        raise ValueError('handoff must be inside D')
    started = time.perf_counter()
    plan = json.loads((out / 'plan.json').read_text())
    changes = verify_sources(plan)
    counter = HFTokenizer(tokenizer)
    counter.name = MODEL
    paths = collect(out, plan, counter)
    output = out / 'reader_inputs.jsonl'
    if output.exists():
        receipt = json.loads((out / 'handoff.json').read_text())
        if sha(output) != receipt['input_sha256']:
            raise ValueError('existing reader input changed')
        e_module('batch').load_inputs(output)
    else:
        receipt = e_module('prepare_inputs').build(paths, PUBLIC / 'turns', output)
        save(out / 'handoff.json', receipt)
    if receipt['records'] != plan['expected_records']:
        raise ValueError('export count differs from frozen plan')
    if verify_sources(plan) != changes:
        raise ValueError('source changed during recovery')
    report = dict(status='materials_ready_for_E', records=receipt['records'],
                  plan_id=digest(plan), input_sha256=sha(output),
                  corrected_exporter_sources=changes,
                  recovery_source_sha256=sha(Path(__file__)),
                  elapsed_s=time.perf_counter()-started,
                  selection_recomputed=False, frozen_plan_modified=False,
                  validation='original input/source hashes; saved decision-replay receipts; '
                             'all shard hashes; original history reconstruction; exact token counts')
    save(out / 'recovery_manifest.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--tokenizer', required=True)
    args = p.parse_args()
    finalize(args.output_dir, args.tokenizer)


if __name__ == '__main__':
    main()
