"""Verify the archived D06/D07 handoff without inference or Judge calls."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from D.D07.run import baseline_key, evidence_module, make_cases, summarize_metrics
from G.G02.prepare import ROOT, read_json, read_rows, source_hash

D06 = ROOT / 'D/D06'
D07 = ROOT / 'D/D07/output/dev34-budgets-v1'
D06_PUBLISHED = D06 / 'output/dev34-parameter-selection-v1'


def compare_csv(path, recalculated):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        original = list(csv.DictReader(stream))
    if len(original) != len(recalculated):
        raise ValueError(f'{path.name}: row count differs from recomputation')
    for old, new in zip(original, recalculated):
        if old.keys() != new.keys() or not all(
            math.isclose(float(old[k]), v, rel_tol=1e-12, abs_tol=1e-12) if type(v) is float else old[k] == str(v)
            for k, v in new.items()
        ):
            raise ValueError(f'{path.name}: metric differs from recomputation')


def run(returned, recomputed):
    checksums = (D06 / 'delivery/SHA256SUMS').read_text(encoding='utf-8').splitlines()
    for line in checksums:
        expected, relative_path = line.split(maxsplit=1)
        if hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() != expected:
            raise ValueError(f'D06 delivery checksum failed: {relative_path}')
    for name in ('paired_parameter_grid.csv', 'parameter_grid.csv', 'scored_records.csv'):
        if source_hash(D06_PUBLISHED / name) != source_hash(recomputed / name):
            raise ValueError(f'D06 {name}: rerun differs from original')
    selected = read_json(D06_PUBLISHED / 'selected_parameters.json')
    current = read_json(recomputed / 'selected_parameters.json')
    if (selected['methods'], selected['source_plan_id'], selected['records']) != (
            current['methods'], current['source_plan_id'], current['records']):
        raise ValueError('D06 winner or plan identity differs from rerun')
    plan = read_json(D07 / 'plan.json')
    ids = selected['question_ids']
    cases = make_cases(selected, [1024, 2048, 4096])
    if plan['question_ids'] != ids or plan['cases'] != cases:
        raise ValueError('D07 plan differs from D06 parameters, question list or intended budget grid')
    by_case = {(c['strategy'], c['condition'], c['budget_tokens']): c for c in cases}
    material = read_rows(returned / 'inputs/reader_inputs.jsonl')
    baseline = {baseline_key(r): r for r in material}
    if len(baseline) != len(material) or len(material) != selected['records']:
        raise ValueError('D06 material grid has duplicate/missing records')
    evidence = evidence_module().Evidence()
    records = read_rows(D07 / 'evidence_metrics.jsonl')
    baseline_count = 0
    for row in records:
        case = by_case[(row['strategy'], row['condition'], row['budget_tokens'])]
        weights = ('redundancy_weight', 'coverage_weight')
        if any(row[k] != case[k] for k in weights):
            raise ValueError('D07 actual weights differ from the plan')
        if row['budget_tokens'] == 2048:
            key = (row['question_id'], row['index'], row['strategy'], *(row[k] for k in weights))
            original = baseline[key]
            if not (row['config_id'] == original['selection_config_id']
                    and row['selected_turns'] == len(original['selected_turn_ids'])
                    and all(row[k] == original[k] for k in ('history_sha256', 'context_tokens'))):
                raise ValueError('D07 2048 material fingerprint/count differs from D06')
            metrics = evidence.retention(row['question_id'], original['selected_turn_ids'])
            if any(row[k] != metrics[k] for k in ('msg_retention', 'all_retained', 'missing_message_ids')):
                raise ValueError('D07 2048 evidence metrics differ from A02 recomputation')
            baseline_count += 1
    tables = summarize_metrics(records, ids, cases)
    for name, rows in zip(('budget_evidence.csv', 'coverage_ablation_pairs.csv',
                           'coverage_ablation_summary.csv'), tables):
        compare_csv(D07 / name, rows)
    return {
        'd06_delivery_files_verified': len(checksums), 'd06_scored_records_recomputed': selected['records'],
        'd06_parameter_winners_match': True, 'd07_metric_records': len(records),
        'd07_2048_joined_to_d06_and_recalculated_with_a02': baseline_count,
        'd07_tables_recalculated': len(tables), 'd07_coverage_pairs': len(tables[1]),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--returned', type=Path, required=True)
    parser.add_argument('--d06-recomputed', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.returned, args.d06_recomputed), indent=2))
