"""Validate every development score, compare the frozen grid, and choose weights."""
from __future__ import annotations
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import sys

from D.D01.selection import digest
from D.D02.prepare_materials import read_jsonl, sha
from D.D06.check_reader import check
from D.D06.prepare import ROOT, e_module, save


def judge_module():
    directory = ROOT / 'F/src/evaluation'
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location('d06_judge', directory / 'judge.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def setting_key(setting):
    return (setting['strategy'], float(setting['redundancy_weight']), float(setting['coverage_weight']))


def choose_best(rows):
    # Paired indices have equal question counts. Integer correct counts avoid
    # floating-point ties. C and Q have independent candidate pools.
    return min(rows, key=lambda r: (-r['paired_correct'], r['redundancy_weight'], r['coverage_weight']))


def aggregate(inputs, answers, scores, plan, judge):
    qids = set(plan['question_ids'])
    settings = [setting_key(s) for s in plan['configs']]
    if len(settings) != len(set(settings)) or not qids:
        raise ValueError('invalid frozen grid')
    expected_count = len(qids) * len(settings) * 2
    if expected_count != plan['expected_records'] or len(inputs) != expected_count:
        raise ValueError('input/grid count mismatch')
    answer_by_id = {r['record_id']: r for r in answers}
    if len(answer_by_id) != len(answers) or set(answer_by_id) != {r['record_id'] for r in inputs}:
        raise ValueError('answer identities missing/duplicate/extra')
    latest = {judge.record_key(r): r for r in scores}
    if set(latest) != {judge.record_key(r) for r in answers}:
        raise ValueError('score identities missing or unexpected')
    cells, records = {}, []
    for row in inputs:
        rid = row['record_id']
        answer = answer_by_id[rid]
        conf = row['selection_config']
        if digest(conf) != row['selection_config_id'] or conf['strategy'] != row['strategy']:
            raise ValueError('selection config mismatch')
        weights = (row['strategy'], float(conf.get('redundancy_weight', 0)),
                   float(conf.get('coverage_weight', 0)))
        if (weights not in settings or row['question_id'] not in qids or row['index'] not in ('K0', 'K1')
                or row['stage'] != 'dev' or row['budget_tokens'] != plan['budget_tokens']):
            raise ValueError('record outside frozen experiment')
        for key in ('question_id', 'index', 'strategy', 'selection_config_id', 'history_sha256'):
            if row[key] != answer[key]:
                raise ValueError('answer/input identity mismatch')
        score = latest[judge.record_key(answer)]
        if not judge.is_finished(score, answer):
            raise ValueError('score incomplete or answer fingerprint stale')
        if (score.get('judge_model') != 'gpt-4o-2024-08-06'
                or score.get('judge_model_returned') != 'gpt-4o-2024-08-06'
                or score.get('scoring_config_version') != 'f03-v1'
                or score.get('prompt_source') != judge.PROMPT_SOURCE
                or score.get('parse_status') != 'clean'
                or score['status'] != 'ok' or type(score['label']) is not int or score['label'] not in (0, 1)):
            raise ValueError('score model/config/label or parse status needs review')
        if score.get('e_status') != answer['status']:
            raise ValueError('score refers to another generation status')
        cell = cells.setdefault((*weights, row['index']), {})
        if row['question_id'] in cell:
            raise ValueError('duplicate question in parameter cell')
        record = dict(question_id=row['question_id'], index=row['index'], strategy=row['strategy'],
                      redundancy_weight=weights[1], coverage_weight=weights[2], label=score['label'],
                      generation_status=answer['status'], record_id=rid,
                      selection_config_id=row['selection_config_id'], reader_config_id=answer['reader_config_id'],
                      history_sha256=row['history_sha256'], question_type=score['question_type'])
        cell[row['question_id']] = record
        records.append(record)
    if set(cells) != {(*s, i) for s in settings for i in ('K0', 'K1')}:
        raise ValueError('missing parameter cells')
    grid_rows, paired = [], []
    for setting in settings:
        summary = dict(strategy=setting[0], redundancy_weight=setting[1], coverage_weight=setting[2])
        for index in ('K0', 'K1'):
            cell = cells[(*setting, index)]
            if set(cell) != qids:
                raise ValueError('unequal question sets across configurations')
            correct = sum(r['label'] for r in cell.values())
            summary[index + '_correct'] = correct
            summary[index + '_accuracy'] = correct / len(qids)
            grid_rows.append(dict(summary, index=index, questions=len(qids), correct=correct,
                                  accuracy=correct / len(qids),
                                  truncated=sum(r['generation_status'] == 'truncated' for r in cell.values())))
        summary.update(paired_correct=summary['K0_correct'] + summary['K1_correct'],
                       paired_denominator=len(qids) * 2,
                       mean_index_accuracy=(summary['K0_correct'] + summary['K1_correct']) / (2 * len(qids)))
        paired.append(summary)
    winners = []
    for strategy in ('R', 'MMR', 'C', 'Q', 'FL'):
        options = [r for r in paired if r['strategy'] == strategy]
        if not options:
            raise ValueError('missing strategy')
        winner = dict(choose_best(options))
        winner['accuracy_ties'] = [dict(redundancy_weight=r['redundancy_weight'], coverage_weight=r['coverage_weight'])
                                   for r in options if r['paired_correct'] == winner['paired_correct']]
        key = setting_key(winner)
        winner['selection_config_ids'] = {index: sorted({r['selection_config_id'] for r in cells[(*key, index)].values()})
                                           for index in ('K0', 'K1')}
        winners.append(winner)
    # Fixed CSV columns: avoid carrying K0 columns into K1 rows by accident.
    columns = ('strategy', 'redundancy_weight', 'coverage_weight', 'index', 'questions', 'correct', 'accuracy', 'truncated')
    grid_rows = [{key: row[key] for key in columns} for row in grid_rows]
    return records, grid_rows, paired, winners


def write_csv(path, rows):
    with path.open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(args):
    if args.output_dir.exists() or not args.output_dir.resolve().is_relative_to(ROOT / 'D/D06'):
        raise ValueError('choose a new output directory inside D/D06')
    check_report = check(args.handoff_dir, [args.run_dir])
    if check_report['status'] != 'reader_complete_waiting_for_scores':
        raise ValueError('reader handoff is not complete')
    files = [args.handoff_dir / 'plan.json', args.handoff_dir / 'reader_inputs.jsonl',
             args.run_dir / 'answers_for_f.jsonl', args.run_dir / 'results.jsonl',
             args.run_dir / 'attempts.jsonl', args.run_dir / 'config.json', args.scores,
             ROOT / 'F/SCORING_CONFIG.md', ROOT / 'F/src/evaluation/judge.py',
             ROOT / 'F/src/evaluation/prompts.py', Path(__file__)]
    before = {str(p): sha(p) for p in files}
    plan = json.loads(files[0].read_text())
    batch = e_module('batch')
    inputs = batch.load_inputs(files[1])
    records, grid_rows, paired, winners = aggregate(inputs, read_jsonl(files[2]), read_jsonl(args.scores), plan, judge_module())
    if any(sha(p) != before[str(p)] for p in files):
        raise ValueError('sources changed while summarizing')
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / 'scored_records.csv', records)
    write_csv(args.output_dir / 'parameter_grid.csv', grid_rows)
    write_csv(args.output_dir / 'paired_parameter_grid.csv', paired)
    selection = dict(task='D06', status='development_parameter_selection_complete',
                     scope='34 development questions; not formal/test accuracy',
                     question_ids=plan['question_ids'], indices=['K0', 'K1'], budget_tokens=2048,
                     scoring_config_version='f03-v1', judge_model='gpt-4o-2024-08-06',
                     metric='maximize equal-weight mean K0/K1 development accuracy per strategy',
                     tie_rule='lower redundancy_weight, then lower coverage_weight',
                     stopping_rule=plan['stopping_rule'], shared_weights_across_indices=True,
                     source_plan_id=digest(plan), records=len(records), methods=winners,
                     provenance_sha256=before,
                     limitations=['development selection accuracy is not an unbiased formal result',
                                  '34 paired questions, not 68 independent observations',
                                  '6 preference questions included; f03-v1 has no project-specific preference calibration',
                                  '7 recorded truncations scored as-is; no resampling'])
    save(args.output_dir / 'selected_parameters.json', selection)
    report = ['# D06 开发比较与参数选择', '',
              '34道开发题，K0/K1，2048 token；完整遍历冻结的17个方法/参数配置，1156条评分全部完成。',
              '每种方法用两种索引的平均正确率选一套共同参数；并列先取较小lambda，再取较小gamma。C与Q独立选择，允许零权重。',
              'F03配置为f03-v1；7条截断回答原样送评并保留在分母。没有早停或按结果扩展网格。', '',
              '| 方法 | lambda | gamma | K0 | K1 | 两索引均值 |', '|---|---:|---:|---:|---:|---:|']
    for row in winners:
        report.append(f"| {row['strategy']} | {row['redundancy_weight']:g} | {row['coverage_weight']:g} | "
                      f"{row['K0_correct']}/34 ({row['K0_accuracy']:.2%}) | "
                      f"{row['K1_correct']}/34 ({row['K1_accuracy']:.2%}) | {row['mean_index_accuracy']:.2%} |")
    report += ['', 'R和FL的零值仅代表没有参与扫描的权重，不代表使用了MMR或词面覆盖公式。', '',
               '完整逐参数结果见parameter_grid.csv及paired_parameter_grid.csv，逐条身份及分数见scored_records.csv。',
               '采用冻结计划中预先记录的建议比较/并列规则；保留原始plan.json，不事后改写历史计划。', '',
               '这些是用于选参的开发集结果，不能作为正式测试性能。34题含6道偏好题，该题型在f03-v1中未额外校准。',
               'D06开发比较与选参完成；D07预算诊断、G02正式冻结和D08正式材料仍需另行执行。', '']
    (args.output_dir / 'REPORT.md').write_text('\n'.join(report), encoding='utf-8')
    print(json.dumps(dict(status=selection['status'], records=len(records), selected=winners,
                         output=str(args.output_dir)), ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--handoff-dir', type=Path, default=ROOT / 'D/D06/output/dev34-grid-v1')
    p.add_argument('--run-dir', type=Path, default=ROOT / 'D/D06/returned/dev34-grid-v1/runs/dev34-grid-v1')
    p.add_argument('--scores', type=Path, default=ROOT / 'F/scores/d06_dev34_grid_v1.jsonl')
    p.add_argument('--output-dir', type=Path, required=True)
    run(p.parse_args())


if __name__ == '__main__':
    main()
