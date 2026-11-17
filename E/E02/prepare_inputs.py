"""Build E02 inputs from pinned public D02/B02/A01 artifacts; stdlib only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from D.D01.selection import render_context, validate


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8', newline='\n')


def render_official_topk(turns_in_rank_order):
    """LongMemEval 9e0b455: flat-turn, JSON, both roles, no fact merge.

    Stable date sorting retains rank order within a date. Unlike D02, the
    official reference numbers chunks and does not deduplicate shared messages.
    """
    parts = []
    ordered = sorted(turns_in_rank_order, key=lambda t: t['session_date'])
    for number, turn in enumerate(ordered, 1):
        messages = [{k: m[k] for k in ('role', 'content')} for m in turn['messages']]
        parts.append(f'\n### Session {number}:\nSession Date: {turn["session_date"]}\nSession Content:\n\n{json.dumps(messages)}\n')
    return ''.join(parts), [t['turn_id'] for t in ordered]


def build(sources, output, topk=50):
    if type(topk) is not int or not 1 <= topk <= 100:
        raise ValueError('topk must be 1..100')
    manifest = json.loads((sources / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['sha256'].items():
        if sha((sources / name).read_bytes()) != expected:
            raise ValueError(f'Source hash mismatch: {name}')
    selections = read_rows(sources / 'd02_selections.jsonl')
    candidates = {r['question_id']: r for r in read_rows(sources / 'b02_candidates.jsonl')}
    qids = [s['question_id'] for s in selections]
    if len(qids) != 5 or len(set(qids)) != 5 or set(qids) != set(candidates):
        raise ValueError('Expected the same five unique D02/B02 questions')
    budget, references, reference_selections = [], [], []
    for s in selections:
        qid = s['question_id']
        turns = read_rows(sources / 'turns' / (qid + '.jsonl'))
        c = candidates[qid]
        records = validate(dict(c, question=s['question'], question_date=s['question_date']), turns)
        ranked = sorted(c['candidates'], key=lambda x: x['rank'])
        if [v['rank'] for v in ranked] != list(range(1, len(ranked) + 1)) or len(ranked) < topk:
            raise ValueError('Incomplete ranked candidate list')
        candidate_ids = {v['turn_id'] for v in ranked}
        if not set(s['selected_turn_ids']) <= candidate_ids:
            raise ValueError('D02 selected a turn outside B02 candidates')
        history = render_context([records[tid] for tid in s['selected_turn_ids']])
        if history != s['history_text'] or sha(history.encode()) != s['history_sha256']:
            raise ValueError('D02 text cannot be reconstructed from selected A01 turns')
        if s['stage'] != 'dev' or s['index'] != 'K0' or s['strategy'] != 'R' or s['budget_tokens'] != 2048:
            raise ValueError('Unexpected D02 setting')
        common = {k: s[k] for k in ('question_id', 'question', 'question_date', 'stage', 'index', 'tokenizer')}
        common.update(tokenizer_fingerprint=s['config']['tokenizer_fingerprint'],
                      input_config_version=c['config_version'], serialization='a01-dedup-json-v1')
        row = dict(common, variant='budget', strategy='R', budget_tokens=2048,
                   config_version=s['config_version'], context=history,
                   context_tokens=s['context_tokens'], history_sha256=s['history_sha256'],
                   selected_turn_ids=s['selected_turn_ids'], source=manifest['provenance'])
        budget.append(row)
        ref_text, selected_ids = render_official_topk([records[v['turn_id']] for v in ranked[:topk]])
        ref = dict(common, variant='original_topk', strategy='original_topk', topk=topk,
                   budget_tokens=None, config_version=f'e02-top{topk}-v1', context=ref_text,
                   history_sha256=sha(ref_text.encode()), selected_turn_ids=selected_ids,
                   source=manifest['provenance'])
        ref['serialization'] = 'longmemeval-9e0b455-flat-turn-json'
        references.append(ref)
        reference_selections.append({k: v for k, v in ref.items() if k != 'context'})
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in [('dev5_budget.jsonl', budget), ('dev5_topk.jsonl', references),
                       ('dev5.jsonl', budget + references), ('topk_selections.jsonl', reference_selections)]:
        write_rows(output / name, rows)
    report = {'status': 'prepared_not_generated', 'question_ids': qids, 'records': 10,
              'topk': topk, 'reference_scope': 'B02 rank top-k; official flat-turn JSON ordering/serialization; Transformers backend adaptation, no silent truncation',
              'tokenizer_check': 'pending on server', 'gpu_generation': 'not run',
              'sha256': {p.name: sha(p.read_bytes()) for p in output.glob('*.jsonl')}}
    (output / 'preparation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, default=ROOT / 'E/E02/inputs/sources')
    parser.add_argument('--output', type=Path, default=ROOT / 'E/E02/inputs')
    parser.add_argument('--topk', type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(build(args.sources, args.output, args.topk), ensure_ascii=False, indent=2))
