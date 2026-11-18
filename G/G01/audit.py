"""Verify the five G01 development questions against tracked A–E artifacts and optional F02 scores."""
import argparse
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from statistics import mean
import subprocess
import sys


# Transcribed as reported observations, never substituted for raw Judge records.
F02_NOTES = {
    '2318644b': (0, 0), '1cea1afa': (1, 1), 'gpt4_7a0daae1': (0, 1),
    '4c36ccef': (1, 1), 'c960da58': (1, 1),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def keyed(rows, key, name):
    table = {row[key]: row for row in rows}
    require(len(rows) == len(table), f'{name}: duplicate {key}')
    return table


def match_hash(path, expected):
    data = path.read_bytes()
    require(expected in (sha(data), sha(data.replace(b'\r\n', b'\n'))), f'{path}: source hash mismatch')


def fact_key(turn):
    session = turn['official_session_id'].replace('answer_', '').replace('noans_', '')
    return f"{session}_{turn['sort_key'][2] + 1}"


def elapsed_slurm(path, job):
    for line in path.read_text().splitlines():
        cols = line.split()
        if cols[:3] == [str(job), 'COMPLETED', '0:0']:
            require(re.fullmatch(r'\d+:\d\d:\d\d', cols[3]), f'{path}: invalid duration')
            h, m, s = map(int, cols[3].split(':'))
            return 3600*h + 60*m + s
    raise ValueError(f'{path}: no successful Slurm terminal record for {job}')


def audit_c02(archive, expected_sources, facts):
    files = {
        'facts': archive/'c02_facts_5q.json',
        'manifest': archive/'c02_turn_manifest.json',
        'pending': archive/'c02_pending.jsonl',
        'extracted': archive/'c02_extracted.jsonl',
        'retry': archive/'c02_extracted_retry.jsonl',
    }
    require(read_json(files['facts']) == facts, 'C02 final cache differs from the C03 snapshot used by B05')
    manifest = read_json(files['manifest'])
    require(set(manifest) == set(expected_sources) == set(facts), 'C02 manifest does not cover the five histories')
    pending, extracted, retries = [
        keyed(read_rows(files[name]), 'cache_key', f'C02 {name}') for name in ('pending', 'extracted', 'retry')
    ]
    new_keys = {key for key, row in manifest.items() if row['status'] == 'extracted'}
    reused_keys = {key for key, row in manifest.items() if row['status'] == 'reused'}
    require(new_keys | reused_keys == set(facts), 'C02 manifest has an unknown extraction status')
    require(set(pending) == set(extracted) == new_keys and set(retries) <= new_keys,
            'C02 pending, extracted, retry and manifest keys disagree')
    token_fields = ('n_input_tokens', 'n_output_tokens')

    def cost(row):
        return (row['elapsed_s'], *(row['usage'][field] for field in token_fields))

    def totals(rows):
        measures = [cost(row) for row in rows]
        return {
            'elapsed_seconds_sum': round(sum(values[0] for values in measures), 2),
            'input_tokens': sum(values[1] for values in measures),
            'output_tokens': sum(values[2] for values in measures),
        }

    for key, row in manifest.items():
        source = expected_sources[key]
        require(all(row[field] == value for field, value in source.items()) and row['n_facts'] == len(facts[key]),
                f'{key}: C02 source metadata or fact count differs from A01 and the cache')
        if key in reused_keys:
            require(cost(row) == (None, None, None), f'{key}: reused C02 row reports an unexpected current-run cost')
            continue
        request = {field: source[field] for field in ('question_id', 'turn_id', 'official_session_id', 'official_corpus_id')}
        request.update(cache_key=key, user_message=source['source_text'])
        final_row = extracted[key]
        require(pending[key] == request and all(final_row[field] == value for field, value in request.items()),
                f'{key}: C02 extraction input differs from the A01 user message')
        elapsed, in_tokens, out_tokens = cost(final_row)
        require(final_row['status'] == 'extracted' and final_row['facts'] == facts[key] and cost(row) == cost(final_row)
                and type(elapsed) in (int, float) and isfinite(elapsed) and elapsed >= 0
                and type(in_tokens) is int and in_tokens > 0 and type(out_tokens) is int and out_tokens >= 0,
                f'{key}: C02 final ledger, cache or measured cost disagree')

    failures = []
    for key, retry in retries.items():
        final_row = extracted[key]
        # The final ledger includes the metrics from these retry rows.
        require(all(retry[field] == value for field, value in pending[key].items()) and cost(retry) == cost(final_row),
                f'{key}: C02 retry input or usage does not line up with the final ledger')
        require(isinstance(retry['raw'], str) and bool(retry['raw'].strip()),
                f'{key}: C02 retry has no raw output to review')
        if retry['status'] == 'failed':
            require(retry['parse'] == 'none' and retry['facts'] is None and facts[key] == [],
                    f'{key}: failed C02 retry does not map to an empty fallback')
            failures.append({
                'cache_key': key, 'question_id': retry['question_id'], 'turn_id': retry['turn_id'],
                'retry_parse': retry['parse'], 'manifest_status': manifest[key]['status'],
            })
        else:
            require(retry['status'] == 'extracted' and retry['parse'] in ('direct', 'regex')
                    and retry['facts'] == facts[key], f'{key}: successful retry disagrees with final C02 facts')

    return {
        'status': 'archived_ledger_verified',
        'source_sha256': {p.name: sha(p.read_bytes().replace(b'\r\n', b'\n')) for p in files.values()},
        'history_turns': len(facts), 'reused_from_author_cache': len(reused_keys), 'new_extraction_keys': len(new_keys),
        'reused_empty_fact_lists': sum(not facts[key] for key in reused_keys),
        'new_empty_fact_lists': sum(not facts[key] for key in new_keys),
        'recorded_new_extraction_cost': totals(extracted.values()),
        'retry_rows_included_in_recorded_cost': len(retries),
        'included_retry_cost': totals(retries.values()),
        'retry_parse_successes': len(retries) - len(failures),
        'retry_parse_failures_with_empty_fallback': failures,
        'unrecorded': ['exact_extractor_config', 'superseded_attempt_costs_and_statuses',
                       'original_author_cache_cost', 'batch_wall_clock_seconds'],
    }


def run(repo, score_file):
    a = repo/'A-数据线/A01/output'
    b = repo/'B-检索线'
    e = repo/'E/E02'
    rb, rt = e/'results/job-55386', e/'results/job-55287'
    e03 = repo/'E/E03/results/dev5-k0-v1'
    sys.path[:0] = [str(p) for p in (repo, a.parents[1]/'A02', e, repo/'F/src/evaluation')]
    from D.D01.selection import digest, render_context, validate
    from evidence_metrics import Evidence
    from export_for_f import convert
    from prepare_inputs import render_official_topk
    from run_generation import PROMPT
    from judge import choose_response, is_finished, load_latest_scores, record_key

    ids = [row['question_id'] for row in read_json(a/'dev_manifest.json')['first_batch']]
    require(len(ids) == len(set(ids)) == 5 and set(ids) == set(F02_NOTES), 'A01 first-five list changed')
    public = keyed(read_rows(a/'public/dev_questions.jsonl'), 'question_id', 'A01 questions')
    candidate_file = b/'B02/candidates/dev_K0.jsonl'
    source_copy = e/'inputs/sources/b02_candidates.jsonl'
    b_manifest = read_json(b/'B02/results/run_manifest.json')
    d_manifest = read_json(rb/'batch_manifest.json')
    for path in (candidate_file, source_copy):
        match_hash(path, b_manifest['candidate_sha256'])
    candidates_hashes = [v for p, v in d_manifest['input_sha256'].items() if p.endswith('/b02_candidates.jsonl')]
    require(candidates_hashes == [b_manifest['candidate_sha256']], 'B02/D02 manifest lineage differs')
    require(d_manifest['question_ids'] == ids, 'D02 manifest first-five list differs')
    b03 = keyed(read_rows(b/'B03/candidates/dev_K0.jsonl'), 'question_id', 'B03 K0')
    b05_facts_file = b/'B05/inputs/dev_facts_by_turn.jsonl'
    match_hash(b05_facts_file, read_json(b/'B05/results/provenance.json')['facts_sha256'])
    raw_b05 = [row for row in read_rows(b05_facts_file) if row['question_id'] in ids]
    mapped_facts = keyed(raw_b05, 'turn_id', 'B05 first-five facts')
    c02, c03 = [read_json(repo/'C03'/name) for name in ('c02_facts_5q.json', 'dev_facts_all40q.json')]
    require(all(c03.get(k) == v for k, v in c02.items()), 'C02 facts changed in C03')

    files = {
        'B02': candidate_file, 'D02': rb/'selections.jsonl', 'budget_in': rb/'dev5_budget.jsonl',
        'budget_out': rb/'results.jsonl', 'budget_F': rb/'answers_for_f.jsonl',
        'topk_D': e/'inputs/topk_selections.jsonl', 'topk_in': e/'inputs/dev5_topk.jsonl',
        'topk_out': rt/'results.jsonl', 'topk_F': rt/'answers_for_f.jsonl',
    }
    data = {name: keyed(read_rows(path), 'question_id', name) for name, path in files.items()}
    require(all(set(rows) == set(ids) for rows in data.values()), 'A–F question ID sets differ')
    ec, tc = [read_json(path/'config.json') for path in (rb, rt)]
    match_hash(files['budget_in'], ec['input_sha256'])
    match_hash(files['topk_in'], tc['input_sha256'])
    require(ec['tokenizer_fingerprint'] == tc['tokenizer_fingerprint'] == d_manifest['tokenizer_fingerprint'],
            'D/E tokenizer fingerprint differs')
    require(all(ec[k] == tc[k] for k in ('revision', 'model', 'reader', 'dtype', 'max_new_tokens', 'do_sample')),
            'E02 reader settings differ between variants')
    require(d_manifest['runtime_budget_checks_passed'] is True, 'D02 did not pass budget checks')

    evidence = Evidence(a)
    expected_c02_sources, by_qid = {}, []
    f_scores = load_latest_scores(score_file) if score_file else None
    judge_seconds = []
    for qid in ids:
        cand, sel = data['B02'][qid], data['D02'][qid]
        turns = read_rows(a/'public/turns'/f'{qid}.jsonl')
        mapping = keyed(read_rows(a/'map'/f'{qid}.turns.jsonl'), 'turn_id', qid+' A01 map')
        request = cand | {k: public[qid][k] for k in ('question', 'question_date')}
        indexed = validate(request, turns)
        require(set(indexed) == set(mapping), f'{qid}: public turns and map differ')
        ranked = sorted(cand['candidates'], key=lambda x: x['rank'])
        tids = [c['turn_id'] for c in ranked]
        require([c['rank'] for c in ranked] == list(range(1, 101)) and len(set(tids)) == 100,
                f'{qid}: B02 candidate ranks differ from 1..100')
        require(cand == b03[qid], f'{qid}: first-five B03 K0 does not match B02')
        require(sel['config']['input_config_version'] == cand['config_version'] and
                sel['config_id'] == digest(sel['config']), f'{qid}: D02 configuration mismatch')
        require(sel['input_sha256'] == digest({'request': request, 'candidate_turns': [indexed[t] for t in tids]}),
                f'{qid}: D02 request digest differs from the actual B02+A01 inputs')
        trials = sel['candidate_trials']
        require([(t['turn_id'], t['rank'], t['retrieval_score']) for t in trials] ==
                [(c['turn_id'], c['rank'], c['score']) for c in ranked] and
                [t['turn_id'] for t in trials if t['decision'] == 'selected'] == sel['selection_order'],
                f'{qid}: D02 selection trace differs from ranks')
        chosen = sel['selected_turn_ids']
        selected_messages = list(dict.fromkeys(m['message_id'] for tid in chosen for m in indexed[tid]['messages']))
        require(set(chosen) == set(sel['selection_order']) and len(set(chosen)) == len(chosen) and
                selected_messages == sel['selected_message_ids'], f'{qid}: D02 turns or messages disagree')
        historical = render_context([indexed[t] for t in chosen])
        topk, top_ids = render_official_topk([indexed[t] for t in tids[:50]])
        for name, text, turn_ids, sr, conf in (
            ('budget', historical, chosen, sel, ec), ('topk', topk, top_ids, data['topk_D'][qid], tc),
        ):
            inp, res, exported = [data[f'{name}_{tag}'][qid] for tag in ('in', 'out', 'F')]
            sha_text = sha(text.encode())
            require(inp['context'] == res['context'] == text and
                    sr['history_sha256'] == inp['history_sha256'] == res['history_sha256'] == sha_text and
                    sr['selected_turn_ids'] == inp['selected_turn_ids'] == res['selected_turn_ids'] == turn_ids,
                    f'{qid}/{name}: D/E text, fingerprint or selected turns differ')
            require(all(res[k] == inp[k] == sr[k] for k in ('index', 'stage', 'strategy', 'budget_tokens', 'config_version')),
                    f'{qid}/{name}: D/E experiment metadata differs')
            require(all(res[k] == inp[k] == public[qid][k] for k in ('question', 'question_date')),
                    f'{qid}/{name}: A/E question text or date differs')
            require(PROMPT.format(text, inp['question_date'], inp['question']) in res['prompt'],
                    f'{qid}/{name}: archived prompt differs from expected question and history')
            require(res['status'] == 'generated' and not res['hit_output_limit'] and
                    0 < res['output_tokens_including_stop'] <= conf['max_new_tokens'] and
                    convert(res) == exported and choose_response(exported)[0] == res['raw_output'].strip(),
                    f'{qid}/{name}: F02 export is stale or differs from raw E02 response')
        budget_out = data['budget_out'][qid]
        budget_in = data['budget_in'][qid]
        match_hash(rb/'batch_manifest.json', budget_in['source']['regenerated_d02_manifest_sha256'])
        require(sel['history_text'] == historical and sel['budget_tokens'] == 2048 and
                sel['context_tokens'] == budget_in['context_tokens'] == budget_out['context_tokens'] <= 2048 and
                sel['config']['tokenizer_fingerprint'] == budget_in['tokenizer_fingerprint'] == ec['tokenizer_fingerprint'],
                f'{qid}: E02 budget or D02 archive text differs')

        facts_nonempty = 0
        for tid, entry in mapping.items():
            key = fact_key(entry)
            require(key == entry['official_corpus_id'].replace('answer_', '').replace('noans_', ''),
                    f'{qid}: unexpected C02 cache key for {tid}')
            require(key in c02 and isinstance(c02[key], list) and all(isinstance(f, str) for f in c02[key]),
                    f'{qid}: missing or malformed C02 facts for {tid}')
            require(mapped_facts.get(tid) == {'question_id': qid, 'turn_id': tid, 'facts': c02[key]},
                    f'{qid}: C02 and B05 mapped facts differ for {tid}')
            user = indexed[tid]['messages'][0]
            require(user['role'] == 'user' and user['message_id'] == entry['message_ids'][0]
                    and key not in expected_c02_sources, f'{tid}: invalid or duplicate C02 source link')
            expected_c02_sources[key] = {
                'question_id': qid, 'turn_id': tid, 'session_index': entry['session_index'],
                'official_session_id': entry['official_session_id'], 'official_corpus_id': entry['official_corpus_id'],
                'source_message_id': user['message_id'], 'source_role': user['role'], 'source_text': user['content'],
            }
            facts_nonempty += bool(c02[key])

        candidates_evidence, selected_evidence, top_evidence = [evidence.retention(qid, turns_) for turns_ in (tids, chosen, top_ids)]
        require(not candidates_evidence['is_abstention'] and candidates_evidence['has_evidence'], f'{qid}: invalid G01 evidence set')
        costs = {t['turn_id']: t['standalone_context_tokens'] for t in trials}
        inferred_cover = evidence.min_evidence_tokens(qid, tids, costs)
        diagnosis = evidence.diagnose(qid, tids, chosen, costs, budget=2048)
        f_actual = None
        if f_scores is not None:
            ans = data['budget_F'][qid]
            record = f_scores.get(record_key(ans))
            require(is_finished(record, ans) and record['status'] == 'ok' and
                    record['label'] in (0, 1), f'{qid}: F02 score missing, wrong source or not complete')
            require(record.get('judge_model') == 'gpt-4o-2024-08-06' and
                    record.get('judge_model_returned', 'gpt-4o-2024-08-06') == 'gpt-4o-2024-08-06',
                    f'{qid}: F02 Judge model differs')
            f_actual = record['label']
            require(f_actual == F02_NOTES[qid][0], f'{qid}: raw F02 score differs from published notes')
            if isinstance(record.get('judge_elapsed_s'), (float, int)):
                judge_seconds.append(record['judge_elapsed_s'])
        by_qid.append({
            'question_id': qid, 'question_type': candidates_evidence['question_type'],
            'history_turns': len(mapping), 'fact_turns_with_facts': facts_nonempty,
            'candidate_turns': len(tids), 'candidate_msg_retention': candidates_evidence['msg_retention'],
            'selected_turns': len(chosen), 'selected_msg_retention': selected_evidence['msg_retention'],
            'selected_all_retained': selected_evidence['all_retained'],
            'missing_evidence_message_ids': selected_evidence['missing_message_ids'],
            'top50_msg_retention': top_evidence['msg_retention'],
            'budget_history_sha256': budget_out['history_sha256'],
            'a02_diagnosis_using_standalone_token_costs': diagnosis,
            'minimum_cover_standalone_token_sum': inferred_cover if candidates_evidence['all_retained'] else None,
            'budget_context_tokens': budget_out['context_tokens'], 'budget_prompt_tokens': budget_out['input_tokens'],
            'budget_output_tokens': budget_out['output_tokens_including_stop'],
            'budget_gpu_seconds': budget_out['generation_seconds'], 'd02_selection_seconds': sel['selection_elapsed_s'],
            'f02_reported_budget_label': F02_NOTES[qid][0], 'f02_reported_top50_label': F02_NOTES[qid][1],
            'f02_verified_budget_label': f_actual,
        })
    require(set(c02) == set(expected_c02_sources) and len(mapped_facts) == sum(r['history_turns'] for r in by_qid),
            'C02/B05 extra unmapped first-five records')
    c02_ledger = audit_c02(repo/'c02_output', expected_c02_sources, c02)

    formal = repo/'A-数据线/A03/output'
    formal_ids = read_json(formal/'eval/formal_manifest.json')['formal_ids']
    require(len(formal_ids) == len(set(formal_ids)), 'A03 formal manifest has duplicate IDs')
    formal_maps = [row for q in formal_ids for row in read_rows(formal/'map'/f'{q}.turns.jsonl')]
    formal_keys = {fact_key(row) for row in formal_maps}
    methods = 10
    e03_rows = read_rows(e03/'results.jsonl')
    require(len(e03_rows) == 25 and all(r['status'] == 'generated' for r in e03_rows), 'E03 timing sample incomplete')
    e03_time = mean(r['generation_seconds'] for r in e03_rows)
    formal_rows = len(formal_ids)*methods
    return {
        'status': 'technical_checks_passed' if f_scores is not None else 'f02_raw_scores_pending',
        'repo_commit': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
        'f02_budget_score_source': 'raw_f02_verified_against_e02' if f_scores is not None else 'F/EVAL_NOTES.md_only',
        'f02_top50_score_source': 'F/EVAL_NOTES.md_only',
        'provenance': {p.relative_to(repo).as_posix(): sha(p.read_bytes().replace(b'\r\n', b'\n')) for p in files.values()},
        'questions': by_qid,
        'c02_ledger': c02_ledger,
        'summary': {
            'candidate_mean_msg_retention': mean(r['candidate_msg_retention'] for r in by_qid),
            'selected_mean_msg_retention': mean(r['selected_msg_retention'] for r in by_qid),
            'selected_all_retained_count': sum(r['selected_all_retained'] for r in by_qid),
            'c02_keys_mapped_to_b05': len(expected_c02_sources),
            'c02_nonempty_turns': sum(r['fact_turns_with_facts'] for r in by_qid),
            'f02_budget_reported_correct': sum(r['f02_reported_budget_label'] for r in by_qid),
            'f02_top50_reported_correct': sum(r['f02_reported_top50_label'] for r in by_qid),
            'f02_verified_judge_timing_count': len(judge_seconds),
            'f02_judge_seconds_mean': mean(judge_seconds) if judge_seconds else None,
        },
        'scale_planning': {
            'dev_min_questions': len(ids), 'conditions_per_question': methods,
            'dev_answer_rows_per_parameter_set': len(ids)*methods,
            'provisional_formal_questions': len(formal_ids), 'formal_history_turn_occurrences': len(formal_maps),
            'formal_unique_fact_cache_keys': len(formal_keys), 'formal_keys_present_in_c03_unverified_reuse': len(formal_keys & c03.keys()),
            'formal_answer_rows': formal_rows, 'formal_judge_requests_one_per_scorable_answer': formal_rows,
            'b02_observed_retrieval_work_seconds': sum(b_manifest['per_question_elapsed_s'].values()),
            'b04_observed_k0_encoding_seconds': read_json(b/'B04/results/cost.json')['index_build_s'],
            'b05_observed_dev_k1_encoding_seconds': read_json(b/'B05/results/cost.json')['index_build_s'],
            'd02_selection_seconds_mean': mean(r['d02_selection_seconds'] for r in by_qid),
            'e02_budget_generation_seconds_mean': mean(r['budget_gpu_seconds'] for r in by_qid),
            'e02_budget_job_seconds': elapsed_slurm(rb/'slurm_final.txt', 55386),
            'e02_top50_job_seconds': elapsed_slurm(rt/'slurm_final.txt', 55287),
            'e03_generation_seconds_mean': e03_time,
            'e03_dev_min_generation_seconds': len(ids)*methods*e03_time,
            'e03_extrapolated_formal_generation_seconds': formal_rows*e03_time,
            'e03_extrapolated_formal_output_tokens_including_stop': round(formal_rows*mean(r['output_tokens_including_stop'] for r in e03_rows)),
            'c02_fact_extraction_elapsed_seconds': c02_ledger['recorded_new_extraction_cost']['elapsed_seconds_sum'],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--f02-scores', type=Path, help='Real budget job 55386 score file saved by F')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.repo.resolve(), args.f02_scores)
    with args.output.open('w', encoding='utf-8', newline='\n') as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
    print('PASS: A01/B02/B03/C02/B05/D02/E02 and both E→F exports, five questions')
    print('F02 budget scoring:', report['f02_budget_score_source'])
    print('C02 ledger:', report['c02_ledger']['status'])
    print('G01 sign-off is recorded separately in G/G01/ACCEPTANCE.md.')
    if not args.f02_scores:
        print('This rerun did not verify raw F02 scores.')


if __name__ == '__main__':
    main()
