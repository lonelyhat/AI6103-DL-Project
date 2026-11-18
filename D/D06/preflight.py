"""CPU-only E reader prompt/token checks using the local cached tokenizer."""
import argparse
import json
from pathlib import Path

from D.D01.selection import HFTokenizer
from D.D06.prepare import e_module


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--tokenizer', type=Path, required=True)
    args = p.parse_args()
    batch = e_module('batch')
    counter = HFTokenizer(str(args.tokenizer))
    capacity = json.loads((args.tokenizer / 'config.json').read_text())['max_position_embeddings']
    rows = batch.load_inputs(args.input)
    prepared = [batch.reader.prepare(r, counter.tokenizer, capacity, 800) for r in rows]
    print(json.dumps(dict(records=len(rows), status='E_token_prompt_capacity_checks_passed',
                         tokenizer_fingerprint=counter.fingerprint,
                         max_prompt_tokens=max(r['input_tokens'] for r in prepared),
                         max_new_tokens=800, model_inference=False), indent=2))


if __name__ == '__main__':
    main()
