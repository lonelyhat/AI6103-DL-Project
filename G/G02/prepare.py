"""Build and verify a formal D-to-E material batch from the local G02 plan."""
import argparse
import hashlib
import json
from itertools import product
from pathlib import Path
import re
from time import perf_counter

from D.D01.selection import HFTokenizer
from D.D02.materials import select_ranked
from D.D06.prepare import e_module
from D.D07.run import CachedCounter, replay
from D.selection_batch import prepare_results

ROOT = Path(__file__).resolve().parents[2]
PLAN = Path(__file__).with_name('plan.json')
METHODS = ('R', 'MMR', 'C', 'Q', 'FL')
INDICES = ('K0', 'K1')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def read_rows(path):
    with path.open(encoding='utf-8-sig') as source:
        return [json.loads(line) for line in source if line.strip()]


def source_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def table(rows, expected_ids, name):
    ids = [row['question_id'] for row in rows]
    if ids != expected_ids or len(set(ids)) != len(ids):
        raise ValueError(f'{name}: IDs or order differ from the formal manifest')
    return dict(zip(ids, rows))


def require_matrix(rows, qids, version, budget, indices=INDICES):
    keys = [(r['question_id'], r['index'], r['strategy']) for r in rows]
    if len(keys) != len(set(keys)) or set(keys) != set(product(qids, indices, METHODS)):
        raise ValueError(f'Batch requires exactly {len(indices)*len(METHODS)} distinct settings per question')
    if any((r['stage'], r['input_config_version'], r['budget_tokens']) != ('formal', version, budget) for r in rows):
        raise ValueError('Reader input stage/version/budget differs from G02 plan')


def prepare_rows(config, qids, counter, budget, indices=INDICES):
    for path, expected in config['source_sha256'].items():
        if source_hash(ROOT / path) != expected:
            raise ValueError(f'Pinned input or runner changed: {path}')
    formal = config['formal']
    version = formal['config_version']
    public_root = ROOT / formal['public_root']
    manifest = read_json(ROOT / formal['manifest'])
    ids = manifest['formal_ids']
    if (len(ids) != formal['questions'] or manifest['config_version'] != version
            or not qids or len(qids) != len(set(qids)) or not set(qids) <= set(ids)):
        raise ValueError('Unknown/duplicate questions or unexpected formal manifest')
    questions = table(read_rows(public_root / 'formal_questions.jsonl'), ids, 'A03 public questions')
    candidates = {i: table(read_rows(ROOT / formal['candidates'][i]), ids, f'{i} candidates') for i in indices}
    weights = config['methods']
    if set(weights) != set(METHODS):
        raise ValueError('G02 plan must specify all five methods')

    for qid in qids:
        if not re.fullmatch(r'[A-Za-z0-9_]+', qid):
            raise ValueError(f'Invalid question ID: {qid!r}')
        turns_path = public_root / 'turns' / f'{qid}.jsonl'
        if source_hash(turns_path) != formal['turn_sha256'][qid]:
            raise ValueError(f'{qid}: formal history changed')
        turns = read_rows(turns_path)
        exact_counter = CachedCounter(counter)
        question = questions[qid]
        if set(question) != {'question_id', 'stage', 'question', 'question_date'}:
            raise ValueError('Only A03 public question fields may reach the selector')
        for index in indices:
            candidate = candidates[index][qid]
            if (candidate['stage'], candidate['index'], candidate['config_version'], candidate.get('strategy')) != (
                    'formal', index, version, None):
                raise ValueError(f'{qid}/{index}: invalid candidate provenance')
            if candidate['budget_tokens'] != config['history_budget_tokens'] or question['stage'] != 'formal':
                raise ValueError('Unexpected source budget/stage')
            if any(key in candidate and candidate[key] != value for key, value in question.items()):
                raise ValueError(f'{qid}/{index}: candidate and public question disagree')
            adapted = {**candidate, 'budget_tokens': budget}
            request = {**adapted, **question}
            for strategy in METHODS:
                case = {'strategy': strategy, **weights[strategy]}
                if strategy == 'R':
                    started = perf_counter()
                    row = select_ranked(request, turns, exact_counter)
                    row['selection_elapsed_s'] = perf_counter() - started
                else:
                    settings = dict(case, stage='formal', index=index, budget_tokens=budget,
                                    question_ids=[qid], strategies=[strategy])
                    row = prepare_results([adapted], [question], lambda _: turns, exact_counter, settings)[0]
                replay(row, request, turns, exact_counter, case)
                if not row['selected_turn_ids']:
                    raise ValueError(f'{qid}/{index}/{strategy}: empty material requires review')
                yield row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer', required=True, help='Local reader snapshot or matching tokenizer directory')
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--question-ids', nargs='+')
    scope.add_argument('--batch-id', help='Batch ID from the frozen D08 schedule')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--preview-budget', type=int, help='Explicit budget override for local diagnostics')
    parser.add_argument('--preview-index', choices=INDICES, help='Check one index for handoff diagnosis only')
    parser.add_argument('--config', type=Path, default=PLAN)
    args = parser.parse_args()
    plan_hash = source_hash(args.config)
    config = read_json(args.config)
    approvals = config['approvals']
    frozen = config['status'] == 'frozen' and all(approvals[key] for key in ('a03_final', 'g01_acceptance'))
    indices = (args.preview_index,) if args.preview_index else INDICES
    unavailable = [i for i in indices if not config['formal']['candidates'].get(i)]
    if unavailable:
        parser.error(f"Awaiting {'/'.join(unavailable)} candidates for {config['formal']['config_version']}")
    if args.batch_id:
        batch_plan = config.get('formal', {}).get('batches', {}).get(args.batch_id)
        if not frozen or not batch_plan:
            parser.error('A known batch ID and frozen plan are required for D08')
        if args.preview_index is not None or args.preview_budget is not None:
            parser.error('A D08 batch must use both indices and the frozen budget')
        qids = batch_plan['question_ids']
        if batch_plan['expected_records'] != len(qids) * len(INDICES) * len(METHODS):
            parser.error('D08 batch size differs from the frozen schedule')
    else:
        qids = args.question_ids
    if not frozen and len(qids) > 2:
        parser.error('Pending freeze permits only a one- or two-question interface check')
    if args.preview_budget is not None and not 0 < args.preview_budget:
        parser.error('Preview budget must be positive')
    budget = config['history_budget_tokens'] if args.preview_budget is None else args.preview_budget
    candidate_only = not frozen or args.preview_budget is not None or args.preview_index is not None
    out = args.output_dir.resolve()
    if out.exists():
        parser.error('Choose a new output directory')

    from transformers import AutoConfig
    counter = HFTokenizer(args.tokenizer)
    reader = config['reader']
    counter.name = reader['model']
    template_hash = hashlib.sha256(counter.tokenizer.chat_template.encode()).hexdigest()
    if (counter.fingerprint, template_hash) != (reader['tokenizer_fingerprint'], reader['chat_template_sha256']):
        raise ValueError('Tokenizer or chat template differs from the E03 archived fingerprint')
    capacity = AutoConfig.from_pretrained(args.tokenizer, local_files_only=True).max_position_embeddings
    batch = e_module('batch')
    if (batch.reader.MODEL, batch.reader.REVISION, hashlib.sha256(batch.reader.PROMPT.encode()).hexdigest()) != (
            reader['model'], reader['revision'], reader['prompt_sha256']):
        raise ValueError('E02 model revision or CoN prompt differs from the G02 plan')
    rows = list(prepare_rows(config, qids, counter, budget, indices))
    out.mkdir(parents=True)
    selection_file = out / 'selections.jsonl'
    with selection_file.open('x', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
    input_file = out / 'reader_inputs.jsonl'
    public_root = ROOT / config['formal']['public_root']
    receipt = e_module('prepare_inputs').build([selection_file], public_root / 'turns', input_file)
    reader_inputs = batch.load_inputs(input_file)
    require_matrix(reader_inputs, qids, config['formal']['config_version'], budget, indices)
    prepared = [batch.reader.prepare(row, counter.tokenizer, capacity, reader['max_new_tokens'])
                for row in reader_inputs]
    if source_hash(args.config) != plan_hash:
        raise ValueError('G02 plan changed during material preparation')
    receipt.update(status='cpu_reader_preflight_passed', batch_id=args.batch_id,
                   intended_use='interface_check_only' if candidate_only else 'formal_generation',
                   plan_sha256=plan_hash, question_ids=qids, indices=list(indices),
                   budget_tokens=budget, tokenizer_check='passed', tokenizer_fingerprint=counter.fingerprint,
                   chat_template_sha256=template_hash, selections_sha256=source_hash(selection_file),
                   max_context_tokens=max(r['context_tokens'] for r in prepared),
                   max_prompt_tokens=max(r['input_tokens'] for r in prepared),
                   max_new_tokens=reader['max_new_tokens'], generation_performed=False)
    (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{receipt['status']}: {len(prepared)} records at {budget} tokens; {receipt['intended_use']}")


if __name__ == '__main__':
    main()
