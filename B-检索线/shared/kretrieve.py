#!/usr/bin/env python3
"""Shared Stella turn retrieval for B04 (formal K0) and B05 (development K1).

Same embedding path as B02/B03 (official flat-stella, turn granularity).  Only the
index text differs between K0 and K1; candidates always point to full public turns.

  run       encode + rank with per-question checkpoint, export complete delivery only
  validate  structural checks, official top-100 comparison, timing/cost summary
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A01 = ROOT / 'A-数据线/A01/output'
A03 = ROOT / 'A-数据线/A03/output'
B02 = ROOT / 'B-检索线/B02'
SHARED = Path(__file__).resolve().parent
TOKENIZER = 'meta-llama/Llama-3.1-8B-Instruct'
sys.path.insert(0, str(ROOT))


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = module_at('b02_baseline', B02 / 'retrieve_k0.py')
jl = lambda p: baseline.read_jsonl(Path(p))
write_jsonl_atomic = baseline.write_jsonl_atomic


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


# ---------------------------------------------------------------- question sets
def question_set(stage):
    """Frozen public inputs for one stage: ids, delivery splits, questions, turns dir."""
    if stage == 'dev':
        manifest_path = A01 / 'dev_manifest.json'
        m = json.loads(manifest_path.read_text())
        ids, ans, abst = m['dev_ids'], m['dev_answerable_ids'], m['dev_abstention_ids']
        if len(ids) != 40 or len(ans) != 34 or len(abst) != 6 or set(ids) != set(ans) | set(abst):
            raise ValueError('Expected the frozen A01 split (40 = 34 + 6)')
        return {'stage': 'dev', 'manifest_path': manifest_path, 'config_version': m['config_version'],
                'data_sha256': m['data_sha256'], 'ids': ids,
                'questions_path': A01 / 'public/dev_questions.jsonl', 'turns_dir': A01 / 'public/turns',
                'map_dir': A01 / 'map', 'splits': {'all': ids, 'main': ans, 'abstention': abst}}
    if stage == 'formal':
        manifest_path = A03 / 'eval/formal_manifest.json'
        m = json.loads(manifest_path.read_text())
        ids = m['formal_ids']
        if len(ids) != m['actual_count'] or len(set(ids)) != len(ids) or any(q.endswith('_abs') for q in ids):
            raise ValueError('Unexpected A03 formal list')
        dev = set(json.loads((A01 / 'dev_manifest.json').read_text())['dev_ids'])
        if dev & set(ids):
            raise ValueError('Formal questions overlap development questions')
        return {'stage': 'formal', 'manifest_path': manifest_path, 'config_version': m['config_version'],
                'data_sha256': m['data_sha256'], 'ids': ids,
                'questions_path': A03 / 'public/formal_questions.jsonl', 'turns_dir': A03 / 'public/turns',
                'map_dir': A03 / 'map', 'splits': {'main': ids}}
    raise ValueError(stage)


def output_names(spec, index):
    """Delivery file per split; dev keeps B03 naming (dev_K0 / dev_abstention_K0 / dev_all_K0)."""
    s = spec['stage']
    names = {'main': f'{s}_{index}.jsonl', 'abstention': f'{s}_abstention_{index}.jsonl',
             'all': f'{s}_all_{index}.jsonl'}
    return {k: names[k] for k in spec['splits']}


def load_items(spec):
    from D.D01.selection import validate
    questions = jl(spec['questions_path'])
    if len({q['question_id'] for q in questions}) != len(questions):
        raise ValueError('Duplicate public question')
    questions = {q['question_id']: q for q in questions}
    if set(spec['ids']) - set(questions):
        raise ValueError('Public question file is missing manifest IDs')
    items = []
    for qid in spec['ids']:
        q = questions[qid]
        if set(q) != {'question_id', 'stage', 'question', 'question_date'} or q['stage'] != spec['stage']:
            raise ValueError(f'{qid}: unexpected public question record')
        path = spec['turns_dir'] / f'{qid}.jsonl'
        if not path.exists():
            raise FileNotFoundError(f'{path}: run the input preparation step first')
        turns = jl(path)
        if len(turns) < 100 or len({t['turn_id'] for t in turns}) != len(turns):
            raise ValueError(f'{qid}: expected at least 100 distinct turns')
        for t in turns:
            if t['messages'][0]['role'] != 'user':
                raise ValueError(f'{t["turn_id"]}: first message is not the user message')
        validate(dict(q, index='K0', budget_tokens=2048, candidates=[]), turns)
        items.append((q, turns))
    return items


# ---------------------------------------------------------------- index text
def load_facts(path):
    """Public turn_id -> list[str] built by B05/prepare_facts.py (no official IDs inside)."""
    rows = jl(path)
    return {r['turn_id']: r['facts'] for r in rows}


def k1_text(facts, text):
    """Official `turn-userfact` + `merge`: ' '.join(facts) + ' ' + user text.

    A turn without facts keeps its original user text (identical to K0)."""
    return ' '.join(facts) + ' ' + text if facts else text


def index_texts(turns, index, facts):
    if index == 'K0':
        return [t['messages'][0]['content'] for t in turns]
    if index == 'K1':
        missing = [t['turn_id'] for t in turns if t['turn_id'] not in facts]
        if missing:
            raise ValueError(f'No fact record for {len(missing)} turns, e.g. {missing[:3]}')
        return [k1_text(facts[t['turn_id']], t['messages'][0]['content']) for t in turns]
    raise ValueError(index)


def settings(spec, index, batch_size=64):
    return {'stage': spec['stage'], 'index': index, 'config_version': spec['config_version'],
            'top_k': 100, 'max_length': 512, 'batch_size': batch_size, 'dtype': 'float32',
            'projection_dim': 1024, 'pooling': 'attention-mask mean', 'normalization': 'sklearn L2',
            'query_prefix': '', 'score': 'NumPy dot product',
            'retrieval_text': 'first user message only' if index == 'K0'
            else "' '.join(facts) + ' ' + first user message (facts empty -> user message only)",
            'budget_tokens': 2048, 'tokenizer': TOKENIZER}


def public_row(question, candidates, config):
    return {'question_id': question['question_id'], 'stage': config['stage'], 'index': config['index'],
            'strategy': None, 'budget_tokens': config['budget_tokens'], 'tokenizer': TOKENIZER,
            'config_version': config['config_version'], 'candidates': candidates}


def check_row(row, question, turns, config):
    from D.D01.selection import validate
    expected = public_row(question, [], config)
    if set(row) != set(expected) or any(row[k] != expected[k] for k in expected if k != 'candidates'):
        raise ValueError('Candidate record fields/metadata mismatch')
    cands = row['candidates']
    if len(cands) != 100 or [c['rank'] for c in cands] != list(range(1, 101)):
        raise ValueError('Expected exactly 100 sequentially ranked candidates')
    scores = [c['score'] for c in cands]
    if not all(type(s) in (float, int) and math.isfinite(s) for s in scores):
        raise ValueError('Non-finite scores')
    if any(a < b for a, b in zip(scores, scores[1:])):
        raise ValueError('Scores not descending')
    validate(dict(row, question=question['question'], question_date=question['question_date']), turns)


# ---------------------------------------------------------------- run
def run_questions(items, config, identity, checkpoint, resume, score_question):
    """Persist each finished question; partial state is never a delivery."""
    state = {'identity': identity, 'completed': {}, 'stats': {}}
    if checkpoint.exists():
        if not resume:
            raise ValueError('Checkpoint exists; use --resume or a new output directory')
        state = json.loads(checkpoint.read_text())
        if state.get('identity') != identity:
            raise ValueError('Checkpoint fingerprint mismatch (inputs/model/settings/software/source)')
        if set(state['completed']) - {q['question_id'] for q, _ in items}:
            raise ValueError('Checkpoint contains unexpected question IDs')
    for q, turns in items:
        qid = q['question_id']
        if qid in state['completed']:
            check_row(state['completed'][qid], q, turns, config)
            print(f'{qid}: resume skip', flush=True)
            continue
        try:
            row, stats = score_question(q, turns)
            check_row(row, q, turns, config)
            state['completed'][qid] = row
            state['stats'][qid] = stats
            write_jsonl_atomic(checkpoint, [state])
            print(f'{qid}: 100 candidates, {stats["total_s"]:.2f}s ({len(state["completed"])}/{len(items)})',
                  flush=True)
        except Exception as exc:
            write_jsonl_atomic(checkpoint.with_suffix('.failure.json'), [{
                'question_id': qid, 'error_type': type(exc).__name__, 'error': str(exc),
                'completed_questions': len(state['completed'])}])
            raise
    return state


def export(state, spec, index, output):
    completed = state['completed']
    if set(completed) != set(spec['ids']):
        raise ValueError('Refusing to export an incomplete question set')
    for split, name in output_names(spec, index).items():
        write_jsonl_atomic(output / 'candidates' / name, [completed[q] for q in spec['splits'][split]])


def cost_summary(state, model_load_s):
    stats = state['stats']
    total = lambda k: sum(s[k] for s in stats.values())
    return {'questions': len(stats), 'model_load_s': model_load_s,
            'index_build_s': total('index_encode_s'), 'retrieval_s': total('query_encode_s') + total('rank_s'),
            'total_question_s': total('total_s'), 'indexed_turns': total('n_turns'),
            'indexed_tokens_after_truncation': total('index_tokens'),
            'index_tokens_before_truncation': total('index_tokens_raw'),
            'truncated_index_texts': total('n_truncated'),
            'per_question': stats,
            'scope': ('index_build = Stella encoding of all history index texts for one question; '
                      'retrieval = query encoding + dot product + top-100 ranking; model_load is one-time; '
                      'hash checks and official comparison excluded. Token counts use the Stella tokenizer '
                      'with special tokens; truncation limit 512.')}


def cmd_run(args):
    spec = question_set(args.stage)
    items = load_items(spec)
    facts, facts_sha = None, None
    if args.index == 'K1':
        if args.facts is None:
            raise SystemExit('--facts is required for K1')
        facts, facts_sha = load_facts(args.facts), sha(args.facts)
    for q, turns in items:  # fail fast on missing facts before touching the GPU
        index_texts(turns, args.index, facts)
    print(f'Validated {len(items)} {args.stage} histories, {sum(len(t) for _, t in items)} turns', flush=True)
    if args.validate_inputs:
        return
    import numpy
    import sklearn
    import torch
    import transformers
    if not torch.cuda.is_available():
        raise RuntimeError('A Slurm CUDA allocation is required')
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    checkpoint = out / 'checkpoint.json'
    with (out / 'checkpoint.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        model_hashes = json.loads((B02 / 'model_sha256.json').read_text())
        for name, expected in model_hashes.items():
            if sha(args.model_dir / name) != expected:
                raise ValueError(f'Model hash mismatch: {name}')
        print(f'All {len(model_hashes)} model file hashes verified', flush=True)
        config = settings(spec, args.index, args.batch_size)
        software = {'torch': torch.__version__, 'transformers': transformers.__version__,
                    'numpy': numpy.__version__, 'sklearn': sklearn.__version__,
                    'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name()}
        provenance = {'config': config, 'software': software, 'model_sha256': model_hashes,
                      'public_inputs_sha256': digest([{'question': q, 'turns': t} for q, t in items]),
                      'facts_sha256': facts_sha, 'manifest_sha256': sha(spec['manifest_path']),
                      'source_sha256': {'shared/kretrieve.py': sha(Path(__file__)),
                                        'B02/retrieve_k0.py': sha(B02 / 'retrieve_k0.py')}}
        identity = digest(provenance)
        if checkpoint.exists() and (not args.resume or json.loads(checkpoint.read_text()).get('identity') != identity):
            raise ValueError('Existing checkpoint requires --resume and an identical run fingerprint')
        write_jsonl_atomic(out / 'provenance.json', [dict(provenance, identity=identity)])
        parts, load_s = None, None

        def score_question(q, turns):
            nonlocal parts, load_s
            if parts is None:
                t0 = time.monotonic()
                parts = baseline.load_model(args.model_dir, torch.device('cuda:0'))
                load_s = time.monotonic() - t0
                print(f'Model loaded in {load_s:.2f}s', flush=True)
            tok, model, linear = parts
            texts = index_texts(turns, args.index, facts)
            lengths = [len(x) for x in tok(texts, truncation=False)['input_ids']]
            torch.cuda.synchronize()
            t0 = time.monotonic()
            dvec = baseline.embed(texts, tok, model, linear, args.batch_size)
            t1 = time.monotonic()
            qvec = baseline.embed([q['question']], tok, model, linear, 1)
            t2 = time.monotonic()
            scores = torch.tensor((qvec @ dvec.T).squeeze(0))
            order = scores.argsort(descending=True)[:100].tolist()
            cands = [{'turn_id': turns[i]['turn_id'], 'rank': r, 'score': float(scores[i])}
                     for r, i in enumerate(order, 1)]
            t3 = time.monotonic()
            stats = {'n_turns': len(turns), 'index_encode_s': t1 - t0, 'query_encode_s': t2 - t1,
                     'rank_s': t3 - t2, 'total_s': t3 - t0,
                     'index_tokens_raw': sum(lengths), 'index_tokens': sum(min(n, 512) for n in lengths),
                     'n_truncated': sum(n > 512 for n in lengths)}
            return public_row(q, cands, config), stats

        state = run_questions(items, config, identity, checkpoint, args.resume, score_question)
        export(state, spec, args.index, out)
        prior = jl(out / 'cost.json')[0] if (out / 'cost.json').exists() else {}
        load = load_s if load_s is not None else prior.get('model_load_s')
        write_jsonl_atomic(out / 'cost.json', [dict(cost_summary(state, load), identity=identity)])
        print(f'Exported {", ".join(f"{k}={len(v)}" for k, v in spec["splits"].items())}', flush=True)


# ---------------------------------------------------------------- validate
def cmd_validate(args):
    spec = question_set(args.stage)
    items = load_items(spec)
    config = settings(spec, args.index)
    names = output_names(spec, args.index)
    full = 'all' if 'all' in names else 'main'
    rows = jl(args.output_dir / 'candidates' / names[full])
    if [r['question_id'] for r in rows] != spec['splits'][full]:
        raise ValueError('Delivery has missing, duplicate, or reordered IDs')
    by_id = {r['question_id']: r for r in rows}
    for q, turns in items:
        check_row(by_id[q['question_id']], q, turns, config)
    for split, name in names.items():
        if jl(args.output_dir / 'candidates' / name) != [by_id[q] for q in spec['splits'][split]]:
            raise ValueError(f'Incorrect split or changed payload: {name}')
    raw = {r['question_id']: r for r in jl(args.official_log)}
    if set(raw) != set(spec['ids']):
        raise ValueError('Official log covers a different question set')
    comparisons = []
    for qid in spec['ids']:
        # Compare in official corpus-id space: a haystack may repeat an identical session
        # (same official id, same text), so official id -> turn_id is not one-to-one.
        to_official = {r['turn_id']: r['official_corpus_id'] for r in jl(spec['map_dir'] / f'{qid}.turns.jsonl')}
        theirs = [r['corpus_id'] for r in raw[qid]['retrieval_results']['ranked_items'][:100]]
        mine = [to_official[c['turn_id']] for c in by_id[qid]['candidates']]
        dup = len(set(to_official.values())) < len(to_official)
        comparisons.append({'question_id': qid, 'same_order': mine == theirs,
                            'same_set': sorted(mine) == sorted(theirs), 'repeated_session_in_history': dup,
                            'different_positions': [i + 1 for i, (a, b) in enumerate(zip(mine, theirs)) if a != b]})
    regression = []
    if args.regression:  # same stage/index rows produced earlier must be unchanged
        for old in jl(args.regression):
            new = by_id.get(old['question_id'])
            if new is None:
                continue
            o = {c['turn_id']: c['score'] for c in old['candidates']}
            n = {c['turn_id']: c['score'] for c in new['candidates']}
            regression.append({'question_id': old['question_id'],
                               'same_order': list(o) == list(n),
                               'max_absolute_score_difference': max(abs(o[k] - n[k]) for k in o) if o.keys() == n.keys() else None})
    cost = jl(args.output_dir / 'cost.json')[0]
    passed = all(c['same_order'] for c in comparisons) and all(
        r['same_order'] and r['max_absolute_score_difference'] <= 1e-5 for r in regression)
    result = {'passed': passed, 'stage': spec['stage'], 'index': args.index,
              'questions': {k: len(v) for k, v in spec['splits'].items()},
              'candidates_per_question': 100, 'total_candidates': 100 * len(spec['ids']),
              'D01_public_input_validation': f'passed for all {len(spec["ids"])}',
              'official_same_order': sum(c['same_order'] for c in comparisons),
              'official_same_set': sum(c['same_set'] for c in comparisons),
              'official_top100_comparison': comparisons, 'regression': regression,
              'truncated_index_texts': cost['truncated_index_texts'], 'indexed_turns': cost['indexed_turns'],
              'candidate_sha256': {f.name: sha(f) for f in sorted((args.output_dir / 'candidates').glob('*.jsonl'))},
              'scope': 'rank/order comparison only; official log has no scores; not an answer-accuracy evaluation'}
    write_jsonl_atomic(args.report, [result])
    print(json.dumps({k: v for k, v in result.items() if k != 'official_top100_comparison'}, indent=2))
    if not passed:
        raise SystemExit('Official/regression comparison failed; see report')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    v = sub.add_parser('validate')
    for x in (r, v):
        x.add_argument('--stage', choices=['dev', 'formal'], required=True)
        x.add_argument('--index', choices=['K0', 'K1'], required=True)
        x.add_argument('--output-dir', type=Path)
    r.add_argument('--facts', type=Path)
    r.add_argument('--model-dir', type=Path)
    r.add_argument('--resume', action='store_true')
    r.add_argument('--batch-size', type=int, default=64)
    r.add_argument('--validate-inputs', action='store_true')
    v.add_argument('--official-log', type=Path, required=True)
    v.add_argument('--regression', type=Path)
    v.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    if a.cmd == 'run':
        if not a.validate_inputs and (a.model_dir is None or a.output_dir is None or a.batch_size < 1):
            p.error('--model-dir and --output-dir are required; batch size must be positive')
        cmd_run(a)
    else:
        cmd_validate(a)


if __name__ == '__main__':
    main()
