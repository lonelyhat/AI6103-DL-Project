"""JSONL batch entry point. Inputs must already be anonymized by B/A01."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
if __package__:
    from .selection import Config, STRATEGIES, CharacterTokenizer, HFTokenizer, select
else:
    from selection import Config, STRATEGIES, CharacterTokenizer, HFTokenizer, select


def read_jsonl(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, help='B candidates JSONL; question may be joined via --questions')
    p.add_argument('--questions', help='A01 public/dev_questions.jsonl')
    p.add_argument('--turns-dir', required=True, help='A01 public/turns')
    p.add_argument('--output', required=True)
    p.add_argument('--strategy', choices=(*STRATEGIES, 'all'), default='all')
    p.add_argument('--tokenizer', required=True, help='HF model/local path, or demo:characters (test only)')
    p.add_argument('--allow-download', action='store_true', help='opt in to tokenizer download; default offline')
    p.add_argument('--budget', type=int, help='explicitly override all input budgets')
    p.add_argument('--redundancy-weight', type=float, default=0.5)
    p.add_argument('--coverage-weight', type=float, default=0.5)
    args = p.parse_args()
    config = Config(args.redundancy_weight, args.coverage_weight)
    tokenizer = CharacterTokenizer() if args.tokenizer == 'demo:characters' else HFTokenizer(args.tokenizer, args.allow_download)
    questions = {}
    if args.questions:
        for q in read_jsonl(args.questions):
            if set(q) - {'question_id', 'stage', 'question', 'question_date'} or q['question_id'] in questions:
                raise ValueError('questions must be unique A01 public rows')
            questions[q['question_id']] = q
    output = Path(args.output)
    protected = [Path(args.input)] + ([Path(args.questions)] if args.questions else [])
    turns_dir = Path(args.turns_dir)
    if output.resolve() in [x.resolve() for x in protected] or output.resolve().is_relative_to(turns_dir.resolve()):
        raise ValueError('output must not overwrite public inputs')
    results, seen = [], set()
    for row in read_jsonl(args.input):
        row = dict(row)
        qid = row['question_id']
        if not isinstance(qid, str) or not re.fullmatch('[a-z0-9_]+', qid):
            raise ValueError('invalid question_id')
        if qid in questions:
            for key, value in questions[qid].items():
                if key in row and row[key] != value:
                    raise ValueError(f'conflicting question metadata: {qid}/{key}')
                row[key] = value
        if args.budget is not None:
            row['budget_tokens'] = args.budget
        turns = read_jsonl(turns_dir / (qid + '.jsonl'))
        methods = STRATEGIES if args.strategy == 'all' else (args.strategy,)
        for method in methods:
            identity = (qid, row['stage'], row['index'], method, row['budget_tokens'])
            if identity in seen:
                raise ValueError(f'duplicate run: {identity}')
            seen.add(identity)
            results.append(select(row, turns, tokenizer, method, config))
    # Validate entire batch before replacing the target; failures leave old output intact.
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                         prefix=output.name+'.', suffix='.tmp', delete=False) as f:
            tmp = f.name
            for result in results:
                f.write(json.dumps(result, ensure_ascii=False, allow_nan=False)+'\n')
        os.replace(tmp, output)
    finally:
        if tmp and Path(tmp).exists(): Path(tmp).unlink()
    print(f'Wrote {len(results)} selections to {output}')


if __name__ == '__main__':
    main()
