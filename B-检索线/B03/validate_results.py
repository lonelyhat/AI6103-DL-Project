#!/usr/bin/env python3
"""Validate complete public delivery and compare ranks using restricted official logs."""
import argparse
import json
import sys
from pathlib import Path
from common import A01, B02, ROOT, baseline, jl, load_inputs, settings, sha
sys.path.insert(0, str(ROOT))
from retrieve_dev import check_row


def validate(output, official, report):
    manifest, items = load_inputs()
    config = settings(manifest)
    rows = jl(output / 'candidates/dev_all_K0.jsonl')
    if [r['question_id'] for r in rows] != manifest['dev_ids']:
        raise ValueError('All-question delivery has missing, duplicate, or reordered IDs')
    by_id = {r['question_id']: r for r in rows}
    for q, turns in items:
        check_row(by_id[q['question_id']], q, turns, config)
    for filename, ids in [('dev_K0.jsonl', manifest['dev_answerable_ids']),
                          ('dev_abstention_K0.jsonl', manifest['dev_abstention_ids'])]:
        if jl(output / 'candidates' / filename) != [by_id[q] for q in ids]:
            raise ValueError(f'Incorrect split or changed payload: {filename}')
    raw = jl(official)
    if len(raw) != 40 or {r['question_id'] for r in raw} != set(manifest['dev_ids']):
        raise ValueError('Official log is not the same 40-question set')
    raw = {r['question_id']: r for r in raw}
    comparisons = []
    for qid in manifest['dev_ids']:
        mapping = {r['official_corpus_id']: r['turn_id'] for r in jl(A01 / f'map/{qid}.turns.jsonl')}
        theirs = [mapping[r['corpus_id']] for r in raw[qid]['retrieval_results']['ranked_items'][:100]]
        mine = [r['turn_id'] for r in by_id[qid]['candidates']]
        comparisons.append({'question_id': qid, 'same_order': mine == theirs,
                            'same_set': set(mine) == set(theirs),
                            'different_positions': [i + 1 for i, (a, b) in enumerate(zip(mine, theirs)) if a != b]})
    prior = []
    for old in jl(B02 / 'candidates/dev_K0.jsonl'):
        new = by_id[old['question_id']]
        same_ranks = [c['turn_id'] for c in old['candidates']] == [c['turn_id'] for c in new['candidates']]
        old_scores = {c['turn_id']: c['score'] for c in old['candidates']}
        new_scores = {c['turn_id']: c['score'] for c in new['candidates']}
        max_diff = max(abs(old_scores[k]-new_scores[k]) for k in old_scores) if old_scores.keys()==new_scores.keys() else None
        prior.append({'question_id': old['question_id'], 'same_order': same_ranks,
                      'max_absolute_score_difference': max_diff})
    passed = all(c['same_order'] for c in comparisons) and all(
        c['same_order'] and c['max_absolute_score_difference'] <= 1e-5 for c in prior)
    result = {'passed': passed, 'all_questions': 40, 'main_questions': 34, 'abstention_questions': 6,
              'candidates_per_question': 100, 'total_candidates': 4000,
              'D01_public_input_validation': 'passed for all 40',
              'official_top100_comparison': comparisons, 'B02_regression': prior,
              'candidate_sha256': {f.name: sha(f) for f in sorted((output/'candidates').glob('*.jsonl'))},
              'scope': 'rank/order comparison only; official log contains no numerical scores; not an answer-accuracy evaluation'}
    baseline.write_jsonl_atomic(report, [result])
    print(json.dumps(result, indent=2))
    if not passed:
        raise SystemExit('Official/B02 comparison failed; see report')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--official-log', required=True, type=Path)
    p.add_argument('--report', required=True, type=Path)
    a = p.parse_args()
    validate(a.output_dir, a.official_log, a.report)
