"""CPU tests for the shared runner: recovery, fingerprint refusal, export gating, K1 text."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kretrieve import export, k1_text, load_items, public_row, question_set, run_questions, settings


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = question_set('formal')
        cls.items = load_items(cls.spec)[:2]
        cls.config = settings(cls.spec, 'K0')

    def result(self, q, turns):
        cands = [{'turn_id': t['turn_id'], 'rank': i + 1, 'score': 1.0 - i / 1000} for i, t in enumerate(turns[:100])]
        return public_row(q, cands, self.config), {'total_s': 1.0}

    def test_interruption_resume_and_complete_skip(self):
        with tempfile.TemporaryDirectory() as d:
            ck = Path(d) / 'checkpoint.json'
            first, second = self.items

            def interrupted(q, turns):
                if q['question_id'] == second[0]['question_id']:
                    raise RuntimeError('simulated failure')
                return self.result(q, turns)
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                run_questions(self.items, self.config, 'run', ck, False, interrupted)
            self.assertEqual(set(json.loads(ck.read_text())['completed']), {first[0]['question_id']})
            calls = []
            run_questions(self.items, self.config, 'run', ck, True,
                          lambda q, t: (calls.append(q['question_id']), self.result(q, t))[1])
            self.assertEqual(calls, [second[0]['question_id']])
            run_questions(self.items, self.config, 'run', ck, True, lambda *_: self.fail('recomputed'))

    def test_fingerprint_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as d:
            ck = Path(d) / 'checkpoint.json'
            run_questions(self.items[:1], self.config, 'old', ck, False, self.result)
            before = ck.read_bytes()
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                run_questions(self.items[:1], self.config, 'new', ck, True, self.result)
            self.assertEqual(ck.read_bytes(), before)

    def test_incomplete_export_refused(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'candidates/formal_K0.jsonl'
            target.parent.mkdir()
            target.write_text('existing delivery')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                export({'completed': {}}, self.spec, 'K0', Path(d))
            self.assertEqual(target.read_text(), 'existing delivery')

    def test_k1_text(self):
        self.assertEqual(k1_text(['A.', 'B.'], 'hi'), 'A. B. hi')
        self.assertEqual(k1_text([], 'hi'), 'hi')


if __name__ == '__main__':
    unittest.main()
