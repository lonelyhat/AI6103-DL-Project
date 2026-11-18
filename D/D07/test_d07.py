import copy
import unittest

from D.D01.selection import CharacterTokenizer
from D.D02.test_materials import turn, request
from D.D07.run import (CachedCounter, baseline_key, check_baseline, make_cases,
                       metric_row, replay, select_case, summarize_metrics)


class Counter(CharacterTokenizer):
    fingerprint = 'test-only-characters'


class Evidence:
    def retention(self, qid, ids):
        kept = 'toy-s000-t000' in ids
        return dict(is_abstention=False, has_evidence=True, n_evidence_msgs=1,
                    n_retained_msgs=int(kept), msg_retention=float(kept),
                    all_retained=kept, any_retained=kept,
                    missing_message_ids=[] if kept else ['toy-s000-m000'])


def parameters():
    return dict(methods=[dict(strategy=s, redundancy_weight=l, coverage_weight=g)
                         for s, l, g in [('R', 0, 0), ('MMR', .5, 0), ('C', 1, 0),
                                         ('Q', .5, 1), ('FL', 0, 0)]])


class D07Tests(unittest.TestCase):
    def setUp(self):
        self.counter = CachedCounter(Counter())
        self.turns = [turn(0, 'old rent alpha ' * 8), turn(1, 'new rent bravo'), turn(2, 'alpha')]
        self.candidate = request(self.turns)
        self.question = {k: self.candidate[k] for k in ('question_id', 'stage', 'question', 'question_date')}
        self.candidate.pop('question')

    def test_grid_uses_fixed_winners_and_only_zeroes_q_gamma(self):
        cases = make_cases(parameters(), [1024, 2048, 4096])
        self.assertEqual(len(cases) * 34 * 2, 1224)
        for budget in (1024, 2048, 4096):
            on, off = [next(c for c in cases if c['strategy'] == 'Q' and c['budget_tokens'] == budget
                            and c['condition'] == cond) for cond in ('main', 'coverage_off')]
            self.assertEqual(on['redundancy_weight'], off['redundancy_weight'])
            self.assertEqual((on['coverage_weight'], off['coverage_weight']), (1, 0))
        for budgets in ([0], [True], [1024, 1024]):
            with self.assertRaises(ValueError):
                make_cases(parameters(), budgets)

    def test_real_selection_replay_and_budget_intervention_preserves_inputs(self):
        before = copy.deepcopy((self.candidate, self.turns, self.question))
        for case in make_cases(parameters(), [1, 200, 2048]):
            row, req, _ = select_case(self.candidate, self.question, self.turns, self.counter, case)
            replay(row, req, self.turns, self.counter, case)
            self.assertLessEqual(row['context_tokens'], case['budget_tokens'])
            if case['budget_tokens'] == 1:
                self.assertEqual(row['selected_turn_ids'], [])
                m = metric_row(row, dict(msg_retention=1, all_retained=True), Evidence(), case, 0)
                self.assertEqual(m['msg_retention'], 0)
                self.assertTrue(m['empty_material'])
        self.assertEqual((self.candidate, self.turns, self.question), before)
        self.assertEqual(self.candidate['budget_tokens'], 2048)

    def test_gamma_zero_matches_c_at_same_lambda_not_retuned_c(self):
        off = next(c for c in make_cases(parameters(), [300]) if c['condition'] == 'coverage_off')
        c = dict(off, strategy='C', condition='main')
        qrow = select_case(self.candidate, self.question, self.turns, self.counter, off)[0]
        crow = select_case(self.candidate, self.question, self.turns, self.counter, c)[0]
        for key in ('steps', 'selection_order', 'history_text'):
            self.assertEqual(qrow[key], crow[key])
        self.assertEqual(c['redundancy_weight'], .5)

    def test_baseline_exact_matching_and_mismatch_rejection(self):
        case = make_cases(parameters(), [2048])[3]
        row = select_case(self.candidate, self.question, self.turns, self.counter, case)[0]
        old = dict(row, context=row['history_text'], selection_config=row['config'], selection_config_id=row['config_id'])
        baseline = {baseline_key(row): old}
        self.assertTrue(check_baseline(row, baseline))
        baseline[baseline_key(row)] = dict(old, context='changed')
        with self.assertRaises(ValueError):
            check_baseline(row, baseline)

    def test_summary_requires_complete_paired_question_sets(self):
        cases = make_cases(parameters(), [1, 200, 2048])
        metrics = []
        for index in ('K0', 'K1'):
            for case in cases:
                row = select_case(dict(self.candidate, index=index), self.question, self.turns, self.counter, case)[0]
                metrics.append(metric_row(row, dict(msg_retention=1, all_retained=True), Evidence(), case, 0))
        summaries, pairs, pair_summary = summarize_metrics(metrics, ['toy'], cases)
        self.assertEqual((len(summaries), len(pairs), len(pair_summary)), (36, 6, 6))
        for bad in (metrics[:-1], metrics + metrics[:1]):
            with self.assertRaises(ValueError):
                summarize_metrics(bad, ['toy'], cases)
        modified = copy.deepcopy(metrics)
        next(r for r in modified if r['condition'] == 'coverage_off')['redundancy_weight'] = 1
        with self.assertRaisesRegex(ValueError, 'another weight'):
            summarize_metrics(modified, ['toy'], cases)


if __name__ == '__main__':
    unittest.main()
