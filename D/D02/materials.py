"""D02: one-pass rank selection with exact deduplicated history budgets.

Shares A01 validation and serialization with D01. No official IDs or evaluation
files are used. All costs are evaluated on whole original messages.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import sys

if __package__:
    from ..D01.selection import digest, render_context, validate
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from D.D01.selection import digest, render_context, validate

VERSION = 'd02-v1'


def count_history(counter, history):
    count = counter.count(history)
    if type(count) is not int or count < 0:
        raise ValueError('history counter must return a nonnegative integer')
    return count


def select_ranked(request, turns, counter):
    """Return A01-compatible selection plus detailed per-candidate audit.

    Each candidate is visited once in rank order. A failed budget trial is
    skipped permanently; all subsequent ranks are still visited, even if the
    current count equals the budget (tokenization need not be additive).
    """
    records = validate(request, turns)
    if request.get('strategy') not in (None, 'R'):
        raise ValueError('D02 only prepares strategy R')
    if request.get('config_version') != 'a01-v2':
        raise ValueError('D02 requires A01-v2 public/candidate records')
    if request.get('tokenizer') not in (None, counter.name):
        raise ValueError('candidate tokenizer label differs from actual reader counter')
    if count_history(counter, '') != 0:
        raise ValueError('empty history must cost zero')
    candidates = sorted(request['candidates'], key=lambda c: (c['rank'], c['turn_id']))
    budget = request['budget_tokens']
    selected, steps, trials, skipped = [], [], [], []
    current = 0
    for candidate in candidates:
        tid = candidate['turn_id']
        single = count_history(counter, render_context([records[tid]]))
        proposal = render_context([records[t] for t in selected + [tid]])
        total = count_history(counter, proposal)
        marginal = total-current
        selected_messages = {m['message_id'] for t in selected for m in records[t]['messages']}
        trial_messages = records[tid]['messages']
        duplicate_messages = [m['message_id'] for m in trial_messages if m['message_id'] in selected_messages]
        fits = total <= budget
        trial = {'visit': len(trials)+1, 'turn_id': tid, 'rank': candidate['rank'],
                 'retrieval_score': candidate['score'], 'decision': 'selected' if fits else 'skipped',
                 'reason': 'fits_budget' if fits else 'over_budget',
                 'context_tokens_before': current, 'standalone_context_tokens': single,
                 'standalone_over_budget': single > budget,
                 'proposed_context_tokens': total, 'marginal_tokens': marginal,
                 'duplicate_message_ids_removed': duplicate_messages}
        trials.append(trial)
        if fits:
            selected.append(tid)
            current = total
            steps.append({'step': len(steps)+1, **{k:v for k,v in trial.items() if k != 'visit'},
                          'score': candidate['score'], 'context_tokens': current})
        else:
            skipped.append(trial)
    ordered = sorted((records[t] for t in selected), key=lambda t: (t['sort_key'], t['turn_id']))
    history = render_context(ordered)
    final_count = count_history(counter, history)
    if final_count != current or final_count > budget:
        raise RuntimeError('final exact history budget check failed')
    selected_message_ids = list(dict.fromkeys(m['message_id'] for t in ordered for m in t['messages']))
    full_message_count = sum(len(t['messages']) for t in ordered)
    config = {'implementation': VERSION, 'input_config_version': 'a01-v2', 'strategy': 'R',
              'selection': 'rank-ascending-one-pass-skip-oversize',
              'serialization': 'a01-dedup-json-v1', 'sort': 'session_datetime-session_index-user_position',
              'budget_tokens': budget, 'counter': 'reader-tokenizer-no-special-tokens',
              'tokenizer': counter.name, 'tokenizer_fingerprint': getattr(counter, 'fingerprint', counter.name),
              'stop': 'exhaust-all-candidates', 'relevance': 'raw-score-recorded-rank-controls-R'}
    return {'question_id': request['question_id'], 'question': request['question'],
            'question_date': request.get('question_date'), 'stage': request['stage'], 'index': request['index'],
            'strategy': 'R', 'budget_tokens': budget, 'tokenizer': counter.name, 'config_version': VERSION,
            'config_id': digest(config), 'config': config,
            'input_sha256': digest({'request': request, 'candidate_turns': [records[c['turn_id']] for c in candidates]}),
            'selected_turn_ids': [t['turn_id'] for t in ordered], 'selection_order': selected,
            'selected_message_ids': selected_message_ids, 'context_tokens': final_count,
            'history_text': history, 'history_sha256': hashlib.sha256(history.encode()).hexdigest(),
            'skipped_turn_ids': [t['turn_id'] for t in skipped], 'steps': steps, 'candidate_trials': trials,
            'standalone_over_budget_turn_ids': [t['turn_id'] for t in trials if t['standalone_over_budget']],
            'skipped': skipped, 'stop_reason': 'candidate_list_exhausted' if candidates else 'empty_candidates',
            'n_candidates': len(candidates), 'n_selected_turns': len(selected),
            'n_unique_messages': len(selected_message_ids),
            'n_duplicate_message_occurrences_removed': full_message_count-len(selected_message_ids),
            'budget_check': {'scope': 'serialized_history_only', 'passed': True, 'actual': final_count,
                             'limit': budget, 'remaining': budget-final_count},
            'status': 'ready_for_reader' if selected else 'empty_material'}
