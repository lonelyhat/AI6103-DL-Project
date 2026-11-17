#!/usr/bin/env python3
"""B04 input preparation: materialize A03 formal histories with A01's unchanged builders.

Writes (never overwrites differing files):
  A-数据线/A03/output/public/turns/{qid}.jsonl   public turns for retrieval/selection/answering
  A-数据线/A03/output/map/{qid}.{messages,turns}.jsonl   ID mapping (evaluation only, never a selector input)
  <official subset>   labelled raw questions, private, only for the official comparison run
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shared'))
from kretrieve import A03, ROOT, jl, load_items, module_at, question_set, sha, write_jsonl_atomic


def put(path, rows, written, kept):
    if path.exists():
        if jl(path) != rows:
            raise ValueError(f'{path}: existing file differs; refusing overwrite')
        kept.append(path.name)
    else:
        written.append((path, rows))


def prepare(source, official_subset, report):
    spec = question_set('formal')
    if sha(source) != spec['data_sha256']:
        raise ValueError('Source dataset SHA-256 does not match A03')
    data = json.loads(source.read_text())
    by_id = {q['question_id']: q for q in data}
    if len(by_id) != len(data):
        raise ValueError('Duplicate source question')
    a01 = module_at('a01_builder', ROOT / 'A-数据线/A01/build_a01.py')
    public = {q['question_id']: q for q in jl(spec['questions_path'])}
    written, kept, unreachable = [], [], {}
    for qid in spec['ids']:
        q = by_id[qid]
        if (q['question'], q['question_date']) != (public[qid]['question'], public[qid]['question_date']):
            raise ValueError(f'{qid}: public question does not match source')
        _, ev, msgs, turns = a01.build_question(q)
        if ev['unreachable_evidence_message_ids']:
            unreachable[qid] = ev['unreachable_evidence_message_ids']
        put(A03 / 'public/turns' / f'{qid}.jsonl', a01.public_turns(q), written, kept)
        put(A03 / 'map' / f'{qid}.messages.jsonl', msgs, written, kept)
        put(A03 / 'map' / f'{qid}.turns.jsonl', turns, written, kept)
    for path, rows in written:
        write_jsonl_atomic(path, rows)
    items = load_items(spec)
    official_subset.parent.mkdir(parents=True, exist_ok=True)
    official_subset.write_text(json.dumps([by_id[q] for q in spec['ids']], ensure_ascii=False))
    official_subset.chmod(0o600)
    result = {'source_sha256': spec['data_sha256'], 'formal_questions': len(spec['ids']),
              'written_files': len(written), 'unchanged_existing_files': len(kept),
              'public_turn_counts': {q['question_id']: len(t) for q, t in items},
              'total_public_turns': sum(len(t) for _, t in items),
              'unreachable_evidence_message_ids': unreachable,
              'builders': 'A01 build_question() / public_turns(), unchanged'}
    write_jsonl_atomic(report, [result])
    print(json.dumps({k: v for k, v in result.items() if k != 'public_turn_counts'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--official-subset', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    prepare(a.source, a.official_subset, a.report)
