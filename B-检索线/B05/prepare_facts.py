#!/usr/bin/env python3
"""Convert C-line facts (official cache keys) to public turn_id -> facts.

--stage dev uses C03 for the 40 development questions (B05); --stage formal uses C04 for the
80 formal questions (B06).

C03 key = <official session id without answer_/noans_>_<user message position + 1>
(official `turn-userfact` cache format).  The A01 map is used only for this join; the output
contains public turn IDs and fact text only, so the retrieval step never sees official IDs.

Value normalisation follows the official reader: a string becomes [string], other list
items go through str().  Empty lists mean "no facts" (K1 text = original user text).
"""
import argparse
import collections
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shared'))
from kretrieve import jl, load_items, question_set, sha, write_jsonl_atomic


def cache_key(official_session_id, position):
    return official_session_id.replace('answer_', '').replace('noans_', '') + f'_{position + 1}'


def normalise(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(x) for x in value]


def prepare(facts_path, out, report, stage='dev', sources=None):
    spec = question_set(stage)
    cache = json.loads(facts_path.read_text())
    rows, used, kinds, source_rows = [], set(), collections.Counter(), []
    missing, per_q = [], {}
    for q, turns in load_items(spec):
        qid = q['question_id']
        mapping = {r['turn_id']: r for r in jl(spec['map_dir'] / f'{qid}.turns.jsonl')}
        with_facts = 0
        for t in turns:
            m = mapping[t['turn_id']]
            key = cache_key(m['official_session_id'], m['sort_key'][2])
            if key not in cache:
                missing.append(t['turn_id'])
                continue
            used.add(key)
            raw = cache[key]
            kinds['string' if isinstance(raw, str) else 'none' if raw is None else
                  'empty_list' if not raw else
                  'list_with_non_string' if any(not isinstance(x, str) for x in raw) else 'list_of_strings'] += 1
            facts = normalise(raw)
            with_facts += bool(facts)
            rows.append({'question_id': qid, 'turn_id': t['turn_id'], 'facts': facts})
            source_rows.append({'question_id': qid, 'turn_id': t['turn_id'], 'fact_key': key,
                                'source_message_id': t['messages'][0]['message_id'], 'n_facts': len(facts)})
        per_q[qid] = {'turns': len(turns), 'turns_with_facts': with_facts}
    if missing:
        raise SystemExit(f'{len(missing)} turns have no C03 record, e.g. {missing[:5]}')
    write_jsonl_atomic(out, rows)
    if sources is not None:  # fact provenance: which C-line record each turn's facts came from
        write_jsonl_atomic(sources, source_rows)
    result = {'stage': stage, 'facts_file': facts_path.name, 'facts_sha256': sha(facts_path), 'fact_keys': len(cache),
              'fact_keys_used': len(used), 'fact_keys_unused': sorted(set(cache) - used),
              'turn_records': len(rows), 'turns_with_facts': sum(bool(r['facts']) for r in rows),
              'turns_without_facts': sum(not r['facts'] for r in rows),
              'value_kinds': dict(kinds), 'per_question': per_q,
              'output_sha256': sha(out)}
    write_jsonl_atomic(report, [result])
    print(json.dumps({k: v for k, v in result.items() if k != 'per_question'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('facts', type=Path, help='C03/dev_facts_all40q.json or C04/c04_facts_80q.json')
    p.add_argument('--stage', choices=['dev', 'formal'], default='dev')
    p.add_argument('--sources', type=Path, help='optional turn_id -> fact key provenance file')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    prepare(a.facts, a.out, a.report, a.stage, a.sources)
