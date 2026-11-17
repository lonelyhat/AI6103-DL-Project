"""Export E02 outputs to F's interface without overwriting raw run artifacts."""
import argparse
import json
from pathlib import Path

FIELDS = ('question_id', 'stage', 'index', 'strategy', 'budget_tokens', 'tokenizer', 'config_version',
          'variant', 'topk', 'history_sha256', 'reader_config_version', 'parse_status', 'context_tokens')


def convert(row):
    for key in ('question_id', 'stage', 'index', 'strategy', 'budget_tokens', 'tokenizer',
                'config_version', 'variant', 'raw_output', 'hypothesis', 'status'):
        if key not in row:
            raise ValueError(f'Missing E02 output field: {key}')
    status = row['status']
    if status not in ('generated', 'truncated', 'empty', 'technical_failure'):
        raise ValueError(f'Unknown generation status: {status}')
    if status == 'generated' and (not row['raw_output'].strip() or row.get('hit_output_limit')):
        raise ValueError('Inconsistent successful generation')
    result = {k: row[k] for k in FIELDS if k in row}
    result.update(raw_output=row['raw_output'], hypothesis=row['hypothesis'],
                  generation_status=status, status='ok' if status == 'generated' else status,
                  error=row.get('error'), needs_review=row.get('parse_status') == 'needs_review')
    return result


def export(source, dest):
    if source.resolve() == dest.resolve():
        raise ValueError('Do not overwrite raw E02 results')
    rows = [convert(json.loads(line)) for line in source.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    keys = [(r['question_id'], r['index'], r['strategy'], r['variant'], r.get('topk'), r['config_version']) for r in rows]
    if not rows or len(keys) != len(set(keys)):
        raise ValueError('Empty or duplicate E02 results')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('x', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return len(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(f'Exported {export(args.input, args.output)} records; no Judge API called.')
