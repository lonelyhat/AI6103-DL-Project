"""Prepare first-five D02 materials after B02 delivery. Does not call an LLM."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[2]
if __package__:
    from .materials import VERSION, select_ranked
    from ..D01.selection import HFTokenizer
else:
    sys.path.insert(0, str(REPO))
    from D.D02.materials import VERSION, select_ranked
    from D.D01.selection import HFTokenizer

HERE = Path(__file__).resolve().parent


def read_jsonl(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        return [json.loads(line) for line in f if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_batch(candidate_rows, questions, load_turns, counter, config):
    """Pure in-memory adapter, independently callable when B02 arrives."""
    expected = config['question_ids']
    if len(expected) != len(set(expected)):
        raise ValueError('duplicate requested question IDs')
    by_id = {}
    for q in questions:
        if not isinstance(q, dict) or set(q)-{'question_id','stage','question','question_date'}:
            raise ValueError('only A01 public question rows are permitted')
        if q['question_id'] in by_id:
            raise ValueError('duplicate public question')
        by_id[q['question_id']] = q
    inputs = {}
    for row in candidate_rows:
        if not isinstance(row, dict):
            raise ValueError('B02 candidate rows must be JSON objects')
        qid = row.get('question_id')
        if not isinstance(qid, str) or qid not in expected or qid in inputs:
            raise ValueError('unexpected or duplicate B02 question_id')
        inputs[qid] = row
    if set(inputs) != set(expected):
        raise ValueError(f'B02 must provide all requested questions; missing={sorted(set(expected)-set(inputs))}')
    results = []
    for qid in expected:
        if qid not in by_id:
            raise ValueError(f'missing A01 public question: {qid}')
        request = dict(inputs[qid])
        if request.get('config_version') != config['input_config_version']:
            raise ValueError(f'{qid}: require {config["input_config_version"]} candidate metadata')
        for key, value in by_id[qid].items():
            if key in request and request[key] != value:
                raise ValueError(f'{qid}: conflicting public question field {key}')
            request[key] = value
        if request.get('index') != config['index'] or request.get('stage') != config['stage']:
            raise ValueError(f'{qid}: unexpected stage/index')
        if request.get('strategy') not in (None,'R'):
            raise ValueError('D02 accepts unselected candidates or R only')
        declared_budget = request.get('budget_tokens')
        if declared_budget not in (None, config['budget_tokens']):
            raise ValueError('candidate metadata declares another budget; reconcile before running')
        request['budget_tokens'] = config['budget_tokens']
        # score/unknown-field/identity checks stay strict in shared A01 validator.
        started = time.perf_counter()
        result = select_ranked(request, load_turns(qid), counter)
        result['selection_elapsed_s'] = time.perf_counter()-started
        result['history_file'] = f'materials/{qid}.txt'
        results.append(result)
    return results


def write_bundle(output, results, manifest):
    """Write a new batch directory as one bundle; existing batches are immutable."""
    output = Path(output)
    if output.exists():
        raise FileExistsError('output directory already exists; choose a new batch directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve()
    temporary = Path(tempfile.mkdtemp(prefix='.d02-partial-', dir=parent))
    try:
        (temporary/'materials').mkdir()
        with (temporary/'selections.jsonl').open('w', encoding='utf-8', newline='\n') as f:
            for result in results:
                f.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
                # newline='' avoids platform newline conversion of hashed history text.
                with (temporary/result['history_file']).open('w',encoding='utf-8',newline='') as history:
                    history.write(result['history_text'])
        (temporary/'batch_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        if output.exists():
            raise FileExistsError('output appeared during preparation')
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            # Resolve/check the exact recursive-cleanup target within this batch parent.
            if temporary.resolve().parent != parent or not temporary.name.startswith('.d02-partial-'):
                raise RuntimeError('refuse cleanup outside batch parent')
            shutil.rmtree(temporary)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidates', type=Path, required=True, help='B02 anonymized K0 candidate JSONL')
    p.add_argument('--public-root', type=Path, default=REPO/'A-数据线/A01/output/public')
    p.add_argument('--tokenizer', required=True, help='actual reader tokenizer model ID or local directory')
    p.add_argument('--tokenizer-label', help='explicit canonical reader model ID if --tokenizer is a local path')
    p.add_argument('--allow-download', action='store_true')
    p.add_argument('--output-dir', type=Path, required=True, help='new output directory; never overwrites a batch')
    args = p.parse_args()
    if args.tokenizer.startswith('demo:'):
        raise ValueError('D02 B02 acceptance requires the actual reader tokenizer')
    config = json.loads((HERE/'config.json').read_text(encoding='utf-8-sig'))
    if args.output_dir.resolve().is_relative_to(args.public_root.resolve()):
        raise ValueError('output directory must not be inside A01 public inputs')
    if args.output_dir.exists():
        raise FileExistsError('choose a new output directory')
    counter = HFTokenizer(args.tokenizer, allow_download=args.allow_download)
    if args.tokenizer_label:
        counter.name = args.tokenizer_label
    files = [args.candidates, args.public_root/'dev_questions.jsonl']
    files.extend(args.public_root/'turns'/(qid+'.jsonl') for qid in config['question_ids'])
    initial_hashes = {str(path):sha(path) for path in files}
    results = prepare_batch(read_jsonl(args.candidates), read_jsonl(files[1]),
                            lambda qid:read_jsonl(args.public_root/'turns'/(qid+'.jsonl')), counter, config)
    if any(sha(path) != initial_hashes[str(path)] for path in files):
        raise RuntimeError('input files changed during preparation; retry against fixed B02 inputs')
    ready = all(r['status']=='ready_for_reader' for r in results)
    manifest = {'config_version':VERSION, 'input_config_version':'a01-v2',
                'status':'materials_generated_pending_acceptance' if ready else 'needs_attention_empty_material',
                'config':config, 'question_ids':config['question_ids'], 'n_questions':len(results),
                'tokenizer_source':args.tokenizer, 'tokenizer_label':counter.name,
                'tokenizer_fingerprint':counter.fingerprint, 'input_sha256':initial_hashes,
                'source_sha256':{str(path.relative_to(REPO)):sha(path) for path in
                    [HERE/'materials.py',HERE/'prepare_materials.py',REPO/'D/D01/selection.py']},
                'runtime_budget_checks_passed':all(r['budget_check']['passed'] for r in results),
                'acceptance_status':'pending_independent_verification',
                'records':[{'question_id':r['question_id'],'n_candidates':r['n_candidates'],
                    'n_selected_turns':r['n_selected_turns'],'context_tokens':r['context_tokens'],
                    'history_file':r['history_file'],'history_sha256':r['history_sha256'],
                    'status':r['status']} for r in results]}
    write_bundle(args.output_dir, results, manifest)
    print(f'Wrote {len(results)} D02 material records to {args.output_dir}; independent acceptance pending')


if __name__ == '__main__':
    main()
