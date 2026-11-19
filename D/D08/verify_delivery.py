"""Check all eight D08 archives against the frozen G02 plan, without a GPU."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from D.D01.selection import HFTokenizer, render_context
from D.D06.prepare import e_module
from G.G02.prepare import INDICES, PLAN, ROOT, read_json, read_rows, require_matrix, source_hash

DELIVERY = Path(__file__).with_name('delivery')
MEMBERS = {'selections.jsonl', 'reader_inputs.jsonl', 'receipt.json'}


def check(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def check_delivery(delivery=DELIVERY, tokenizer_path=None):
    plan = read_json(PLAN)
    plan_sha = source_hash(PLAN)
    check(plan['status'] == 'frozen', 'D08 requires the frozen G02 plan')
    for relative, expected in plan['source_sha256'].items():
        check(source_hash(ROOT / relative) == expected, f'Pinned input or runner changed: {relative}')
    formal = plan['formal']
    budget = plan['history_budget_tokens']
    question_ids = read_json(ROOT / formal['manifest'])['formal_ids']
    check([qid for b in formal['batches'].values() for qid in b['question_ids']] == question_ids
          and len(set(question_ids)) == len(question_ids) == formal['questions'],
          'Batch schedule differs from the formal question list')
    candidates = {
        index: {r['question_id']: {c['turn_id'] for c in r['candidates']}
                for r in read_rows(ROOT / formal['candidates'][index])}
        for index in INDICES
    }
    questions = {r['question_id']: r for r in
                 read_rows(ROOT / formal['public_root'] / 'formal_questions.jsonl')}
    batch_module = e_module('batch')
    normalize = batch_module.normalize
    tokenizer = capacity = None
    if tokenizer_path is not None:
        from transformers import AutoConfig

        counter = HFTokenizer(str(tokenizer_path))
        tokenizer = counter.tokenizer
        reader = plan['reader']
        check(counter.fingerprint == reader['tokenizer_fingerprint']
              and sha(tokenizer.chat_template.encode()) == reader['chat_template_sha256']
              and sha(batch_module.reader.PROMPT.encode()) == reader['prompt_sha256'],
              'Tokenizer, chat template or CoN prompt differs from G02')
        capacity = AutoConfig.from_pretrained(str(tokenizer_path), local_files_only=True).max_position_embeddings
    found_ids = set()
    receipts = {}
    for batch_id, batch in formal['batches'].items():
        archive = delivery / f"D08_{plan['config_version']}_{batch_id}.zip"
        with zipfile.ZipFile(archive) as zipped:
            check(len(zipped.namelist()) == len(MEMBERS) and set(zipped.namelist()) == MEMBERS
                  and zipped.testzip() is None, f'{batch_id}: wrong archive members or CRC failure')
            input_bytes = zipped.read('reader_inputs.jsonl')
            selection_bytes = zipped.read('selections.jsonl')
            receipt = json.loads(zipped.read('receipt.json'))
        rows = [json.loads(line) for line in input_bytes.splitlines() if line.strip()]
        selections = [json.loads(line) for line in selection_bytes.splitlines() if line.strip()]
        check(receipt['batch_id'] == batch_id and receipt['plan_sha256'] == plan_sha
              and receipt['question_ids'] == batch['question_ids']
              and receipt['status'] == 'cpu_reader_preflight_passed'
              and receipt['intended_use'] == 'formal_generation'
              and receipt['tokenizer_fingerprint'] == plan['reader']['tokenizer_fingerprint']
              and receipt['input_sha256'] == sha(input_bytes)
              and receipt['selections_sha256'] == sha(selection_bytes)
              and len(rows) == len(selections) == receipt['records'] == batch['expected_records'],
              f'{batch_id}: receipt, schedule or checksums disagree')
        require_matrix(rows, batch['question_ids'], formal['config_version'], budget)
        history = {
            qid: {turn['turn_id']: turn for turn in
                  read_rows(ROOT / formal['public_root'] / 'turns' / f'{qid}.jsonl')}
            for qid in batch['question_ids']
        }
        for selected, row in zip(selections, rows):
            qid, index, strategy = (row[k] for k in ('question_id', 'index', 'strategy'))
            label = f'{batch_id}/{qid}/{index}/{strategy}'
            check(all(row[k] == questions[qid][k] for k in ('question', 'question_date', 'stage')),
                  f'{label}: reader question differs from A03')
            check(all(row[k] == selected[k] for k in ('question_id', 'index', 'strategy', 'context_tokens',
                                                      'history_sha256', 'selected_turn_ids'))
                  and row['selection_config_id'] == selected['config_id'],
                  f'{label}: selected material and reader input differ')
            tids = row['selected_turn_ids']
            text = render_context([history[qid][tid] for tid in tids])
            check(len(set(tids)) == len(tids) and set(tids) <= candidates[index][qid]
                  and 0 < row['context_tokens'] <= budget
                  and text == row['context'] == selected['history_text'],
                  f'{label}: chosen turns, budget or original history mismatch')
            conf = row['selection_config']
            weights = plan['methods'][strategy]
            check(conf['strategy'] == strategy and conf['budget_tokens'] == budget
                  and conf['tokenizer_fingerprint'] == plan['reader']['tokenizer_fingerprint']
                  and all(conf.get(k, 0 if strategy == 'R' else None) == value for k, value in weights.items()),
                  f'{label}: per-method settings differ from G02')
            check(normalize(row) == row and row['record_id'] not in found_ids,
                  f'{label}: duplicate record or invalid reader identity/fields')
            found_ids.add(row['record_id'])
        check(receipt['max_context_tokens'] == max(r['context_tokens'] for r in rows),
              f'{batch_id}: maximum history length differs')
        if tokenizer is not None:
            prompts = [tokenizer.apply_chat_template([{'role': 'user', 'content': batch_module.reader.PROMPT.format(
                r['context'], r['question_date'], r['question'])}], tokenize=False, add_generation_prompt=True)
                for r in rows]
            counts = tokenizer([r['context'] for r in rows] + prompts,
                               add_special_tokens=False, return_attention_mask=False)['input_ids']
            history_counts, prompt_counts = counts[:len(rows)], counts[len(rows):]
            check(all(len(tokens) == r['context_tokens'] for tokens, r in zip(history_counts, rows, strict=True))
                  and max(map(len, prompt_counts)) == receipt['max_prompt_tokens']
                  and max(map(len, prompt_counts)) + plan['reader']['max_new_tokens'] <= capacity,
                  f'{batch_id}: independently recounted history/prompt differs or exceeds capacity')
        receipts[batch_id] = {
            'archive': archive.name, 'archive_sha256': sha(archive.read_bytes()),
            'question_ids': batch['question_ids'], 'records': len(rows),
            'max_context_tokens': receipt['max_context_tokens'],
            'max_prompt_tokens': receipt['max_prompt_tokens'],
            'input_sha256': receipt['input_sha256'], 'selections_sha256': receipt['selections_sha256'],
        }
    check(len(found_ids) == sum(b['expected_records'] for b in formal['batches'].values()),
          'Combined D08 record count differs from the frozen schedule')
    return {
        'status': 'd08_materials_complete', 'config_version': plan['config_version'],
        'a03_config_version': formal['config_version'], 'plan_sha256': plan_sha,
        'questions': len(question_ids), 'records': len(found_ids), 'history_budget_tokens': budget,
        'max_context_tokens': max(r['max_context_tokens'] for r in receipts.values()),
        'batches': receipts,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer', type=Path, help='Also recount all history tokens and full CoN prompts')
    args = parser.parse_args()
    report = check_delivery(tokenizer_path=args.tokenizer)
    check(report == read_json(DELIVERY / 'manifest.json'), 'Delivered archives differ from the manifest')
    print(f"D08 PASS: {report['questions']} questions, {report['records']} records, "
          f"maximum history {report['max_context_tokens']} tokens.")
    if args.tokenizer is not None:
        print('Independent tokenizer check passed for every history and full CoN prompt.')
