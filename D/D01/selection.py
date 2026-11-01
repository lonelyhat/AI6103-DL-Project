"""Budgeted selectors over A01 public turns; no official/evaluation IDs are read."""
from __future__ import annotations
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime

VERSION = 'd01-v1'
STRATEGIES = ('R', 'MMR', 'C', 'Q', 'FL')
STOPWORDS = frozenset('a an the i me my we our you your he she it they their is are was were be been do does did have has had to of in on at for from and or but with about what which who when where why how much many after before this that these those please tell would could can'.split())


def lexical(text):
    # Fixed word/number/CJK-character rules, no query-conditioned model or labels.
    return re.findall(r"[a-z]+(?:'[a-z]+)?|\d+(?:[.,]\d+)*|[\u3400-\u9fff]", text.casefold())


def clues(question):
    return set(lexical(question)) - STOPWORDS


class CharacterTokenizer:
    """Explicit test-only counter, never a model-token estimate."""
    name = 'demo:characters'
    def count(self, text):
        return len(text)


class HFTokenizer:
    def __init__(self, model, allow_download=False):
        from transformers import AutoTokenizer
        self.name = model
        self.tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=not allow_download,
                                                       trust_remote_code=False, use_fast=True)
        if not self.tokenizer.is_fast:
            raise ValueError("a fast tokenizer is required for a reproducible fingerprint")
    @property
    def fingerprint(self):
        return hashlib.sha256(self.tokenizer.backend_tokenizer.to_str().encode()).hexdigest()
    def count(self, text):
        return len(self.tokenizer.encode(text, add_special_tokens=False))


@dataclass(frozen=True)
class Config:
    redundancy_weight: float = 0.5
    coverage_weight: float = 0.5
    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('weights must be finite and nonnegative')
            object.__setattr__(self, name, float(value))


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _keys(row, allowed, required):
    if not isinstance(row, dict) or set(row) - set(allowed) or set(required) - set(row):
        raise ValueError(f'invalid fields; allowed={allowed}, required={required}')


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def validate(request, turns):
    _keys(request, ('question_id', 'question', 'question_date', 'stage', 'index', 'strategy',
                    'budget_tokens', 'tokenizer', 'config_version', 'candidates'),
          ('question_id', 'question', 'stage', 'index', 'budget_tokens', 'candidates'))
    qid = request['question_id']
    if not isinstance(qid, str) or not re.fullmatch(r'[a-z0-9_]+', qid):
        raise ValueError('invalid question_id')
    if not isinstance(request['question'], str) or not _integer(request['budget_tokens']):
        raise ValueError('question must be text; budget_tokens must be nonnegative integer')
    if request['index'] not in ('K0', 'K1') or request['stage'] not in ('dev', 'formal'):
        raise ValueError('invalid stage/index')
    for field in ('question_date', 'config_version', 'tokenizer'):
        if request.get(field) is not None and not isinstance(request[field], str):
            raise ValueError(f'{field} must be text or null')
    if request.get('strategy') not in (None, *STRATEGIES):
        raise ValueError('invalid strategy')
    if not isinstance(request['candidates'], list) or len(request['candidates']) > 100:
        raise ValueError('B must supply at most 100 canonical candidates')
    records, messages = {}, {}
    for t in turns:
        _keys(t, ('turn_id', 'session_index', 'session_date', 'session_datetime', 'sort_key', 'messages'),
              ('turn_id', 'session_index', 'session_date', 'session_datetime', 'sort_key', 'messages'))
        tid = t['turn_id']
        if not isinstance(tid, str) or not re.fullmatch(re.escape(qid) + r'-s\d{3}-t\d{3}', tid) or tid in records:
            raise ValueError('duplicate, foreign or invalid turn_id')
        key = t['sort_key']
        if (not isinstance(key, list) or len(key) != 3 or
            not isinstance(key[0], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', key[0]) or
            not _integer(key[1]) or not _integer(key[2]) or not _integer(t['session_index']) or key[1] != t['session_index'] or
            key[0] != t['session_datetime'] or not isinstance(t['session_date'], str) or
            tid.rsplit('-t', 1)[0] != f'{qid}-s{key[1]:03d}'):
            raise ValueError('invalid A01 sort_key/session metadata')
        try:
            datetime.fromisoformat(key[0])
        except ValueError as error:
            raise ValueError('invalid calendar date in sort_key') from error
        ms = t['messages']
        if not isinstance(ms, list) or not 1 <= len(ms) <= 2 or not isinstance(ms[0], dict) or ms[0].get('role') != 'user':
            raise ValueError('turn must contain a user and optional next message')
        for offset, m in enumerate(ms):
            _keys(m, ('message_id', 'role', 'content'), ('message_id', 'role', 'content'))
            expected = f'{qid}-s{key[1]:03d}-m{key[2]+offset:03d}'
            if m['message_id'] != expected or m['role'] not in ('user', 'assistant', 'system') or not isinstance(m['content'], str):
                raise ValueError('invalid message identity/role/content')
            if expected in messages and messages[expected] != m:
                raise ValueError('conflicting shared message')
            messages[expected] = m
        records[tid] = t
    ranks, ids = set(), set()
    for c in request['candidates']:
        _keys(c, ('turn_id', 'rank', 'score'), ('turn_id', 'rank', 'score'))
        if c['turn_id'] not in records or c['turn_id'] in ids or not _integer(c['rank'], 1) or c['rank'] in ranks:
            raise ValueError('unknown/duplicate candidate or duplicate/invalid rank')
        if isinstance(c['score'], bool) or not isinstance(c['score'], (float, int)) or not math.isfinite(c['score']):
            raise ValueError('finite numeric retrieval score required; rank fallback forbidden')
        ids.add(c['turn_id']); ranks.add(c['rank'])
    return records


def render_context(turns):
    """Serialize chronological whole turns; each shared message appears once."""
    seen, chunks = set(), []
    for turn in sorted(turns, key=lambda t: (t['sort_key'], t['turn_id'])):
        ms = [m for m in turn['messages'] if m['message_id'] not in seen]
        if not ms:
            continue
        seen.update(m['message_id'] for m in ms)
        # Identical session date/title overhead for every strategy; no rank or labels.
        content = json.dumps([{'role': m['role'], 'content': m['content']} for m in ms],
                             ensure_ascii=False, separators=(',', ':'))
        chunks.append(f"### Session Date: {turn['session_date']}\nSession Content:\n{content}\n")
    return '\n'.join(chunks)


def similarities(texts):
    """Candidate-local TF-IDF cosine on full original user+next-message text."""
    counts = [Counter(lexical(t)) for t in texts]
    df = Counter(w for c in counts for w in c)
    vectors = [{w: n * (math.log((1 + len(texts)) / (1 + df[w])) + 1)
                for w, n in c.items()} for c in counts]
    norms = [math.sqrt(sum(x*x for x in v.values())) for v in vectors]
    return [[min(1.0, max(0.0, sum(v * vectors[j].get(w, 0) for w, v in vectors[i].items()) /
             (norms[i] * norms[j]))) if norms[i] and norms[j] else float(i == j)
             for j in range(len(texts))] for i in range(len(texts))]


def select(request, turns, tokenizer, strategy=None, config=None):
    """Unified A01-v2 input -> A01 selection record plus auditable reading text."""
    config = config or Config()
    strategy = strategy or request.get('strategy')
    if strategy not in STRATEGIES:
        raise ValueError('choose R/MMR/C/Q/FL')
    records = validate(request, turns)
    if request.get('tokenizer') not in (None, tokenizer.name):
        raise ValueError('request tokenizer does not match actual counter')
    candidates = sorted(request['candidates'], key=lambda c: (c['rank'], c['turn_id']))
    data = [records[c['turn_id']] for c in candidates]
    raw = [c['score'] for c in candidates]
    lo, hi = (min(raw), max(raw)) if raw else (0, 0)
    spread = hi-lo
    relevance = [((r-lo)/spread if math.isfinite(spread) else
                  (r/2-lo/2)/(hi/2-lo/2)) if hi > lo else 1.0 for r in raw]
    texts = ['\n'.join(m['content'] for m in t['messages']) for t in data]
    sim = similarities(texts)
    query_clues = clues(request['question'])
    matched = [query_clues & set(lexical(t)) for t in texts]
    selected, steps = [], []
    covered, facilities = set(), [0.0] * len(data)
    budget = request['budget_tokens']
    current = tokenizer.count('')
    if current != 0:
        raise ValueError('counter must count empty history as zero')
    def proposal(i):
        text = render_context([data[j] for j in selected + [i]])
        total = tokenizer.count(text)
        if not _integer(total):
            raise ValueError('counter must return nonnegative integer')
        delta = total - current
        # Exact token counts can be nonmonotone; max(1, delta) avoids division by zero.
        cost = max(1, delta)
        d = max((sim[i][j] for j in selected), default=0.0)
        new = matched[i] - covered
        gain = len(new) / max(1, len(query_clues))
        facility_gain = sum(relevance[j] * max(0, sim[i][j] - facilities[j]) for j in range(len(data)))
        numerator = relevance[i] - config.redundancy_weight*d
        if strategy == 'R': utility = relevance[i]
        elif strategy == 'MMR': utility = numerator
        elif strategy == 'C': utility = numerator / cost
        elif strategy == 'Q': utility = (numerator + config.coverage_weight*gain) / cost
        else: utility = facility_gain / cost
        return {'turn_id': candidates[i]['turn_id'], 'rank': candidates[i]['rank'],
                'relevance': relevance[i], 'redundancy': d, 'new_clues': sorted(new),
                'coverage_gain': gain, 'facility_gain': facility_gain, 'score': utility,
                'marginal_tokens': delta, 'cost_denominator': cost, 'context_tokens': total}
    stop = 'exhausted'
    remaining = list(range(len(data)))
    while remaining:
        proposals = [(i, proposal(i)) for i in remaining]
        feasible = [(i, p) for i, p in proposals if p['context_tokens'] <= budget]
        if not feasible:
            stop = 'no_candidate_fits'; break
        if strategy == 'R':
            i, p = feasible[0]
        else:
            i, p = max(feasible, key=lambda x: (x[1]['score'], -candidates[x[0]]['rank']))
            if p['score'] <= 0:
                stop = 'nonpositive_gain'; break
        selected.append(i); remaining.remove(i); current = p['context_tokens']
        covered.update(matched[i])
        facilities = [max(facilities[j], sim[i][j]) for j in range(len(data))]
        steps.append({'step': len(steps)+1, **p})
    # Re-evaluate skipped candidates against final material; no stale cost assumptions.
    skipped = []
    for i in remaining:
        p = proposal(i)
        skipped.append({'turn_id': p['turn_id'], 'reason': 'over_budget' if p['context_tokens'] > budget else 'nonpositive_gain',
                        'proposed_context_tokens': p['context_tokens'], 'score': p['score']})
    chronological = sorted((data[i] for i in selected), key=lambda t: (t['sort_key'], t['turn_id']))
    history = render_context(chronological)
    exact = tokenizer.count(history)
    if exact != current or exact > budget:
        raise RuntimeError('final budget invariant failed')
    settings = {'implementation': VERSION, **asdict(config), 'similarity': 'original-round-tfidf-cosine-v1',
                'clues': 'fixed-lexical-v1', 'relevance': 'candidate-minmax-equal-one',
                'cost': 'exact-history-delta-floor-one', 'serialization': 'a01-dedup-json-v1',
                'stop': 'R-fill-others-positive-only', 'tokenizer': tokenizer.name,
                'tokenizer_fingerprint': getattr(tokenizer, 'fingerprint', tokenizer.name),
                'strategy': strategy, 'budget_tokens': budget,
                'input_config_version': request.get('config_version')}
    selected_messages = list(dict.fromkeys(m['message_id'] for t in chronological for m in t['messages']))
    return {'question_id': request['question_id'], 'stage': request['stage'], 'index': request['index'],
            'strategy': strategy, 'budget_tokens': budget, 'tokenizer': tokenizer.name,
            'config_version': VERSION, 'config_id': digest(settings), 'config': settings,
            'input_sha256': digest({'request': request, 'candidate_turns': data}),
            'selected_turn_ids': [t['turn_id'] for t in chronological],
            'selection_order': [candidates[i]['turn_id'] for i in selected],
            'selected_message_ids': selected_messages, 'context_tokens': exact,
            'history_text': history, 'history_sha256': hashlib.sha256(history.encode()).hexdigest(),
            'skipped_turn_ids': [s['turn_id'] for s in skipped], 'skipped': skipped,
            'steps': steps, 'stop_reason': stop, 'question_clues': sorted(query_clues),
            'covered_clues': sorted(covered)}

