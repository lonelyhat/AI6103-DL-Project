"""Check A03/C04/B04/B06 from one Git commit without checking out the branch."""
import argparse
from collections import defaultdict
import io
import json
from pathlib import Path
from statistics import mean
import subprocess
import tarfile

from audit import fact_key, keyed, require, sha

A03 = 'A-数据线/A03/output'
B04 = 'B-检索线/B04'
B06 = 'B-检索线/B06'
MANIFEST = f'{A03}/eval/formal_manifest.json'
PUBLIC_QUESTIONS = f'{A03}/public/formal_questions.jsonl'
C04_FACTS = 'C04/c04_facts_80q.json'
C04_MANIFEST = 'C04/c04_turn_manifest.json'
B06_FACTS = f'{B06}/inputs/formal_facts_by_turn.jsonl'


def content(snapshot, name):
    return snapshot.extractfile(name).read()


def json_at(snapshot, name):
    return json.loads(content(snapshot, name))


def rows_at(snapshot, name):
    return [json.loads(line) for line in content(snapshot, name).splitlines() if line.strip()]


def normalized_facts(value):
    if isinstance(value, str):
        return [value]
    require(isinstance(value, list), 'Unexpected C04 fact type')
    return [str(fact) for fact in value]


def inspect_handoffs(snapshot):
    manifest = json_at(snapshot, MANIFEST)
    ids = manifest['formal_ids']
    require(len(ids) == len(set(ids)) == manifest['actual_count'], 'A03 formal IDs are invalid')
    questions = keyed(rows_at(snapshot, PUBLIC_QUESTIONS), 'question_id', 'A03 public questions')
    require(set(questions) == set(ids) and all(q['stage'] == 'formal' for q in questions.values()),
            'A03 public questions differ from its formal manifest')

    expected_sources, source_text, public_inputs = {}, {}, []
    key_questions, key_source_text = defaultdict(set), {}
    for qid in ids:
        turns = rows_at(snapshot, f'{A03}/public/turns/{qid}.jsonl')
        turn_map = keyed(rows_at(snapshot, f'{A03}/map/{qid}.turns.jsonl'), 'turn_id', f'{qid} map')
        require(len(turns) == len(turn_map) and {t['turn_id'] for t in turns} == set(turn_map),
                f'{qid}: A03 public and mapped turns differ')
        public_inputs.append({'question': questions[qid], 'turns': turns})
        for turn in turns:
            tid = turn['turn_id']
            first = turn['messages'][0]
            require(first['role'] == 'user' and first['message_id'] == turn_map[tid]['message_ids'][0],
                    f'{tid}: fact source is not the mapped user message')
            key = fact_key(turn_map[tid])
            require(key_source_text.setdefault(key, first['content']) == first['content'],
                    f'{key}: a shared fact key points to different A03 user texts')
            expected_sources[tid] = (qid, key, first['message_id'])
            source_text[tid] = first['content']
            key_questions[key].add(qid)

    fact_cache = json_at(snapshot, C04_FACTS)
    fact_manifest = json_at(snapshot, C04_MANIFEST)
    require(set(fact_cache) == set(fact_manifest) == set(key_questions), 'C04 cache does not cover A03')
    shared = {key: set(qids) for key, qids in json_at(snapshot, 'C04/c04_shared_keys.json').items()}
    require(shared == {key: qids for key, qids in key_questions.items() if len(qids) > 1},
            'C04 shared keys differ from A03 map')
    facts = {key: normalized_facts(value) for key, value in fact_cache.items()}
    raw_string_counts = []
    for key, line in fact_manifest.items():
        tid = line['turn_id']
        require(expected_sources.get(tid) == (line['question_id'], key, line['source_message_id']) and
                line['source_role'] == 'user' and line['source_text'] == source_text[tid],
                f'{key}: C04 manifest source does not match A03')
        if len(facts[key]) != line['n_facts']:
            raw = fact_cache[key]
            require(isinstance(raw, str) and line['n_facts'] == len(raw),
                    f'{key}: unexpected fact-count mismatch in C04 manifest')
            raw_string_counts.append(key)

    sources = keyed(rows_at(snapshot, f'{B06}/inputs/formal_fact_sources.jsonl'), 'turn_id', 'B06 fact sources')
    by_turn = keyed(rows_at(snapshot, B06_FACTS), 'turn_id', 'B06 indexed facts')
    require(set(sources) == set(by_turn) == set(expected_sources), 'B06 facts miss one or more A03 turns')
    for tid, (qid, key, message_id) in expected_sources.items():
        s = sources[tid]
        require((s['question_id'], s['fact_key'], s['source_message_id'], s['n_facts']) ==
                (qid, key, message_id, len(facts[key])) and by_turn[tid]['question_id'] == qid and
                by_turn[tid]['facts'] == facts[key], f'{tid}: B06 facts differ from mapped C04 source')
    prepared = json_at(snapshot, f'{B06}/results/facts_preparation.json')
    facts_hash = sha(content(snapshot, B06_FACTS))
    require(prepared['facts_sha256'] == sha(content(snapshot, C04_FACTS)) and
            prepared['output_sha256'] == facts_hash, 'C04/B06 fact archive SHA-256 differs')
    nonempty_turns = sum(bool(row['facts']) for row in by_turn.values())
    require(prepared['fact_keys_used'] == len(facts) and prepared['turn_records'] == len(by_turn) and
            prepared['turns_with_facts'] == nonempty_turns and
            prepared['turns_without_facts'] == len(by_turn) - nonempty_turns,
            'B06 fact preparation summary differs from verified inputs')

    manifest_hash = sha(content(snapshot, MANIFEST))
    public_hash = sha(json.dumps(public_inputs, sort_keys=True, ensure_ascii=False,
                                 allow_nan=False, separators=(',', ':')).encode('utf-8'))
    provenance, ranked, costs = {}, {}, {}
    for index, branch in [('K0', B04), ('K1', B06)]:
        p = provenance[index] = json_at(snapshot, f'{branch}/results/provenance.json')
        require(p['manifest_sha256'] == manifest_hash and p['public_inputs_sha256'] == public_hash,
                f'{index}: provenance differs from A03 formal snapshot')
        require(p['facts_sha256'] == (facts_hash if index == 'K1' else None), f'{index}: wrong fact input')
        name = f'formal_{index}.jsonl'
        candidate_file = f'{branch}/candidates/{name}'
        validation = json_at(snapshot, f'{branch}/results/validation.json')
        require(validation['passed'] and validation['candidate_sha256'][name] == sha(content(snapshot, candidate_file)),
                f'{index}: candidate archive does not pass its SHA-256 check')
        rows = rows_at(snapshot, candidate_file)
        require([row['question_id'] for row in rows] == ids, f'{index}: candidate question order differs from A03')
        ranked[index] = {}
        for row in rows:
            qid = row['question_id']
            config = p['config']
            require((row['stage'], row['index'], row['config_version'], row['strategy']) ==
                    ('formal', index, manifest['config_version'], None) and
                    row['budget_tokens'] == config['budget_tokens'] and row['tokenizer'] == config['tokenizer'],
                    f'{qid}/{index}: candidate metadata differs from provenance')
            items = row['candidates']
            tids = [item['turn_id'] for item in items]
            require(len(set(tids)) == len(tids) == 100 and [x['rank'] for x in items] == list(range(1, 101))
                    and all(tid in expected_sources and expected_sources[tid][0] == qid for tid in tids),
                    f'{qid}/{index}: candidates are incomplete, duplicated or outside the question history')
            ranked[index][qid] = tids
        cost = costs[index] = json_at(snapshot, f'{branch}/results/cost.json')
        require(cost['identity'] == p['identity'] and cost['questions'] == len(ids) and
                cost['indexed_turns'] == len(by_turn), f'{index}: timing record does not match candidate batch')

    k0, k1 = provenance['K0'], provenance['K1']
    require(all(k0[field] == k1[field] for field in ('software', 'model_sha256', 'source_sha256')),
            'K0/K1 retrieval environment, source code or model differ')
    settings = [{key: value for key, value in p['config'].items() if key not in ('index', 'retrieval_text')}
                for p in (k0, k1)]
    require(settings[0] == settings[1], 'K0/K1 non-index configuration differs')
    overlaps = [len(set(ranked['K0'][qid]) & set(ranked['K1'][qid])) for qid in ids]
    by_status = {status: [r for r in fact_manifest.values() if r['status'] == status]
                 for status in ('reused', 'extracted')}
    reused, extracted = by_status['reused'], by_status['extracted']
    require(len(reused) + len(extracted) == len(fact_manifest), 'Unexpected C04 extraction status')
    require(all(isinstance(r['elapsed_s'], (float, int)) and
                all(type(r['usage'].get(k)) is int for k in ('n_input_tokens', 'n_output_tokens')) for r in extracted),
            'Missing timing or token usage for newly extracted C04 facts')
    return {
        'a03_config_version': manifest['config_version'], 'a03_manifest_sha256': manifest_hash,
        'a03_public_inputs_sha256': public_hash, 'formal_questions': len(ids),
        'candidates_per_index': len(ids)*100, 'history_turns': len(by_turn),
        'k0_k1_candidate_overlap': {'mean': mean(overlaps), 'min': min(overlaps), 'max': max(overlaps)},
        'c04': {
            'cache_keys': len(facts), 'cache_keys_shared_between_questions': len(shared),
            'turns_with_nonempty_facts': nonempty_turns,
            'reused_from_cache': len(reused), 'newly_extracted': len(extracted),
            'legacy_string_counts_in_c04_manifest': sorted(raw_string_counts),
            'measured_extraction_seconds_sum': round(sum(r['elapsed_s'] for r in extracted), 3),
            'new_extraction_input_tokens': sum(r['usage']['n_input_tokens'] for r in extracted),
            'new_extraction_output_tokens': sum(r['usage']['n_output_tokens'] for r in extracted),
        },
        'index_build_seconds': {index: costs[index]['index_build_s'] for index in ('K0', 'K1')},
        'query_retrieval_seconds': {index: costs[index]['retrieval_s'] for index in ('K0', 'K1')},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--ref', default='origin/main', help='Git ref containing A03, B04, C04 and B06')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Archive the committed bytes, regardless of the local Windows checkout setting.
    git = ['git', '-C', str(args.repo.resolve()), '-c', 'core.autocrlf=false']
    revision = subprocess.check_output(git + ['rev-parse', '--verify', f'{args.ref}^{{commit}}'], text=True).strip()
    paths = [MANIFEST, f'{A03}/public', f'{A03}/map', 'C04',
             f'{B04}/candidates', f'{B04}/results', f'{B06}/candidates', f'{B06}/inputs', f'{B06}/results']
    archive = subprocess.check_output(git + ['archive', '--format=tar', revision, *paths])
    with tarfile.open(fileobj=io.BytesIO(archive)) as snapshot:
        report = {'formal_data_commit': revision, **inspect_handoffs(snapshot)}
    with args.output.open('w', encoding='utf-8', newline='\n') as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
    print(f"PASS: {report['formal_questions']} A03 questions, matched B04/B06 sets and C04 fact sources")


if __name__ == '__main__':
    main()
