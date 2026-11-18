import copy
import json
import unittest

from D.D02.prepare_materials import read_jsonl
from D.D06.prepare import ROOT
from D.D06.summarize import aggregate, choose_best, judge_module


class SummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((ROOT / 'D/D06/output/dev34-grid-v1/plan.json').read_text())
        cls.inputs = read_jsonl(ROOT / 'D/D06/output/dev34-grid-v1/reader_inputs.jsonl')
        cls.answers = read_jsonl(ROOT / 'D/D06/returned/dev34-grid-v1/runs/dev34-grid-v1/answers_for_f.jsonl')
        cls.scores = read_jsonl(ROOT / 'F/scores/d06_dev34_grid_v1.jsonl')
        cls.judge = judge_module()

    def test_actual_complete_grid_and_independent_winners(self):
        records, grid, paired, winners = aggregate(self.inputs, self.answers, self.scores, self.plan, self.judge)
        self.assertEqual((len(records), len(grid), len(paired), len(winners)), (1156, 34, 17, 5))
        self.assertEqual(sum(r['generation_status'] == 'truncated' for r in records), 7)
        self.assertTrue(all(r['questions'] == 34 for r in grid))
        for winner in winners:
            pool = [r for r in paired if r['strategy'] == winner['strategy']]
            self.assertEqual(winner['paired_correct'], max(r['paired_correct'] for r in pool))

    def test_ties_prefer_lower_lambda_then_gamma(self):
        options = [dict(redundancy_weight=l, coverage_weight=g, paired_correct=10)
                   for l, g in ((.5, 0), (0, 1), (0, .5))]
        self.assertEqual(choose_best(options), options[2])
        options.append(dict(redundancy_weight=1, coverage_weight=1, paired_correct=11))
        self.assertEqual(choose_best(options), options[-1])

    def test_stale_score_and_api_error_are_rejected(self):
        scores = copy.deepcopy(self.scores)
        scores[0]['answer_sha256'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            aggregate(self.inputs, self.answers, scores, self.plan, self.judge)
        scores[0] = dict(self.scores[0], status='api_error', label=None)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            aggregate(self.inputs, self.answers, scores, self.plan, self.judge)
        with self.assertRaises(ValueError):
            aggregate(self.inputs[:-1], self.answers, self.scores, self.plan, self.judge)


if __name__ == '__main__':
    unittest.main()
