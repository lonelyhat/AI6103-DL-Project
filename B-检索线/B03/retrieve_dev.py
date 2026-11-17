#!/usr/bin/env python3
"""Run all A01 development questions with B02's unchanged Stella embedding path."""
import argparse
import fcntl
import json
import math
import sys
import time
from pathlib import Path
from common import A01, ROOT, B02, baseline, digest, jl, load_inputs, public_row, settings, sha
sys.path.insert(0, str(ROOT))


def check_row(row, question, turns, config):
    from D.D01.selection import validate
    if set(row) != set(public_row(question, [], config)):
        raise ValueError('Unexpected candidate record fields')
    expected = public_row(question, [], config)
    if any(row[k] != expected[k] for k in expected if k != 'candidates'):
        raise ValueError('Candidate metadata mismatch')
    candidates = row['candidates']
    if len(candidates) != 100 or [c['rank'] for c in candidates] != list(range(1, 101)):
        raise ValueError('Expected exactly 100 sequentially ranked candidates')
    scores = [c['score'] for c in candidates]
    if not all(type(s) in (float, int) and math.isfinite(s) for s in scores):
        raise ValueError('Non-finite scores')
    if any(a < b for a, b in zip(scores, scores[1:])):
        raise ValueError('Scores not descending')
    validate(dict(row, question=question['question'], question_date=question['question_date']), turns)


def run_questions(items, config, identity, checkpoint, resume, score_question):
    """Persist successes after every question; never treat partial results as delivery."""
    state = {'identity': identity, 'completed': {}, 'timings_s': {}}
    if checkpoint.exists():
        if not resume:
            raise ValueError('Checkpoint exists; use --resume or a new output directory')
        state = json.loads(checkpoint.read_text())
        if state.get('identity') != identity:
            raise ValueError('Checkpoint fingerprint mismatch (inputs/model/settings/software/source)')
        if set(state['completed']) - {q['question_id'] for q, _ in items}:
            raise ValueError('Checkpoint contains unexpected question IDs')
    for q, turns in items:
        qid = q['question_id']
        if qid in state['completed']:
            check_row(state['completed'][qid], q, turns, config)
            print(f'{qid}: resume skip', flush=True)
            continue
        try:
            row, elapsed = score_question(q, turns)
            check_row(row, q, turns, config)
            state['completed'][qid] = row
            state['timings_s'][qid] = elapsed
            baseline.write_jsonl_atomic(checkpoint, [state])
            print(f'{qid}: 100 candidates, {elapsed:.2f}s ({len(state["completed"])}/{len(items)})', flush=True)
        except Exception as exc:
            baseline.write_jsonl_atomic(checkpoint.with_suffix('.failure.json'), [{
                'question_id': qid, 'error_type': type(exc).__name__, 'error': str(exc),
                'completed_questions': len(state['completed'])}])
            raise
    return state


def export(state, manifest, output):
    completed = state['completed']
    if set(completed) != set(manifest['dev_ids']):
        raise ValueError('Refusing to export an incomplete development set')
    for name, ids in [('dev_all_K0.jsonl', manifest['dev_ids']),
                      ('dev_K0.jsonl', manifest['dev_answerable_ids']),
                      ('dev_abstention_K0.jsonl', manifest['dev_abstention_ids'])]:
        baseline.write_jsonl_atomic(output / 'candidates' / name, [completed[q] for q in ids])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-dir', type=Path)
    p.add_argument('--output-dir', type=Path)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--batch-size', type=int, default=64)
    p.add_argument('--validate-inputs', action='store_true')
    args = p.parse_args()
    manifest, items = load_inputs()
    print(f'Validated {len(items)} histories, {sum(len(t) for _, t in items)} turns', flush=True)
    if args.validate_inputs:
        return
    if args.model_dir is None or args.output_dir is None or args.batch_size < 1:
        p.error('--model-dir and --output-dir required, batch size must be positive')
    import torch
    import transformers
    import numpy
    import sklearn
    if not torch.cuda.is_available():
        raise RuntimeError('A Slurm CUDA allocation is required')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output_dir / 'checkpoint.json'
    with (args.output_dir / 'checkpoint.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        model_hashes = json.loads((B02 / 'model_sha256.json').read_text())
        for name, expected in model_hashes.items():
            if sha(args.model_dir / name) != expected:
                raise ValueError(f'Model hash mismatch: {name}')
        print('All 12 model file hashes verified', flush=True)
        config = settings(manifest, args.batch_size)
        source_hashes = {f: sha(Path(__file__).parent / f) for f in ('common.py', 'retrieve_dev.py')}
        source_hashes['B02/retrieve_k0.py'] = sha(B02 / 'retrieve_k0.py')
        software = {'torch': torch.__version__, 'transformers': transformers.__version__,
                    'numpy': numpy.__version__, 'sklearn': sklearn.__version__,
                    'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name()}
        inputs_hash = digest([{'question': q, 'turns': t} for q, t in items])
        provenance = {'config': config, 'software': software, 'model_sha256': model_hashes,
                      'public_inputs_sha256': inputs_hash, 'source_sha256': source_hashes,
                      'manifest_sha256': sha(A01 / 'dev_manifest.json')}
        identity = digest(provenance)
        # Fail before model loading when a requested resume does not match this run.
        if checkpoint.exists() and (not args.resume or json.loads(checkpoint.read_text()).get('identity') != identity):
            raise ValueError('Existing checkpoint requires --resume and identical run fingerprint')
        baseline.write_jsonl_atomic(args.output_dir / 'provenance.json', [dict(provenance, identity=identity)])
        model_parts = None

        def score_question(q, turns):
            nonlocal model_parts
            if model_parts is None:
                start = time.monotonic()
                model_parts = baseline.load_model(args.model_dir, torch.device('cuda:0'))
                print(f'Model loaded in {time.monotonic()-start:.2f}s', flush=True)
            tokenizer, model, linear = model_parts
            start = time.monotonic()
            qvec = baseline.embed([q['question']], tokenizer, model, linear, 1)
            dvec = baseline.embed([t['messages'][0]['content'] for t in turns], tokenizer, model, linear, args.batch_size)
            scores = torch.tensor((qvec @ dvec.T).squeeze(0))
            indices = scores.argsort(descending=True)[:100].tolist()
            candidates = [{'turn_id': turns[i]['turn_id'], 'rank': rank, 'score': float(scores[i])}
                          for rank, i in enumerate(indices, 1)]
            return public_row(q, candidates, config), time.monotonic() - start

        state = run_questions(items, config, identity, checkpoint, args.resume, score_question)
        export(state, manifest, args.output_dir)
        baseline.write_jsonl_atomic(args.output_dir / 'timings.json', [{
            'identity': identity, 'per_question_s': state['timings_s'],
            'total_question_s': sum(state['timings_s'].values()),
            'scope': 'query/history encoding, dot products, ranking and candidate assembly; excludes model loading, hash verification and official comparison'}])
        print('Exported all=40, main=34, abstention=6', flush=True)


if __name__ == '__main__':
    main()
