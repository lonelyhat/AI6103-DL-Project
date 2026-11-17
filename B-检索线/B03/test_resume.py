"""Failure/recovery tests: partial work must survive without becoming a delivery."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import load_inputs, public_row, settings
from retrieve_dev import export, run_questions


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.items = load_inputs()
        cls.config = settings(cls.manifest)

    def result(self, q, turns):
        return public_row(q, [{'turn_id': t['turn_id'], 'rank': i + 1, 'score': 1.0 - i/1000}
                              for i, t in enumerate(turns[:100])], self.config), 1.0

    def test_interruption_resume_and_complete_skip(self):
        with tempfile.TemporaryDirectory() as d:
            checkpoint = Path(d) / 'checkpoint.json'
            first, second = self.items[:2]
            def interrupted(q, turns):
                if q['question_id'] == second[0]['question_id']:
                    raise RuntimeError('simulated process failure')
                return self.result(q, turns)
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                run_questions(self.items[:2], self.config, 'same-run', checkpoint, False, interrupted)
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(set(saved['completed']), {first[0]['question_id']})
            calls = []
            def resumed(q, turns):
                calls.append(q['question_id'])
                return self.result(q, turns)
            recovered = run_questions(self.items[:2], self.config, 'same-run', checkpoint, True, resumed)
            self.assertEqual(calls, [second[0]['question_id']])
            self.assertEqual(recovered['completed'][first[0]['question_id']], saved['completed'][first[0]['question_id']])
            run_questions(self.items[:2], self.config, 'same-run', checkpoint, True,
                          lambda *_: self.fail('Completed question was unexpectedly recomputed'))

    def test_changed_fingerprint_rejected_without_modifying_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            checkpoint = Path(d) / 'checkpoint.json'
            run_questions(self.items[:1], self.config, 'old-run', checkpoint, False, self.result)
            before = checkpoint.read_bytes()
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                run_questions(self.items[:1], self.config, 'changed-model-or-input', checkpoint, True, self.result)
            self.assertEqual(checkpoint.read_bytes(), before)

    def test_incomplete_state_cannot_replace_delivery(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)
            target = output / 'candidates/dev_all_K0.jsonl'
            target.parent.mkdir()
            target.write_text('existing delivery')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                export({'completed': {}}, self.manifest, output)
            self.assertEqual(target.read_text(), 'existing delivery')


if __name__ == '__main__':
    unittest.main()
