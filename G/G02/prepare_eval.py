"""Build F/A02 evaluation metadata separately from public D/E inputs."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path

from G.G02.prepare import PLAN, ROOT, read_json, read_rows, source_hash, table


def build(config, dataset, output):
    formal = config['formal']
    manifest_path = ROOT / formal['manifest']
    questions_path = ROOT / formal['public_root'] / 'formal_questions.jsonl'
    a01_builder = ROOT / 'A-数据线/A01/build_a01.py'
    for path in (manifest_path, questions_path, a01_builder):
        if source_hash(path) != config['source_sha256'][path.relative_to(ROOT).as_posix()]:
            raise ValueError(f'Pinned source changed: {path.name}')
    manifest = read_json(manifest_path)
    with dataset.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != manifest['data_sha256']:
            raise ValueError('Source dataset differs from the A03 archive')
        stream.seek(0)
        ids = manifest['formal_ids']
        wanted = set(ids)
        data = [row for row in json.load(stream) if row['question_id'] in wanted]
    indexed = {q['question_id']: q for q in data}
    if len(data) != len(indexed) or set(indexed) != wanted:
        raise ValueError('Official source and manifest have different question IDs')
    public = table(read_rows(questions_path), ids, 'A03 public questions')
    spec = importlib.util.spec_from_file_location('g02_a01', a01_builder)
    a01 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a01)

    evaluation = []
    for qid in ids:
        question, labels, _, turn_map = a01.build_question(indexed[qid])
        archived_map = questions_path.parent.parent / 'map' / (qid + '.turns.jsonl')
        if {**question, 'stage': 'formal'} != public[qid] or turn_map != read_rows(archived_map):
            raise ValueError(f'{qid}: official data does not match the A03 question/turn mapping')
        if labels['is_abstention'] or not labels['evidence_message_ids']:
            raise ValueError(f'{qid}: formal question has no annotated answer evidence')
        evaluation.append(labels)
    if dict(Counter(row['question_type'] for row in evaluation)) != manifest['formal_type_counts']:
        raise ValueError('Rebuilt evaluation file differs from the A03 type counts')
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        for row in evaluation:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
    return {'questions': len(evaluation), 'a03_config_version': manifest['config_version'],
            'eval_sha256': source_hash(output), 'dataset_sha256': actual}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=PLAN)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(read_json(args.config), args.dataset, args.output), indent=2))
