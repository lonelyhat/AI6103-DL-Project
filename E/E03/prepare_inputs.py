"""Adapt D selections without changing chosen turns, history, or token counts."""
import argparse
import json
from pathlib import Path
import sys

from batch import digest, load_inputs, normalize, sha
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from D.D01.selection import render_context


def read_rows(path):
    # JSONL is delimited by physical newlines. Unicode separators (e.g. U+2028)
    # are legal inside JSON strings and must not split a record.
    with path.open(encoding='utf-8-sig') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build(selection_paths, turns_dir, output):
    rows, sources = [], {}
    for path in selection_paths:
        sources[str(path)] = sha(path.read_bytes())
        for selection in read_rows(path):
            qid = selection['question_id']
            # A01 IDs are file stems; reject traversal in external input.
            if '/' in qid or '\\' in qid or qid in ('.', '..'):
                raise ValueError('Invalid question_id')
            turn_path = turns_dir / (qid + '.jsonl')
            turns = {t['turn_id']: t for t in read_rows(turn_path)}
            sources[str(turn_path)] = sha(turn_path.read_bytes())
            history = render_context([turns[tid] for tid in selection['selected_turn_ids']])
            if history != selection['history_text'] or sha(history.encode()) != selection['history_sha256']:
                raise ValueError(f'{qid}: D history does not match original selected turns')
            conf = selection['config']
            if digest(conf) != selection['config_id']:
                raise ValueError('D config_id does not match config')
            for key in ('strategy', 'budget_tokens', 'tokenizer'):
                if conf[key] != selection[key]:
                    raise ValueError(f'D config/row conflict: {key}')
            common = {k: selection[k] for k in ('question_id', 'question', 'question_date',
                'stage', 'index', 'strategy', 'budget_tokens', 'tokenizer', 'config_version',
                'selected_turn_ids', 'history_sha256', 'context_tokens')}
            rows.append(normalize(dict(common, context=history, variant='budget',
                tokenizer_fingerprint=conf['tokenizer_fingerprint'],
                serialization=conf['serialization'], input_config_version=conf['input_config_version'],
                selection_config=conf, selection_config_id=selection['config_id'],
                source={'selection_file': str(path), 'selection_sha256': sources[str(path)],
                        'turn_file': str(turn_path), 'turn_sha256': sources[str(turn_path)]})))
    if not rows or len({r['record_id'] for r in rows}) != len(rows):
        raise ValueError('Empty or duplicate selection inputs')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    load_inputs(output)
    return {'records': len(rows), 'questions': len({r['question_id'] for r in rows}),
            'settings': sorted({r['index']+'/'+r['strategy'] for r in rows}),
            'input_sha256': sha(output.read_bytes()), 'source_sha256': sources,
            'status': 'prepared_not_generated', 'tokenizer_check': 'pending on server'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selections', type=Path, nargs='+', required=True)
    parser.add_argument('--turns-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.selections, args.turns_dir, args.output), ensure_ascii=False, indent=2))
