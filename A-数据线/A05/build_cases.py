"""构造 A05 案例证据包，核对冻结选材、实际回答、评分及原文。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

E04_COMMIT = '95438df71b0730d58ab260d97f4528e3b3228e72'
CASES = [
    ('1568498a', ('K0', 'C'), ('K0', 'Q'), 'improved'),
    ('89941a93', ('K0', 'C'), ('K0', 'Q'), 'regressed'),
    ('aae3761f', ('K0', 'R'), ('K1', 'R'), 'more_evidence_still_wrong'),
    ('6d550036', ('K0', 'R'), ('K1', 'R'), 'candidates_missing'),
    ('157a136e', ('K0', 'C'), ('K0', 'Q'), 'minimal_cover_over_budget'),
]


def rows(path):
    with path.open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def keyed(records):
    result = {}
    for row in records:
        key = (row['question_id'], row['index'], row['strategy'])
        if key in result:
            raise ValueError(f'duplicate record: {key}')
        result[key] = row
    return result


def main(dataset, output):
    report = json.loads((ROOT / 'D/D08/delivery/manifest.json').read_text())
    if report['questions'] != 80 or report['records'] != 800:
        raise ValueError('unexpected D08 delivery dimensions')
    manifest = json.loads((ROOT / 'A-数据线/A03/output/eval/formal_manifest.json').read_text())
    raw = dataset.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['data_sha256']:
        raise ValueError('dataset does not match A03')
    needed = {case[0] for case in CASES}
    questions = {q['question_id']: q for q in json.loads(raw) if q['question_id'] in needed}
    if set(questions) != needed:
        raise ValueError('case question missing from data')
    evaluations = {r['question_id']: r for r in rows(ROOT / 'A-数据线/A04/output/formal_eval.jsonl')}
    metrics = keyed(rows(ROOT / 'A-数据线/A04/output/selection_metrics.jsonl'))
    score_files = sorted((ROOT / 'F/scores').glob('formal_g02-v1_batch-*.jsonl'))
    scores = keyed([r for path in score_files for r in rows(path)])
    if len(scores) != 800:
        raise ValueError('expected 800 F04 scores')
    with (ROOT / 'F/F06/f06_per_question.csv').open(encoding='utf-8-sig', newline='') as f:
        f06 = {r['question_id']: r for r in csv.DictReader(f)}
    with (ROOT / 'F/F05/g02-v1/audit/formal_members_DO_NOT_OPEN.csv').open(
            encoding='utf-8-sig', newline='') as f:
        review_rows = list(csv.DictReader(f))
    review_by_id = {}
    for row in review_rows:
        review_by_id.setdefault(row['record_id'], []).append(row['編號'])

    selections, answers = {}, {}
    for batch in sorted({metrics[(q, *pair)]['batch_id']
                         for q, left, right, _ in CASES for pair in (left, right)}):
        archive = ROOT / f'D/D08/delivery/D08_g02-v1_{batch}.zip'
        if hashlib.sha256(archive.read_bytes()).hexdigest() != report['batches'][batch]['archive_sha256']:
            raise ValueError(f'{batch}: archive checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            for row in map(json.loads, z.read('selections.jsonl').splitlines()):
                selections[row['question_id'], row['index'], row['strategy']] = row
        path = f'E/E04/results/g02-v1/{batch}/answers_for_f.jsonl'
        raw_answers = subprocess.check_output(['git', 'show', f'{E04_COMMIT}:{path}'], cwd=ROOT)
        for row in map(json.loads, raw_answers.splitlines()):
            answers[row['question_id'], row['index'], row['strategy']] = row

    candidate_sets = {}
    for index in ('K0', 'K1'):
        candidate_sets[index] = {r['question_id']: r['candidates'] for r in rows(
            ROOT / f'B-检索线/B0{4 if index == "K0" else 6}/candidates/formal_{index}.jsonl')}
    cases = []
    for qid, left, right, kind in CASES:
        q = questions[qid]
        ev = evaluations[qid]
        message_map = {}
        for si, session in enumerate(q['haystack_sessions']):
            for mi, message in enumerate(session):
                mid = f'{qid}-s{si:03d}-m{mi:03d}'
                message_map[mid] = message
        evidence = [{'message_id': mid, 'role': message_map[mid]['role'],
                     'content': message_map[mid]['content']} for mid in ev['evidence_message_ids']]
        variants = []
        for index, strategy in (left, right):
            key = (qid, index, strategy)
            selection, metric, answer, score = (table[key] for table in
                                                  (selections, metrics, answers, scores))
            if (selection['history_sha256'] != metric['history_sha256']
                    or answer['history_sha256'] != score['history_sha256']
                    or score['history_sha256'] != metric['history_sha256']
                    or score['record_id'] != answer['record_id']
                    or selection['config_id'] != score['selection_config_id']
                    or selection['selected_turn_ids'] != answer['selected_turn_ids']):
                raise ValueError(f'{key}: selection/answer/score do not match')
            if score['response_source'] == 'raw_output':
                response = answer['raw_output']
            elif score['response_source'] == 'hypothesis':
                response = answer['hypothesis']
            else:
                raise ValueError(f'{key}: unknown response source')
            if response != score['response_sent'] or str(score['label']) != f06[qid][f'{index}-{strategy}']:
                raise ValueError(f'{key}: sent answer or F06 label differs')
            kept = set(selection['selected_message_ids'])
            evidence_kept = [e['message_id'] for e in evidence if e['message_id'] in kept]
            if len(evidence_kept) != metric['selected']['n_retained_msgs']:
                raise ValueError(f'{key}: evidence mismatch')
            mapping = {r['turn_id']: r for r in rows(ROOT / 'A-数据线/A03/output/map' /
                                                     f'{qid}.turns.jsonl')}
            candidates = candidate_sets[index][qid]
            evidence_ranks = [{'turn_id': c['turn_id'], 'rank': c['rank']}
                              for c in candidates
                              if kept_evidence(mapping[c['turn_id']]['message_ids'], ev)]
            variants.append({
                'index': index, 'strategy': strategy, 'batch_id': metric['batch_id'],
                'selected_turn_ids': selection['selected_turn_ids'], 'evidence_candidate_ranks': evidence_ranks,
                'evidence_retained_ids': evidence_kept, 'candidate_missing_message_ids':
                    metric['candidate']['missing_message_ids'],
                'diagnosis': metric['diagnosis'], 'cover': metric['cover'],
                'context_tokens': selection['context_tokens'], 'history_sha256': metric['history_sha256'],
                'record_id': score['record_id'], 'response_source': score['response_source'],
                'response_sent': response, 'judge_output': score['judge_output'],
                'judge_label': score['label'], 'f05_review_ids': sorted(set(
                    review_by_id.get(score['record_id'], []))),
                'e04_source': f'{E04_COMMIT}:E/E04/results/g02-v1/{metric["batch_id"]}/answers_for_f.jsonl',
                'f04_source': f'F/scores/formal_g02-v1_{metric["batch_id"]}.jsonl',
            })
        cases.append({'question_id': qid, 'case_type': kind, 'question': q['question'],
                      'reference_answer': ev['answer'], 'evidence': evidence, 'variants': variants})
    by_kind = {case['case_type']: case for case in cases}
    assert [int(v['judge_label']) for v in by_kind['improved']['variants']] == [0, 1]
    assert [int(v['judge_label']) for v in by_kind['regressed']['variants']] == [1, 0]
    more = by_kind['more_evidence_still_wrong']['variants']
    assert [int(v['judge_label']) for v in more] == [0, 0]
    assert len(more[1]['evidence_retained_ids']) > len(more[0]['evidence_retained_ids'])
    assert all(v['diagnosis'] == 'candidates_missing' for v in by_kind['candidates_missing']['variants'])
    assert all(v['diagnosis'] == 'minimal_cover_over_budget' for v in by_kind['minimal_cover_over_budget']['variants'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Validated {len(cases)} cases and {sum(len(c["variants"]) for c in cases)} settings')


def kept_evidence(message_ids, evaluation):
    return bool(set(message_ids) & set(evaluation['evidence_message_ids']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'cases.json')
    args = parser.parse_args()
    main(args.dataset, args.output)
