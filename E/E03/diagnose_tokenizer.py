"""CPU-only diagnostics for D/E tokenizer differences; never authorizes generation."""
import argparse
import importlib.metadata
import json
from pathlib import Path

from batch import digest, load_inputs, reader, sha


def diagnose(rows, tokenizer):
    before = tokenizer.backend_tokenizer.to_str()
    records = []
    for row in rows:
        ids = tokenizer.encode(row['context'], add_special_tokens=False)
        records.append({'question_id': row['question_id'], 'index': row['index'],
            'strategy': row['strategy'], 'record_id': row['record_id'],
            'expected_fingerprint': row.get('tokenizer_fingerprint'),
            'expected_tokens': row.get('context_tokens'), 'actual_tokens': len(ids),
            'token_ids_sha256': digest(ids),
            'count_matches': row.get('context_tokens') == len(ids),
            'within_budget': row['variant'] != 'budget' or len(ids) <= row['budget_tokens']})
    after = tokenizer.backend_tokenizer.to_str()
    return {'model': reader.MODEL, 'revision': reader.REVISION,
        'backend_fingerprint_before_encoding': sha(before.encode()),
        'backend_fingerprint_after_encoding': sha(after.encode()),
        'canonical_backend_sha256': digest(json.loads(after)),
        'chat_template_sha256': sha(tokenizer.chat_template.encode()),
        'packages': {p: importlib.metadata.version(p) for p in ('transformers','tokenizers')},
        'records': records, 'generation_performed': False,
        'warning': 'Matching counts alone do not prove tokenizer equivalence. Keep strict generation checks.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = load_inputs(args.input)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(reader.MODEL, revision=reader.REVISION, local_files_only=True)
    report = diagnose(rows, tokenizer)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f'Diagnostics saved to {args.output}; no generation or fingerprint override.')
