"""E02: validate prepared DEV contexts, then run the official single-call con prompt.

Prompt source: LongMemEval, commit 9e0b455f4ef0e2ab8f2e582289761153549043fc,
src/generation/run_generation.py. Backend adapted to local Transformers.
This runner does not retrieve, select, reorder, or truncate history.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time


MODEL = 'meta-llama/Llama-3.1-8B-Instruct'
REVISION = '0e9e39f249a16976918f6564b8830bc894c89659'
PROMPT = ('I will give you several history chats between you and a user. '
          'Please answer the question based on the relevant chat history. '
          'Answer the question step by step: first extract all the relevant information, '
          'and then reason over the information to get the answer.\n\n\n'
          'History Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer (step by step):')


def load_inputs(path):
    """Small internal interface; adapt the team's actual D02 format at handoff."""
    rows = []
    seen = set()
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():
            continue
        source = json.loads(line)
        row = {}
        for key in ('question_id', 'question', 'question_date', 'context', 'variant'):
            value = source.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'Line {len(rows) + 1}: missing/non-string {key}')
            row[key] = value
        if source.get('stage') != 'dev':
            raise ValueError('E02 expects stage=dev')
        if row['variant'] not in ('budget', 'original_topk'):
            raise ValueError('variant must be budget or original_topk')
        row['stage'] = 'dev'
        for key in ('index', 'strategy', 'tokenizer', 'config_version', 'history_sha256'):
            if not isinstance(source.get(key), str) or not source[key]:
                raise ValueError(f'{row["question_id"]}: missing {key}')
        for key in ('index', 'strategy', 'source', 'context_tokens', 'tokenizer',
                    'config_version', 'history_sha256', 'tokenizer_fingerprint',
                    'selected_turn_ids', 'input_config_version', 'serialization'):
            if key in source:
                row[key] = source[key]
        if row['tokenizer'] != MODEL:
            raise ValueError('E02 requires the E01 Llama tokenizer')
        if hashlib.sha256(row['context'].encode('utf-8')).hexdigest() != row['history_sha256']:
            raise ValueError(f'{row["question_id"]}: context hash mismatch')
        setting = 'budget_tokens' if row['variant'] == 'budget' else 'topk'
        value = source.get(setting)
        if type(value) is not int or value <= 0:
            raise ValueError(f'{row["question_id"]}: requires positive integer {setting}')
        row[setting] = value
        if row['variant'] == 'original_topk':
            row['budget_tokens'] = None  # No fixed-token budget for this reference.
        identity = (row['question_id'], row['variant'])
        if identity in seen:
            raise ValueError(f'Duplicate question/variant: {identity}')
        seen.add(identity)
        rows.append(row)
    if not rows:
        raise ValueError('Input has no records')
    return rows


def prepare(row, tokenizer, capacity, max_new_tokens):
    expected = row.get('tokenizer_fingerprint')
    if expected:
        actual = hashlib.sha256(tokenizer.backend_tokenizer.to_str().encode()).hexdigest()
        if actual != expected:
            raise ValueError('Tokenizer fingerprint differs from D02; resolve before generation')
    context_tokens = len(tokenizer.encode(row['context'], add_special_tokens=False))
    if row['variant'] == 'budget' and context_tokens > row['budget_tokens']:
        raise ValueError(f'{row["question_id"]}: context {context_tokens} exceeds budget')
    if 'context_tokens' in row and row['context_tokens'] != context_tokens:
        raise ValueError(f'{row["question_id"]}: D02 token count differs from actual context')
    messages = [{'role': 'user', 'content': PROMPT.format(
        row['context'], row['question_date'], row['question'])}]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    ids = tokenizer.encode(prompt, add_special_tokens=False)
    if len(ids) + max_new_tokens > capacity:
        raise ValueError(f'{row["question_id"]}: input + output exceeds model capacity')
    return {'record': row, 'prompt': prompt, 'context_tokens': context_tokens,
            'input_tokens': len(ids), 'ids': ids}


def extract_answer(text):
    """Only extract an explicit final-answer marker; never guess the last sentence."""
    normalized = text.replace('**', '')
    matches = list(re.finditer(r'^[ \t]*(?:Final answer|最终答案)[ \t]*[:：]',
                               normalized, flags=re.MULTILINE | re.IGNORECASE))
    if len(matches) == 1:
        answer = normalized[matches[0].end():].strip()
        if answer:
            return answer, 'explicit_marker'
    return None, 'needs_review'


def answer_fields(text, hit_limit):
    answer, parse_status = extract_answer(text)
    if hit_limit or not text:
        answer, parse_status = None, 'needs_review'
    return dict(raw_output=text, hypothesis=answer or '', extracted_answer=answer,
                parse_status=parse_status, hit_output_limit=hit_limit,
                status='truncated' if hit_limit else ('generated' if text else 'empty'),
                reader_config_version='e02-v2')


def git_value(*args):
    result = subprocess.run(['git', *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def save_config(path, config):
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-only', action='store_true', help='CPU tokenizer check; no model load')
    parser.add_argument('--schema-only', action='store_true', help='Validate fields/hashes without model dependencies')
    parser.add_argument('--max-new-tokens', type=int, default=800)
    args = parser.parse_args()
    if args.max_new_tokens < 1:
        parser.error('--max-new-tokens must be positive')
    if not (args.check_only or args.schema_only) and (args.output is None or not os.environ.get('SLURM_JOB_ID')):
        parser.error('Generation needs --output and a Slurm GPU allocation')

    rows = load_inputs(args.input)
    if args.schema_only:
        print(f'Schema and context hashes passed: {len(rows)} records. No tokenizer/GPU check.')
        return
    # Import after input validation; --help and interface checks need only Python.
    from transformers import AutoConfig, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
    capacity = AutoConfig.from_pretrained(
        MODEL, revision=REVISION, local_files_only=True).max_position_embeddings
    prepared = [prepare(row, tokenizer, capacity, args.max_new_tokens) for row in rows]
    variants = sorted({r['variant'] for r in rows})
    for variant in variants:
        count = sum(r['variant'] == variant for r in rows)
        print(f'{variant}: {count} questions (E02 delivery expects 5 per version)', flush=True)
    for item in prepared:
        print(f'{item["record"]["question_id"]} {item["record"]["variant"]}: '
              f'context={item["context_tokens"]}, prompt={item["input_tokens"]}', flush=True)
    if args.check_only:
        print('Input/token checks passed; no GPU inference performed.')
        return

    import torch
    from transformers import AutoModelForCausalLM, GenerationConfig
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError('This E02 configuration requires a CUDA GPU with BF16 support')
    args.output.mkdir(parents=True, exist_ok=False)
    torch.manual_seed(42)
    config = {
        'task': 'E02', 'model': MODEL, 'revision': REVISION, 'tokenizer_revision': REVISION,
        'reader': 'con', 'backend': 'transformers', 'dtype': 'bfloat16', 'quantization': None,
        'attention': 'sdpa', 'batch_size': 1, 'do_sample': False, 'num_beams': 1,
        'seed': 42, 'max_new_tokens': args.max_new_tokens,
        'input_file': str(args.input), 'records': len(rows), 'variants': variants,
        'input_sha256': hashlib.sha256(args.input.read_bytes()).hexdigest(),
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'tokenizer_fingerprint': hashlib.sha256(tokenizer.backend_tokenizer.to_str().encode()).hexdigest(),
        'reader_config_version': 'e02-v2',
        'git_commit': git_value('rev-parse', 'HEAD'), 'git_status': git_value('status', '--short'),
        'python': platform.python_version(), 'gpu': torch.cuda.get_device_name(0),
        'hostname': platform.node(), 'torch_cuda': torch.version.cuda,
        'packages': {p: importlib.metadata.version(p) for p in
                     ('torch', 'transformers', 'huggingface-hub', 'accelerate', 'safetensors')},
        'slurm_job_id': os.environ['SLURM_JOB_ID'],
        'answer_extraction': 'explicit final-answer marker only; otherwise needs_review',
    }
    save_config(args.output / 'config.json', config)
    torch.cuda.synchronize()
    tick = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, revision=REVISION, local_files_only=True, torch_dtype=torch.bfloat16,
        device_map={'': 0}, attn_implementation='sdpa', use_safetensors=True).eval()
    torch.cuda.synchronize()
    config['model_load_seconds'] = time.perf_counter() - tick
    eos = {tokenizer.eos_token_id}
    eot = tokenizer.convert_tokens_to_ids('<|eot_id|>')
    if eot is not None and eot != tokenizer.unk_token_id:
        eos.add(eot)
    generation = GenerationConfig(max_new_tokens=args.max_new_tokens, do_sample=False,
                                  num_beams=1, eos_token_id=sorted(eos),
                                  pad_token_id=tokenizer.eos_token_id, use_cache=True)
    warm = tokenizer('Warm up.', return_tensors='pt').to('cuda:0')
    torch.cuda.synchronize()
    tick = time.perf_counter()
    with torch.inference_mode():
        model.generate(**warm, max_new_tokens=8, do_sample=False,
                       eos_token_id=sorted(eos), pad_token_id=tokenizer.eos_token_id)
    torch.cuda.synchronize()
    config['warmup_seconds'] = time.perf_counter() - tick
    del warm
    save_config(args.output / 'config.json', config)

    with (args.output / 'results.jsonl').open('w', encoding='utf-8') as handle:
        for item in prepared:
            record = dict(item['record'])
            record.update(prompt=item['prompt'], context_tokens=item['context_tokens'],
                          input_tokens=item['input_tokens'])
            try:
                ids = torch.tensor([item['ids']], device='cuda:0')
                mask = torch.ones_like(ids)
                torch.cuda.synchronize()
                torch.cuda.reset_peak_memory_stats()
                tick = time.perf_counter()
                with torch.inference_mode():
                    output = model.generate(input_ids=ids, attention_mask=mask,
                                            generation_config=generation)
                torch.cuda.synchronize()
                seconds = time.perf_counter() - tick
                tokens = output[0, ids.shape[1]:].tolist()
                text = tokenizer.decode(tokens, skip_special_tokens=True).strip()
                hit_limit = len(tokens) >= args.max_new_tokens and tokens[-1] not in eos
                record.update(answer_fields(text, hit_limit))
                record.update(
                    output_tokens_including_stop=len(tokens), generation_seconds=seconds,
                    peak_allocated_gib=torch.cuda.max_memory_allocated() / 2**30)
                del ids, mask, output
            except Exception as error:
                record.update(raw_output='', hypothesis='', extracted_answer=None,
                              parse_status='needs_review', reader_config_version='e02-v2',
                              status='technical_failure', error=str(error))
                handle.write(json.dumps(record, ensure_ascii=False) + '\n')
                handle.flush()
                raise  # Preserve completed rows; recovery belongs to E03.
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            handle.flush()
            print(f'{record["question_id"]} {record["variant"]}: {record["status"]}, '
                  f'{record["generation_seconds"]:.3f}s', flush=True)
    print(f'Saved {len(prepared)} results to {args.output}; correctness has not been scored.')


if __name__ == '__main__':
    main()
