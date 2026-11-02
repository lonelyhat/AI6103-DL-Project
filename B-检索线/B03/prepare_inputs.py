#!/usr/bin/env python3
"""Materialize A01 public histories without modifying existing A01 artifacts."""
import argparse
import json
import sys
from pathlib import Path
from common import A01, ROOT, baseline, module_at, sha
sys.path.insert(0, str(ROOT))
from common import load_inputs


def prepare(source, official_subset, report):
    manifest = json.loads((A01 / 'dev_manifest.json').read_text())
    actual = sha(source)
    if actual != manifest['data_sha256']:
        raise ValueError('Source dataset SHA-256 does not match A01')
    data = json.loads(source.read_text())
    by_id = {q['question_id']: q for q in data}
    if len(by_id) != len(data):
        raise ValueError('Duplicate source question')
    builder = module_at('a01_builder', ROOT / 'A-数据线/A01/build_a01.py')
    public = {q['question_id']: q for q in baseline.read_jsonl(A01 / 'public/dev_questions.jsonl')}
    staged, unchanged = [], []
    for qid in manifest['dev_ids']:
        q = by_id[qid]
        if q['question'] != public[qid]['question'] or q['question_date'] != public[qid]['question_date']:
            raise ValueError(f'{qid}: public question does not match source')
        turns = builder.public_turns(q)
        path = A01 / 'public/turns' / f'{qid}.jsonl'
        if path.exists():
            if baseline.read_jsonl(path) != turns:
                raise ValueError(f'{qid}: existing public turns differ; refusing overwrite')
            unchanged.append(qid)
        else:
            staged.append((path, turns))
    for path, turns in staged:
        baseline.write_jsonl_atomic(path, turns)
    _, items = load_inputs()
    # This private file includes labels, for official comparison only; never a retrieval input.
    official_subset.parent.mkdir(parents=True, exist_ok=True)
    official_subset.write_text(json.dumps([by_id[q] for q in manifest['dev_ids']], ensure_ascii=False))
    official_subset.chmod(0o600)
    result = {'source_sha256': actual, 'source_questions': len(data),
              'generated_public_histories': [p.stem for p, _ in staged],
              'preserved_existing_histories': unchanged,
              'public_turn_counts': {q['question_id']: len(t) for q, t in items},
              'scope': 'all 40; downstream main split is 34 answerable; 6 abstention separate'}
    baseline.write_jsonl_atomic(report, [result])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--official-subset', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    prepare(a.source, a.official_subset, a.report)
