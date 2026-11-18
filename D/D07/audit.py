"""Offline D07 completion audit; recheck all materials and post-selection metrics."""
import argparse
import csv
import json
from pathlib import Path

from D.D01.selection import HFTokenizer, digest, render_context, validate
from D.D02.prepare_materials import read_jsonl, sha
from D.D07.run import (CachedCounter, MODEL, ROOT, PUBLIC, baseline_key,
                       check_baseline, evidence_module, metric_row, save, summarize_metrics)


def verify_csv(path, expected):
    with path.open(encoding='utf-8-sig', newline='') as f:
        actual = list(csv.DictReader(f))
    if actual != [{key: str(value) for key, value in row.items()} for row in expected]:
        raise ValueError('CSV does not match independently recomputed metrics: ' + path.name)


def audit(out, tokenizer):
    if (out / '.writer.lock').exists():
        raise ValueError('D07 writer is still active')
    plan = json.loads((out / 'plan.json').read_text())
    summary = json.loads((out / 'summary.json').read_text())
    if summary['status'] != 'complete' or summary['plan_id'] != digest(plan):
        raise ValueError('D07 plan/summary incomplete or mismatched')
    for name, expected in plan['files_sha256'].items():
        if sha(ROOT / name) != expected:
            raise ValueError('frozen source/input changed: ' + name)
    fp = plan['tokenizer_fingerprint']
    underlying = HFTokenizer(tokenizer)
    underlying.name = MODEL
    counter = CachedCounter(underlying)
    if counter.fingerprint != fp:
        raise ValueError('tokenizer differs')
    qids, cases = plan['question_ids'], plan['cases']
    questions = {q['question_id']: q for q in read_jsonl(PUBLIC / 'dev_questions.jsonl')}
    inputs = {index: {r['question_id']: r for r in read_jsonl(ROOT / name)}
              for index, name in [('K0', 'B-检索线/B03/candidates/dev_K0.jsonl'),
                                  ('K1', 'B-检索线/B05/candidates/dev_K1.jsonl')]}
    baseline_path = next(name for name in plan['files_sha256'] if name.endswith('/reader_inputs.jsonl'))
    baseline = {baseline_key(r): r for r in read_jsonl(ROOT / baseline_path)}
    evidence = evidence_module().Evidence()
    metrics, baseline_matches = [], 0
    for index in plan['indices']:
        for qid in qids:
            turns = read_jsonl(PUBLIC / 'turns' / (qid + '.jsonl'))
            candidate = inputs[index][qid]
            base = dict(candidate)
            base.update(questions[qid])
            records = validate(base, turns)
            ranked = sorted(candidate['candidates'], key=lambda c: (c['rank'], c['turn_id']))
            input_hashes = {b: digest(dict(request=dict(base, budget_tokens=b),
                                         candidate_turns=[records[c['turn_id']] for c in ranked]))
                            for b in {c['budget_tokens'] for c in cases}}
            candidate_metrics = evidence.retention(qid, [c['turn_id'] for c in ranked])
            counter.count.cache_clear()
            for case in cases:
                label = case['strategy'] if case['condition'] == 'main' else 'Q_no_coverage'
                shard = out / 'shards' / index / qid / str(case['budget_tokens']) / label
                manifest = json.loads((shard / 'batch_manifest.json').read_text())
                if (manifest['plan_id'] != digest(plan) or manifest['case'] != case
                        or not manifest['replay_passed']
                        or manifest['selection_sha256'] != sha(shard / 'selections.jsonl')
                        or manifest['candidate_original_budget'] != candidate.get('budget_tokens')
                        or manifest['experiment_budget'] != case['budget_tokens']):
                    raise ValueError('shard receipt mismatch: ' + str(shard))
                rows = read_jsonl(shard / 'selections.jsonl')
                if len(rows) != 1:
                    raise ValueError('invalid shard count')
                row = rows[0]
                for key, expected in dict(question_id=qid, index=index, stage='dev',
                                          strategy=case['strategy'], budget_tokens=case['budget_tokens']).items():
                    if row[key] != expected:
                        raise ValueError('material identity differs')
                if (row['config_id'] != digest(row['config'])
                        or row['config']['tokenizer_fingerprint'] != fp
                        or row['input_sha256'] != input_hashes[case['budget_tokens']]):
                    raise ValueError('config/input hash differs')
                if case['strategy'] != 'R' and any(row['config'][key] != case[key]
                        for key in ('redundancy_weight', 'coverage_weight')):
                    raise ValueError('selection weights differ')
                if not set(row['selected_turn_ids']) <= {c['turn_id'] for c in ranked}:
                    raise ValueError('selected turns outside candidate set')
                selected = [records[t] for t in row['selected_turn_ids']]
                history = render_context(selected)
                messages = list(dict.fromkeys(m['message_id'] for t in selected for m in t['messages']))
                if (history != row['history_text'] or messages != row['selected_message_ids']
                        or sha(shard / row['history_file']) != row['history_sha256']
                        or (shard / row['history_file']).read_bytes() != history.encode()
                        or counter.count(history) != row['context_tokens']
                        or row['context_tokens'] > case['budget_tokens']):
                    raise ValueError('history/token budget differs')
                matched = check_baseline(row, baseline)
                if matched != manifest['baseline_2048_match']:
                    raise ValueError('baseline receipt differs')
                baseline_matches += int(matched)
                metrics.append(metric_row(row, candidate_metrics, evidence, case, manifest['selection_elapsed_s']))
    if metrics != read_jsonl(out / 'evidence_metrics.jsonl'):
        raise ValueError('A02 metrics differ from saved selections')
    summaries, pairs, pair_summary = summarize_metrics(metrics, qids, cases)
    verify_csv(out / 'budget_evidence.csv', summaries)
    verify_csv(out / 'coverage_ablation_pairs.csv', pairs)
    verify_csv(out / 'coverage_ablation_summary.csv', pair_summary)
    if (summary['records'] != len(metrics) or summary['coverage_pairs'] != len(pairs)
            or summary['baseline_2048_checks'] != baseline_matches
            or summary['empty_materials'] != sum(r['empty_material'] for r in metrics)):
        raise ValueError('summary counts differ')
    return dict(status='passed', task='D07', questions=len(qids), records=len(metrics),
                budgets=summary['budgets'], baseline_2048_verified=baseline_matches,
                coverage_pairs=len(pairs), evidence_groups=len(summaries),
                empty_materials=summary['empty_materials'],
                all_saved_decision_replay_receipts_verified=True,
                full_greedy_replay_repeated=False,
                exact_history_token_checks=True, a02_metrics_recomputed=True,
                all_three_csv_tables_recomputed=True, source_and_input_hashes_verified=True,
                original_run_elapsed_s=summary['elapsed_s'], model_inference=False, scoring_api=False,
                audit_source_sha256=sha(Path(__file__)), plan_id=digest(plan))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--tokenizer', default=str(ROOT.parent / 'model_cache/Llama-3.1-8B-Instruct-tokenizer'))
    args = p.parse_args()
    result = audit(args.output_dir, args.tokenizer)
    save(args.output_dir / 'audit.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
