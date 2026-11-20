"""Export one already-used DEV input; never copy gold answers or old outputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile


def prepare(archive, question_id=None):
    with Path(archive).open('rb') as stream:
        archive_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    with ZipFile(archive) as bundle:
        split = json.loads(bundle.read('results/split.json'))
        question_id = question_id or next(q for q in split['dev_ids'] if not q.endswith('_abs'))
        if question_id not in split['dev_ids']:
            raise ValueError('E01 accepts archived DEV IDs only')
        reader_name = f'results/reader/{question_id}_2048_relevance.json'
        selection_name = f'results/selection/{question_id}_2048_relevance_0.json'
        reader = json.loads(bundle.read(reader_name))['value']
        selection = json.loads(bundle.read(selection_name))['value']
        if reader['stage'] != 'dev' or selection['question_id'] != question_id:
            raise ValueError('DEV identity mismatch')
        # Recover only question/date from the archived Qwen prompt. Rebuild the
        # new prompt with the Llama tokenizer; do not pass Qwen special tokens.
        match = re.search(r'\nQuestion date: ([^\n]+)\nQuestion: (.*?)<\|im_end\|>',
                          reader['prompt'], re.DOTALL)
        if not match:
            raise ValueError('Unsupported historical prompt format')
        # Whitelist public fields; ignore archived metrics, labels and hypotheses.
        units = [{key: unit[key] for key in ('id', 'order', 'timestamp')}
                 | {'messages': [{'role': msg['role'], 'content': msg['content']}
                                 for msg in unit['messages']]}
                 for unit in selection['units']]
        return {
            'stage': 'dev', 'question_id': question_id,
            'question_date': match[1], 'question': match[2],
            'context': selection['context'], 'units': units,
            'source': {
                'archive_name': Path(archive).name,
                'archive_sha256': archive_sha256,
                'reader_member': reader_name, 'selection_member': selection_name,
                'historical_method': 'relevance', 'historical_budget': 2048,
                'historical_budget_tokenizer': 'Qwen3; not a Llama token budget',
                'purpose': 'E01 environment smoke test; not a new formal experiment',
            },
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parents[2] /
                        'artifacts/raw/baseline_v1/baseline_v1_20261013_160804_baseline_results.zip')
    parser.add_argument('--question-id')
    parser.add_argument('--output', type=Path, default=Path('E/E01/input_dev.json'))
    args = parser.parse_args()
    payload = prepare(args.archive, args.question_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    print(f"Prepared DEV {payload['question_id']}: {args.output}")


if __name__ == '__main__':
    main()
