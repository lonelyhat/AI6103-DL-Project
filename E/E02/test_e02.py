"""Offline interface checks. Synthetic answers below are not experiment results."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_generation as reader
from export_for_f import convert, export
from prepare_inputs import build, read_rows, render_official_topk


class E02Tests(unittest.TestCase):
    def setUp(self):
        self.rows = reader.load_inputs(HERE / 'inputs/dev5.jsonl')

    def test_real_handoff_and_reproducible_preparation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            build(HERE / 'inputs/sources', output)
            for name in ('dev5.jsonl', 'dev5_budget.jsonl', 'dev5_topk.jsonl', 'topk_selections.jsonl'):
                self.assertEqual((output / name).read_bytes(), (HERE / 'inputs' / name).read_bytes())
        self.assertEqual(len(self.rows), 10)
        self.assertEqual({r['question_id'] for r in self.rows[:5]}, {r['question_id'] for r in self.rows[5:]})
        self.assertTrue(all(len(r['selected_turn_ids']) == 50 for r in self.rows[5:]))
        self.assertTrue(all(r.get('tokenizer_fingerprint') for r in self.rows[:5]))
        self.assertTrue(all('tokenizer_fingerprint' not in r for r in self.rows[5:]))

    def test_hash_tampering_rejected(self):
        row = copy.deepcopy(self.rows[0]); row['context'] += 'changed'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.jsonl'; path.write_text(json.dumps(row), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                reader.load_inputs(path)

    def test_reference_stable_date_sort_and_no_dedup(self):
        message = {'role': 'user', 'content': 'hello', 'message_id': 'shared'}
        turns = [{'turn_id': tid, 'session_date': date, 'messages': [message]}
                 for tid, date in [('later', '2024/02/01'), ('rank2', '2024/01/01'), ('rank3', '2024/01/01')]]
        text, ids = render_official_topk(turns)
        self.assertEqual(ids, ['rank2', 'rank3', 'later'])
        self.assertEqual(text.count('hello'), 3)
        self.assertIn('\n### Session 1:\nSession Date: 2024/01/01\nSession Content:\n\n[{"role": "user", "content": "hello"}]\n', text)
        self.assertNotIn('message_id', text)

    def test_labels_not_forwarded(self):
        row = dict(self.rows[0], answer='DO NOT FORWARD', has_answer=True)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.jsonl'; path.write_text(json.dumps(row), encoding='utf-8')
            result = reader.load_inputs(path)[0]
        self.assertNotIn('answer', result)
        self.assertNotIn('has_answer', result)

    def test_explicit_answer_preserves_multiline(self):
        self.assertEqual(reader.extract_answer('Reason.\n**Final answer:**\nFirst\nSecond'), ('First\nSecond', 'explicit_marker'))
        self.assertEqual(reader.extract_answer('Final answer: one\nFinal answer: two'), (None, 'needs_review'))
        self.assertEqual(reader.extract_answer('No explicit marker.'), (None, 'needs_review'))

    def test_export_statuses_and_raw_preservation(self):
        base = self.rows[0]
        for text, hit, expected in [('Final answer: synthetic', False, 'ok'), ('cut', True, 'truncated'), ('', False, 'empty')]:
            row = dict(base, **reader.answer_fields(text, hit))
            f = convert(row)
            self.assertEqual(f['status'], expected)
            self.assertEqual(f['raw_output'], text)
            if expected != 'ok': self.assertEqual(f['hypothesis'], '')
        row = dict(base, raw_output='', hypothesis='', status='technical_failure')
        self.assertEqual(convert(row)['status'], 'technical_failure')

    def test_export_rejects_false_success_and_duplicate(self):
        row = dict(self.rows[0], **reader.answer_fields('synthetic', False))
        with self.assertRaises(ValueError): convert(dict(row, raw_output=''))
        with tempfile.TemporaryDirectory() as temp:
            source, dest = Path(temp) / 'raw.jsonl', Path(temp) / 'f.jsonl'
            source.write_text((json.dumps(row) + '\n') * 2, encoding='utf-8')
            with self.assertRaises(ValueError): export(source, dest)
            with self.assertRaises(ValueError): export(source, source)

    def test_budget_capacity_and_fingerprint_fail_closed(self):
        class FakeTokenizer:
            # Deliberately synthetic character counter; never used for real inputs.
            def encode(self, text, **kw): return list(text)
            def apply_chat_template(self, messages, **kw): return messages[0]['content']
        row = dict(self.rows[0], context='abc', context_tokens=3, budget_tokens=3)
        row.pop('tokenizer_fingerprint', None)
        self.assertEqual(reader.prepare(row, FakeTokenizer(), 10000, 10)['context_tokens'], 3)
        for changes, capacity in [({'budget_tokens': 2}, 10000), ({'context_tokens': 4}, 10000), ({}, 1)]:
            with self.assertRaises(ValueError): reader.prepare(dict(row, **changes), FakeTokenizer(), capacity, 10)
        class Backend:
            def to_str(self): return 'wrong tokenizer'
        fake = FakeTokenizer(); fake.backend_tokenizer = Backend()
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            reader.prepare(dict(row, tokenizer_fingerprint='invalid'), fake, 10000, 10)


F_DIR = HERE.parents[1] / 'F/src/evaluation'
@unittest.skipUnless((F_DIR / 'judge.py').exists(), 'F branch is not present; apply handoff patch there to run F checks')
class FHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(F_DIR))
        import judge, join_f02
        cls.judge, cls.join = judge, join_f02

    def test_export_accepted_and_versions_separate(self):
        rows = reader.load_inputs(HERE / 'inputs/dev5.jsonl')
        budget = convert(dict(rows[0], **reader.answer_fields('Final answer: synthetic', False)))
        topk = convert(dict(rows[5], **reader.answer_fields('synthetic without marker', False)))
        self.judge.check_answer_fields([budget, topk])
        self.assertIn(budget['status'], self.judge.E_STATUS_OK)
        self.assertEqual(self.judge.choose_response(topk)[:2], ('synthetic without marker', 'raw_output'))
        self.assertNotEqual(self.judge.record_key(budget), self.judge.record_key(topk))
        self.assertNotEqual(self.judge.record_key(topk), self.judge.record_key(dict(topk, topk=20)))
        self.assertEqual(self.judge.DEFAULT_EVAL_FILE.is_file(), True)

    def test_real_d02_b02_metadata_join(self):
        s = read_rows(HERE / 'inputs/sources/d02_selections.jsonl')[0]
        c = read_rows(HERE / 'inputs/sources/b02_candidates.jsonl')[0]
        self.assertEqual(self.join.check_config_match(s, c, 'candidates'), [])
        row = reader.load_inputs(HERE / 'inputs/dev5_budget.jsonl')[0]
        self.assertEqual(self.join.make_key(s, self.join.SELECTION_KEY), self.join.make_key(row, self.join.SELECTION_KEY))
        self.assertTrue(self.join.check_config_match(s, dict(c, config_version='wrong'), 'candidates'))

    def test_mock_judge_to_real_evidence_join(self):
        # Exercise both CLIs with a fake API client, never a live Judge call.
        rows = reader.load_inputs(HERE / 'inputs/dev5.jsonl')
        exports = [convert(dict(row, **reader.answer_fields('Final answer: SYNTHETIC TEST ONLY', False))) for row in rows]
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            answers, scores = base / 'synthetic_answers.jsonl', base / 'synthetic_scores.jsonl'
            answers.write_text(''.join(json.dumps(r) + '\n' for r in exports), encoding='utf-8')
            args = types.SimpleNamespace(answers=str(answers), eval=str(self.judge.DEFAULT_EVAL_FILE),
                    questions=str(self.judge.DEFAULT_QUESTIONS_FILE), out=str(scores), model='offline-mock',
                    expected=None, limit=None, dry_run=False, summary_only=False)
            fake = types.SimpleNamespace(OpenAI=lambda **kw: object())
            result = dict(status='ok', judge_output='no', judge_model_returned='offline-mock',
                          judge_prompt_tokens=0, judge_output_tokens=0, judge_elapsed_s=0, judge_attempts=1)
            with patch.object(self.judge, 'parse_args', return_value=args), patch.object(self.judge, 'load_env_file'), \
                 patch.dict('os.environ', {'OPENAI_API_KEY': 'offline-test-not-a-key'}), \
                 patch.dict(sys.modules, {'openai': fake}), patch.object(self.judge, 'call_judge', return_value=result) as mock, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.judge.main()
            self.assertEqual(mock.call_count, 10)
            scored = read_rows(scores)
            selections = read_rows(HERE / 'inputs/sources/d02_selections.jsonl') + read_rows(HERE / 'inputs/topk_selections.jsonl')
            candidates = {r['question_id']: r for r in read_rows(HERE / 'inputs/sources/b02_candidates.jsonl')}
            table = {self.join.make_key(r, self.join.SELECTION_KEY): r for r in scored}
            evidence = self.join.Evidence()
            self.assertEqual(len(table), 10)
            for selection in selections:
                key = self.join.make_key(selection, self.join.SELECTION_KEY)
                row = self.join.build_row(selection, candidates[selection['question_id']], table[key], evidence, None)
                self.assertEqual(row['issues'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
