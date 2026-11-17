"""Export the latest unique E03 attempts; preserve raw output and failed statuses."""
import argparse
import importlib.util
import json
from pathlib import Path

from batch import E02_PATH, digest, latest_attempts, load_inputs
spec = importlib.util.spec_from_file_location('e02_export', E02_PATH.with_name('export_for_f.py'))
e02_export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e02_export)


def export(run_dir, output, allow_incomplete=False):
    # Read only, never repair a live writer's journal during export.
    if (run_dir / '.writer.lock').exists():
        raise ValueError('Writer lock present; wait for job to finish')
    if output.resolve().is_relative_to(run_dir.resolve()):
        if output.name in ('attempts.jsonl', 'results.jsonl', 'inputs.jsonl', 'config.json'):
            raise ValueError('Cannot overwrite run artifacts')
    rows = load_inputs(run_dir / 'inputs.jsonl')
    config = json.loads((run_dir / 'config.json').read_text(encoding='utf-8'))
    raw = (run_dir / 'attempts.jsonl').read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('Partial journal; resume to repair before export')
    latest = latest_attempts([json.loads(line) for line in raw.splitlines()], rows, digest(config))
    if not latest or (len(latest) != len(rows) and not allow_incomplete):
        raise ValueError('Incomplete run; resume or explicitly use --allow-incomplete')
    fields = ('record_id', 'input_record_sha256', 'reader_config_id', 'batch_runner_version',
        'selection_config_id', 'selection_config', 'input_config_version', 'selected_turn_ids',
        'input_tokens', 'output_tokens_including_stop', 'generation_seconds', 'peak_allocated_gib',
        'hit_output_limit', 'attempt')
    converted = []
    for row in rows:
        if row['record_id'] not in latest:
            continue
        result = latest[row['record_id']]
        item = e02_export.convert(result)
        item.update({key: result[key] for key in fields if key in result})
        converted.append(item)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as handle:
        for row in converted:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    return len(converted)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-incomplete', action='store_true')
    args = parser.parse_args()
    print(f'Exported {export(args.run_dir, args.output, args.allow_incomplete)} records; no Judge API called.')
