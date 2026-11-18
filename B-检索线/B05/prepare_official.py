#!/usr/bin/env python3
"""Copy the official LongMemEval code and apply three minimal K1 fixes for the comparison run.

Fix 1 (index_expansion_utils.py, resolve_expansion): a turn whose fact list is empty or
  missing keeps its original user text.  Unpatched, an empty list [] removes the turn from
  the corpus entirely, and None turns into ' ' + text.
Fix 2 (run_retrieval.py, turn-level expansion): the merge target is the turn's real corpus id.
  Unpatched, non-evidence turns inside evidence sessions are stored as 'noans_..._N' but the
  merge looks for 'answer_..._N', so those turns silently get no facts (label-dependent index).
Fix 3 (run_retrieval.py, turn-level expansion): each corpus id is expanded once.  Unpatched, a
  history that repeats an identical session (same session id) merges the facts into every copy
  once per occurrence, so each copy ends up as 'facts facts text'.  No effect when ids are unique.

Everything else (encoder, truncation, pooling, merge text = ' '.join(facts) + ' ' + text,
str() of non-string facts, ranking) is untouched.  Each replacement must match exactly once.
"""
import argparse
import shutil
from pathlib import Path

FIX1_OLD = """        if cur_item_expansions is None:
            # For failed expansions, we treat it as if the expansion is an empty string
            cur_item_expansions = [""]
"""
FIX1_NEW = """        if not cur_item_expansions:
            # B05 fix 1: no facts -> keep the original turn text unchanged
            return existing_corpus, existing_corpus_ids, existing_corpus_timestamps
"""
FIX2_OLD = "cur_item_expansions, cur_sess_id + f'_{cur_turn_id+1}', ts)"
FIX2_NEW = "cur_item_expansions, _b05_corpus_id(cur_sess_id, cur_turn_id, cur_turn_content), ts)"
FIX2_HELPER_ANCHOR = "def batch_get_retrieved_context_and_eval("
FIX3_INIT_OLD = "                elif 'turn' in args.index_expansion_method:\n"
FIX3_INIT_NEW = FIX3_INIT_OLD + "                    _b05_seen = set()  # B05 fix 3: expand each corpus id once\n"
FIX3_SKIP_OLD = "                                cur_item_expansions = fetch_expansion_from_cache(index_expansion_result_cache, cur_sess_id + f'_{cur_turn_id+1}')\n"
FIX3_SKIP_NEW = ("                                if _b05_corpus_id(cur_sess_id, cur_turn_id, cur_turn_content) in _b05_seen:\n"
                 "                                    continue\n"
                 "                                _b05_seen.add(_b05_corpus_id(cur_sess_id, cur_turn_id, cur_turn_content))\n"
                 + FIX3_SKIP_OLD)
FIX2_HELPER = '''def _b05_corpus_id(sess_id, i_turn, turn):
    # B05 fix 2: same id rule as process_item_flat_index (noans_ for non-evidence turns)
    cid = sess_id + '_' + str(i_turn + 1)
    if 'answer' in sess_id and not turn.get('has_answer'):
        cid = cid.replace('answer', 'noans')
    return cid


'''


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise SystemExit(f'{path.name}: expected exactly one match, found {text.count(old)}')
    path.write_text(text.replace(old, new))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('official', type=Path, help='unmodified official LongMemEval checkout')
    p.add_argument('dest', type=Path, help='new directory for the patched copy')
    a = p.parse_args()
    if a.dest.exists():
        raise SystemExit(f'{a.dest} exists; refusing to overwrite')
    shutil.copytree(a.official, a.dest, ignore=shutil.ignore_patterns('__pycache__', '.git'))
    r = a.dest / 'src/retrieval'
    replace_once(r / 'index_expansion_utils.py', FIX1_OLD, FIX1_NEW)
    replace_once(r / 'run_retrieval.py', FIX2_OLD, FIX2_NEW)
    replace_once(r / 'run_retrieval.py', FIX2_HELPER_ANCHOR, FIX2_HELPER + FIX2_HELPER_ANCHOR)
    replace_once(r / 'run_retrieval.py', FIX3_INIT_OLD, FIX3_INIT_NEW)
    replace_once(r / 'run_retrieval.py', FIX3_SKIP_OLD, FIX3_SKIP_NEW)
    print(f'Patched copy written to {a.dest}')


if __name__ == '__main__':
    main()
