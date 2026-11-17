"""E03 batch reader: E02 prompt/model unchanged; incremental writes and strict resume."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import time

from batch import E02_PATH, load_inputs, reader, run_batch, sha


class GPUReader:
    def __init__(self, tokenizer, max_new_tokens, output):
        self.tokenizer, self.max_new_tokens, self.output = tokenizer, max_new_tokens, output
        self.model = None

    def load(self):
        import torch
        from transformers import AutoModelForCausalLM, GenerationConfig
        from batch import append
        if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
            raise RuntimeError('Requires CUDA GPU with BF16 support')
        torch.manual_seed(42)
        started = time.perf_counter()
        self.model = AutoModelForCausalLM.from_pretrained(
            reader.MODEL, revision=reader.REVISION, local_files_only=True,
            torch_dtype=torch.bfloat16, device_map={'': 0},
            attn_implementation='sdpa', use_safetensors=True).eval()
        torch.cuda.synchronize()
        load_seconds = time.perf_counter() - started
        self.eos = {self.tokenizer.eos_token_id}
        eot = self.tokenizer.convert_tokens_to_ids('<|eot_id|>')
        if eot is not None and eot != self.tokenizer.unk_token_id:
            self.eos.add(eot)
        self.generation = GenerationConfig(max_new_tokens=self.max_new_tokens,
            do_sample=False, num_beams=1, eos_token_id=sorted(self.eos),
            pad_token_id=self.tokenizer.eos_token_id, use_cache=True)
        warm = self.tokenizer('Warm up.', return_tensors='pt').to('cuda:0')
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            self.model.generate(**warm, max_new_tokens=8, do_sample=False,
                eos_token_id=sorted(self.eos), pad_token_id=self.tokenizer.eos_token_id)
        torch.cuda.synchronize()
        append(self.output / 'runtime.jsonl', {'slurm_job_id': os.environ.get('SLURM_JOB_ID'),
            'gpu': torch.cuda.get_device_name(0), 'host': platform.node(),
            'model_load_seconds': load_seconds, 'warmup_seconds': time.perf_counter()-started})

    def __call__(self, item):
        import torch
        if self.model is None:
            self.load()
        ids = torch.tensor([item['ids']], device='cuda:0')
        mask = torch.ones_like(ids)
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        with torch.inference_mode():
            output = self.model.generate(input_ids=ids, attention_mask=mask,
                                         generation_config=self.generation)
        torch.cuda.synchronize()
        seconds = time.perf_counter() - started
        tokens = output[0, ids.shape[1]:].tolist()
        text = self.tokenizer.decode(tokens, skip_special_tokens=True).strip()
        hit_limit = len(tokens) >= self.max_new_tokens and tokens[-1] not in self.eos
        return dict(reader.answer_fields(text, hit_limit),
                    output_tokens_including_stop=len(tokens), generation_seconds=seconds,
                    peak_allocated_gib=torch.cuda.max_memory_allocated() / 2**30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--schema-only', action='store_true')
    mode.add_argument('--check-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--stop-after', type=int, help='Planned checkpoint after N new records')
    parser.add_argument('--max-new-tokens', type=int, default=800)
    parser.add_argument('--stage', choices=['dev', 'formal'], default='dev')
    args = parser.parse_args()
    if args.max_new_tokens <= 0 or (args.stop_after is not None and args.stop_after <= 0):
        parser.error('Token limit and stop-after must be positive')
    rows = load_inputs(args.input)
    if any(r['stage'] != args.stage for r in rows):
        parser.error('Input stage differs from --stage; do not mix dev and formal')
    if args.schema_only:
        print(f'Schema/hash/duplicate checks passed: {len(rows)} records. No tokenizer or GPU check.')
        return
    from transformers import AutoConfig, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(reader.MODEL, revision=reader.REVISION, local_files_only=True)
    capacity = AutoConfig.from_pretrained(reader.MODEL, revision=reader.REVISION,
                                          local_files_only=True).max_position_embeddings
    prepared = [reader.prepare(row, tokenizer, capacity, args.max_new_tokens) for row in rows]
    for item in prepared:
        row = item['record']
        print(f"{row['question_id']} {row['index']}/{row['strategy']}: "
              f"context={item['context_tokens']} prompt={item['input_tokens']}", flush=True)
    if args.check_only:
        print('Token/fingerprint/budget/capacity checks passed; no GPU inference.')
        return
    if args.output is None or not os.environ.get('SLURM_JOB_ID'):
        parser.error('Generation requires --output and a Slurm GPU allocation')
    import torch
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError('Requires CUDA GPU with BF16 support')
    config = {
        'task': 'E03', 'batch_runner_version': 'e03-v1', 'reader_config_version': 'e02-v2',
        'model': reader.MODEL, 'revision': reader.REVISION, 'tokenizer_revision': reader.REVISION,
        'reader': 'con', 'backend': 'transformers', 'dtype': 'bfloat16', 'quantization': None,
        'attention': 'sdpa', 'batch_size': 1, 'do_sample': False, 'num_beams': 1,
        'seed': 42, 'max_new_tokens': args.max_new_tokens, 'stage': args.stage,
        'input_sha256': sha(args.input.read_bytes()), 'records': len(rows),
        'source_sha256': {p.parent.name + '/' + p.name: sha(p.read_bytes()) for p in
                          (Path(__file__), Path(__file__).with_name('batch.py'), E02_PATH)},
        'tokenizer_fingerprint': sha(tokenizer.backend_tokenizer.to_str().encode()),
        'prompt_sha256': sha(reader.PROMPT.encode()),
        'chat_template_sha256': sha(tokenizer.chat_template.encode()),
        'gpu': torch.cuda.get_device_name(0), 'python': platform.python_version(),
        'torch_cuda': torch.version.cuda,
        'packages': {p: importlib.metadata.version(p) for p in
                    ('torch', 'transformers', 'tokenizers', 'huggingface-hub', 'accelerate', 'safetensors')},
        'retry_policy': 'resume technical_failure/missing only; preserve truncated/empty for review',
    }
    report = run_batch(rows, prepared, args.output, config,
        GPUReader(tokenizer, args.max_new_tokens, args.output), args.resume, args.stop_after)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report['statuses']['truncated'] or report['statuses']['empty']:
        raise SystemExit('Generation recorded truncated/empty rows; inspect summary before handoff')


if __name__ == '__main__':
    main()
