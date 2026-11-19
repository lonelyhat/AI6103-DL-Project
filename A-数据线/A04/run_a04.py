"""统计 G02 冻结候选与 D08 选材中的消息级证据。"""
import argparse
from collections import Counter, defaultdict
from itertools import combinations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from D.D01.selection import HFTokenizer, render_context
from D.D08.verify_delivery import check_delivery
from G.G02.prepare import read_json, read_rows, source_hash
from G.G02.prepare_eval import build as build_evaluation

A03 = ROOT / 'A-数据线/A03/output'
A02 = ROOT / 'A-数据线/A02/evidence_metrics.py'
PLAN = ROOT / 'G/G02/plan.json'
DELIVERY = ROOT / 'D/D08/delivery'
STRATEGIES = ('R', 'MMR', 'C', 'Q', 'FL')


def load_evidence(eval_rows):
    spec = importlib.util.spec_from_file_location('a02_metrics', A02)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = module.Evidence()
    evidence.root = A03
    evidence.add_eval_rows(eval_rows)
    return evidence


def evidence_cover(evidence, qid, candidates, turns, tokenizer, budget):
    """枚举候选中包含证据的最小覆盖组合，按 D01 原样序列化计数。"""
    needed = set(evidence.eval[qid]['evidence_message_ids'])
    mapping = evidence.turn2msgs(qid)
    options = [(tid, set(mapping[tid]) & needed) for tid in candidates
               if set(mapping[tid]) & needed]
    best = None
    best_ids = None
    for n in range(1, min(len(needed), len(options)) + 1):
        for combo in combinations(options, n):
            sets = [item[1] for item in combo]
            if set().union(*sets) != needed:
                continue
            # Only inclusion-minimal covers. Supersets add unrelated material.
            if any(set().union(*(sets[:i] + sets[i + 1:])) == needed for i in range(len(sets))):
                continue
            ids = [item[0] for item in combo]
            count = tokenizer.count(render_context([turns[tid] for tid in ids]))
            if best is None or count < best:
                best, best_ids = count, ids
    if best is None:
        raise ValueError(f'{qid}: candidate coverage disagrees with A02')
    return {'minimum_cover_tokens': best, 'minimum_cover_turn_ids': best_ids,
            'minimal_cover_within_budget': best <= budget}


def run(dataset, tokenizer_path, output):
    plan = read_json(PLAN)
    if plan['status'] != 'frozen':
        raise ValueError('G02 configuration is not frozen')
    delivery_report = check_delivery()
    if delivery_report != read_json(DELIVERY / 'manifest.json'):
        raise ValueError('D08 delivery does not match its manifest')
    tokenizer = HFTokenizer(str(tokenizer_path))
    if tokenizer.fingerprint != plan['reader']['tokenizer_fingerprint']:
        raise ValueError('Tokenizer does not match the frozen reader')
    output.mkdir(parents=True, exist_ok=True)
    eval_path = output / 'formal_eval.jsonl'
    with tempfile.TemporaryDirectory() as temporary:
        generated_eval = Path(temporary) / 'formal_eval.jsonl'
        eval_info = build_evaluation(plan, dataset, generated_eval)
        evaluation_bytes = generated_eval.read_bytes()
    if eval_path.exists() and eval_path.read_bytes() != evaluation_bytes:
        raise ValueError('Existing evaluation file differs; choose a new output directory')
    eval_path.write_bytes(evaluation_bytes)
    evidence = load_evidence(read_rows(eval_path))
    formal = plan['formal']
    manifest = read_json(ROOT / formal['manifest'])
    ids = manifest['formal_ids']
    candidate_metrics = {}
    cover_by_question = {}
    indices = ('K0', 'K1')
    for index in indices:
        rows = read_rows(ROOT / formal['candidates'][index])
        if len(rows) != len(ids) or {r['question_id'] for r in rows} != set(ids):
            raise ValueError(f'{index}: candidate questions do not match A03')
        for row in rows:
            qid = row['question_id']
            candidates = [c['turn_id'] for c in row['candidates']]
            if len(candidates) != 100 or len(set(candidates)) != 100:
                raise ValueError(f'{qid}/{index}: invalid candidate count')
            metrics = evidence.retention(qid, candidates)
            candidate_metrics[qid, index] = metrics
            if metrics['all_retained']:
                turns = {t['turn_id']: t for t in read_rows(
                    ROOT / formal['public_root'] / 'turns' / f'{qid}.jsonl')}
                cover_by_question[qid, index] = evidence_cover(
                    evidence, qid, candidates, turns, tokenizer, plan['history_budget_tokens'])

    results = []
    seen = set()
    for batch_id in formal['batches']:
        archive = DELIVERY / f"D08_{plan['config_version']}_{batch_id}.zip"
        with zipfile.ZipFile(archive) as z:
            selections = [json.loads(line) for line in z.read('selections.jsonl').splitlines()]
        for selection in selections:
            qid, index, strategy = (selection[k] for k in ('question_id', 'index', 'strategy'))
            key = (qid, index, strategy)
            if key in seen:
                raise ValueError(f'Duplicate selection: {key}')
            seen.add(key)
            candidate = candidate_metrics[qid, index]
            selected = evidence.retention(qid, selection['selected_turn_ids'])
            if not set(selection['selected_message_ids']) == set().union(
                    *(set(evidence.turn2msgs(qid)[tid]) for tid in selection['selected_turn_ids'])):
                raise ValueError(f'{key}: message mapping disagreement')
            cover = cover_by_question.get((qid, index))
            if not candidate['all_retained']:
                diagnosis = 'candidates_missing'
            elif selected['all_retained']:
                diagnosis = 'all_retained'
            elif cover['minimal_cover_within_budget']:
                diagnosis = 'selection_missed'
            else:
                diagnosis = 'minimal_cover_over_budget'
            results.append({
                'question_id': qid, 'question_type': selected['question_type'],
                'batch_id': batch_id, 'stage': 'formal', 'index': index,
                'strategy': strategy, 'budget_tokens': selection['budget_tokens'],
                'config_id': selection['config_id'], 'history_sha256': selection['history_sha256'],
                'context_tokens': selection['context_tokens'],
                'candidate': candidate, 'selected': selected,
                'cover': cover, 'diagnosis': diagnosis,
            })
    expected = {(qid, index, strategy) for qid in ids for index in indices for strategy in STRATEGIES}
    if seen != expected:
        raise ValueError(f'D08 matrix mismatch: missing {len(expected-seen)}, extra {len(seen-expected)}')
    candidate_rows = [{'question_id': qid, 'index': index, **candidate_metrics[qid, index],
                       'cover': cover_by_question.get((qid, index))}
                      for qid in ids for index in indices]
    grouped = defaultdict(list)
    for row in results:
        grouped[row['index'], row['strategy']].append(row)
    summary = {'a03_version': manifest['config_version'], 'g02_version': plan['config_version'],
               'questions': len(ids), 'records': len(results), 'dataset_sha256': eval_info['dataset_sha256'],
               'formal_eval_sha256': eval_info['eval_sha256'], 'plan_sha256': source_hash(PLAN),
               'tokenizer_fingerprint': tokenizer.fingerprint,
               'candidates': {}, 'selections': {}}
    for index in indices:
        values = [candidate_metrics[qid, index] for qid in ids]
        summary['candidates'][index] = {
            'questions': len(values), 'all_retained': sum(x['all_retained'] for x in values),
            'mean_message_retention': sum(x['msg_retention'] for x in values) / len(values)}
        for strategy in STRATEGIES:
            values = grouped[index, strategy]
            summary['selections'][f'{index}/{strategy}'] = {
                'questions': len(values),
                'all_retained': sum(x['selected']['all_retained'] for x in values),
                'mean_message_retention': sum(x['selected']['msg_retention'] for x in values) / len(values),
                'diagnosis_counts': dict(sorted(Counter(x['diagnosis'] for x in values).items()))}
    for name, rows in [('candidate_metrics.jsonl', candidate_rows), ('selection_metrics.jsonl', results)]:
        with (output / name).open('w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'output')
    args = parser.parse_args()
    run(args.dataset, args.tokenizer, args.output)
