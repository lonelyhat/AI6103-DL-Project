"""Validated batch identities and durable, resumable generation journals (stdlib only)."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import time

E02_PATH = Path(__file__).resolve().parents[1] / 'E02/run_generation.py'
spec = importlib.util.spec_from_file_location('e02_reader', E02_PATH)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())


def normalize(source):
    required = ('question_id', 'question', 'question_date', 'stage', 'index', 'strategy',
                'variant', 'tokenizer', 'config_version', 'history_sha256')
    for key in required:
        if not isinstance(source.get(key), str) or not source[key].strip():
            raise ValueError(f'Missing/non-string {key}')
    if source['stage'] not in ('dev', 'formal') or source['index'] not in ('K0', 'K1'):
        raise ValueError('Expected dev/formal and K0/K1')
    if source['tokenizer'] != reader.MODEL:
        raise ValueError('Reader tokenizer must match E01/E02')
    context = source.get('context')
    if not isinstance(context, str) or sha(context.encode()) != source['history_sha256']:
        raise ValueError('Context hash mismatch')
    variant = source['variant']
    if variant not in ('budget', 'original_topk'):
        raise ValueError('Unknown variant')
    setting = 'budget_tokens' if variant == 'budget' else 'topk'
    if type(source.get(setting)) is not int or source[setting] <= 0:
        raise ValueError(f'Requires positive integer {setting}')
    if variant == 'budget':
        if source['strategy'] not in ('R', 'MMR', 'C', 'Q', 'FL'):
            raise ValueError('Unknown budget strategy')
        if not source.get('tokenizer_fingerprint'):
            raise ValueError('Budget material requires tokenizer_fingerprint')
        if type(source.get('context_tokens')) is not int or not 0 <= source['context_tokens'] <= source[setting]:
            raise ValueError('Invalid declared context_tokens/budget')
    elif source['strategy'] != 'original_topk':
        raise ValueError('Top-k reference must use original_topk strategy')
    selected = source.get('selected_turn_ids')
    if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected) or len(selected) != len(set(selected)):
        raise ValueError('Invalid or duplicate selected_turn_ids')
    # Allowlist prevents gold answers/evidence labels from reaching the reader.
    fields = required + ('context', 'budget_tokens', 'topk', 'context_tokens',
                         'tokenizer_fingerprint', 'selected_turn_ids', 'serialization',
                         'input_config_version', 'selection_config', 'selection_config_id', 'source')
    row = {key: source[key] for key in fields if key in source}
    row.setdefault('budget_tokens', None)
    if 'selection_config' in row:
        if digest(row['selection_config']) != row.get('selection_config_id'):
            raise ValueError('Selection config hash mismatch')
    identity = {key: row.get(key) for key in ('question_id', 'stage', 'index', 'strategy',
                'variant', 'budget_tokens', 'topk', 'config_version', 'input_config_version',
                'selection_config_id')}
    row['record_id'] = digest(identity)
    row['input_record_sha256'] = digest(row)
    return row


def load_inputs(path):
    rows = [normalize(json.loads(line)) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if not rows or len({r['record_id'] for r in rows}) != len(rows):
        raise ValueError('Empty batch or duplicate question/index/strategy/config input')
    return rows


def atomic_text(path, text):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def save_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def append(path, row):
    with path.open('a', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


@contextlib.contextmanager
def run_lock(output):
    path = output / '.writer.lock'
    # Never auto-remove a stale lock: its owner may be on another compute node.
    with path.open('x', encoding='utf-8') as handle:
        json.dump({'host': socket.gethostname(), 'pid': os.getpid(),
                   'slurm_job_id': os.environ.get('SLURM_JOB_ID')}, handle)
    try:
        yield
    finally:
        path.unlink()


def read_journal(path):
    if not path.exists():
        return []
    data = path.read_bytes()
    # Newline is the commit marker. Preserve a torn final write before repair.
    if data and not data.endswith(b'\n'):
        end = data.rfind(b'\n') + 1
        backup = path.with_name(f'attempts.partial-{time.time_ns()}.bin')
        backup.write_bytes(data[end:])
        with path.open('r+b') as handle:
            handle.truncate(end)
            handle.flush()
            os.fsync(handle.fileno())
        data = data[:end]
    # Malformed complete lines are corruption, not recoverable partial writes.
    return [json.loads(line) for line in data.splitlines()]


def latest_attempts(attempts, rows, config_id):
    inputs = {r['record_id']: r for r in rows}
    latest = {}
    for row in attempts:
        rid = row.get('record_id')
        if rid not in inputs or row.get('reader_config_id') != config_id:
            raise ValueError('Journal record/config does not belong to this batch')
        if row.get('input_record_sha256') != inputs[rid]['input_record_sha256']:
            raise ValueError('Journal input changed')
        previous = latest.get(rid)
        if row.get('attempt') != (previous['attempt'] + 1 if previous else 1):
            raise ValueError('Duplicate or nonsequential journal attempt')
        if previous and previous['status'] != 'technical_failure':
            raise ValueError('Completed answer was unexpectedly regenerated')
        if row.get('status') not in ('generated', 'truncated', 'empty', 'technical_failure'):
            raise ValueError('Unknown journal status')
        latest[rid] = row
    return latest


def snapshot(output, rows, latest, attempts):
    ordered = [latest[r['record_id']] for r in rows if r['record_id'] in latest]
    atomic_text(output / 'results.jsonl', ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ordered))
    counts = {s: sum(r['status'] == s for r in ordered)
              for s in ('generated', 'truncated', 'empty', 'technical_failure')}
    report = {'expected': len(rows), 'recorded': len(ordered), 'missing': len(rows)-len(ordered),
              'statuses': counts, 'attempts': attempts,
              'needs_review': sum(r.get('parse_status') == 'needs_review' for r in ordered),
              'all_generated': len(ordered) == len(rows) and counts['generated'] == len(rows),
              'scored': False}
    save_json(output / 'summary.json', report)
    return report


def run_batch(rows, prepared, output, config, generate, resume=False, stop_after=None):
    """generate is lazy: a fully completed resume never loads model weights."""
    output = Path(output)
    if resume:
        if not output.is_dir():
            raise ValueError('Resume directory does not exist')
    else:
        output.mkdir(parents=True, exist_ok=False)
    config_id = digest(config)
    with run_lock(output):
        config_path = output / 'config.json'
        if resume:
            saved = json.loads(config_path.read_text(encoding='utf-8'))
            if saved != config:
                raise ValueError('Input/config/environment/code changed; use a new output directory')
        else:
            save_json(config_path, config)
            atomic_text(output / 'inputs.jsonl', ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
        attempts = read_journal(output / 'attempts.jsonl')
        latest = latest_attempts(attempts, rows, config_id)
        append(output / 'invocations.jsonl', {'time_unix': time.time(), 'resume': resume,
               'host': socket.gethostname(), 'slurm_job_id': os.environ.get('SLURM_JOB_ID'),
               'git_commit': reader.git_value('rev-parse', 'HEAD'),
               'git_status': reader.git_value('status', '--short')})
        snapshot(output, rows, latest, len(attempts))
        count = 0
        for item in prepared:
            row = item['record']
            previous = latest.get(row['record_id'])
            if previous and previous['status'] != 'technical_failure':
                continue  # truncated/empty need review, never silently select a better retry.
            result = dict(row, prompt=item['prompt'], input_tokens=item['input_tokens'],
                          context_tokens=item['context_tokens'], reader_config_id=config_id,
                          reader_config_version='e02-v2', batch_runner_version='e03-v1',
                          attempt=previous['attempt'] + 1 if previous else 1,
                          slurm_job_id=os.environ.get('SLURM_JOB_ID'))
            error = None
            started = time.perf_counter()
            try:
                result.update(generate(item))
            except Exception as exc:
                error = exc
                result.update(status='technical_failure', raw_output='', hypothesis='',
                              extracted_answer=None, parse_status='needs_review',
                              error=f'{type(exc).__name__}: {exc}',
                              failed_attempt_seconds=time.perf_counter()-started)
            append(output / 'attempts.jsonl', result)
            latest[row['record_id']] = result
            attempts.append(result)
            snapshot(output, rows, latest, len(attempts))
            print(f"{row['question_id']} {row['index']}/{row['strategy']}: {result['status']}", flush=True)
            if error is not None:
                raise error  # Restart in a fresh process after resolving a technical failure.
            count += 1
            if stop_after is not None and count >= stop_after:
                break
        return snapshot(output, rows, latest, len(attempts))
