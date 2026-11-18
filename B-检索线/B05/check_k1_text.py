#!/usr/bin/env python3
"""CPU check: our K1 index text equals the patched official corpus text for every turn.

Builds each question's corpus (--stage dev: B05/C03, --stage formal: B06/C04) with the patched official functions
(process_item_flat_index, fetch_expansion_from_cache, resolve_expansion) from the raw
data and C03 cache, maps official corpus ids to public turn ids, and compares strings.
Also checks that every turn without facts has K1 text identical to K0 text.
"""
import argparse
import json
import re
import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shared'))
import kretrieve as K


def official_functions(patched_root):
    sys.modules.setdefault('nltk', types.SimpleNamespace(sent_tokenize=None))  # unused for userfact
    src = (patched_root / 'src/retrieval/run_retrieval.py').read_text()
    ns = {}
    for name in ('process_item_flat_index', '_b05_corpus_id'):  # pure functions; avoid importing torch
        exec(compile(re.search(rf'def {name}.*?\n(?=def )', src, re.S).group(0), name, 'exec'), ns)
    sys.path.insert(0, str(patched_root / 'src/retrieval'))
    import index_expansion_utils
    return ns['process_item_flat_index'], ns['_b05_corpus_id'], index_expansion_utils


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--patched-official', type=Path, required=True)
    p.add_argument('--raw', type=Path, required=True, help='longmemeval_s_cleaned.json')
    p.add_argument('--c03', '--facts-cache', dest='c03', type=Path, required=True, help='C03 or C04 fact file')
    p.add_argument('--stage', choices=['dev', 'formal'], default='dev')
    p.add_argument('--facts', type=Path, required=True, help='turn_id -> facts file from prepare_facts.py')
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    flat, corpus_id, ieu = official_functions(a.patched_official)
    cache = json.loads(a.c03.read_text())
    data = {q['question_id']: q for q in json.loads(a.raw.read_text())}
    spec = K.question_set(a.stage)
    facts = K.load_facts(a.facts)
    total = mismatch = no_fact = no_fact_diff = 0
    for q, turns in K.load_items(spec):
        e = data[q['question_id']]
        sessions = list(zip(e['haystack_session_ids'], e['haystack_sessions'], e['haystack_dates']))
        corpus, ids, ts = [], [], []
        for sid, sess, date in sessions:
            c, i, t = flat(sess, 'turn', sid, date)
            corpus, ids, ts = corpus + c, ids + i, ts + t
        seen = set()  # mirrors fix 3: each corpus id is expanded once
        for sid, sess, date in sessions:
            for ti, turn in enumerate(sess):
                if turn['role'] == 'user':
                    if corpus_id(sid, ti, turn) in seen:
                        continue
                    seen.add(corpus_id(sid, ti, turn))
                    ex = ieu.fetch_expansion_from_cache(cache, sid + f'_{ti + 1}')
                    corpus, ids, ts = ieu.resolve_expansion('turn-userfact', 'merge', corpus, ids, ts, ex,
                                                            corpus_id(sid, ti, turn), date)
        if len(ids) != len(turns):
            raise SystemExit(f'{q["question_id"]}: corpus size {len(ids)} != {len(turns)} public turns')
        to_turn = {r['official_corpus_id']: r['turn_id'] for r in K.jl(spec['map_dir'] / f'{q["question_id"]}.turns.jsonl')}
        k1 = dict(zip([t['turn_id'] for t in turns], K.index_texts(turns, 'K1', facts)))
        k0 = dict(zip([t['turn_id'] for t in turns], K.index_texts(turns, 'K0', None)))
        for cid, text in zip(ids, corpus):
            tid = to_turn[cid]
            total += 1
            mismatch += k1[tid] != text
            if not facts[tid]:
                no_fact += 1
                no_fact_diff += k1[tid] != k0[tid]
    result = {'passed': mismatch == 0 and no_fact_diff == 0, 'turns_compared': total,
              'k1_vs_patched_official_text_mismatches': mismatch,
              'turns_without_facts': no_fact, 'turns_without_facts_k1_differs_from_k0': no_fact_diff}
    K.write_jsonl_atomic(a.report, [result])
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise SystemExit('K1 text check failed')


if __name__ == '__main__':
    main()
