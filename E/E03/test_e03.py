"""Offline fault-injection tests. Synthetic responses are never experiment results."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from batch import digest, load_inputs, normalize, reader, run_batch, run_lock
from export_for_f import export
from prepare_inputs import build

HERE = Path(__file__).resolve().parent


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'run'
        self.rows = load_inputs(HERE / 'inputs/dev5_k0_all_methods.jsonl')[:3]
        self.prepared = [{'record': r, 'prompt': 'SYNTHETIC TEST PROMPT', 'input_tokens': 1,
                          'context_tokens': r['context_tokens']} for r in self.rows]
        self.config = {'test_only': True, 'input_hashes': [r['input_record_sha256'] for r in self.rows]}
        self.generator = Mock(side_effect=lambda item: dict(reader.answer_fields('SYNTHETIC TEST ONLY', False),
                               output_tokens_including_stop=1, generation_seconds=0))

    def run_batch(self, **kwargs):
        return run_batch(self.rows, self.prepared, self.output, self.config, self.generator, **kwargs)

    def journal(self):
        return [json.loads(s) for s in (self.output/'attempts.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_real_25_inputs_and_rebuild(self):
        rows = load_inputs(HERE/'inputs/dev5_k0_all_methods.jsonl')
        self.assertEqual(len(rows), 25)
        self.assertEqual({r['strategy'] for r in rows}, {'R','MMR','C','Q','FL'})
        self.assertEqual(len({r['question_id'] for r in rows}), 5)
        manifest = json.loads((HERE/'inputs/preparation.json').read_text(encoding='utf-8'))
        from batch import sha
        for path, expected in manifest['source_sha256'].items():
            self.assertEqual(sha(Path(path).read_bytes()), expected)
        report = build([Path('E/E02/inputs/sources/d02_selections.jsonl')] +
            sorted(Path('E/E03/inputs/sources').glob('*_selections.jsonl')),
            Path('E/E02/inputs/sources/turns'), self.root/'rebuilt.jsonl')
        self.assertEqual(report['records'], 25)
        self.assertEqual((self.root/'rebuilt.jsonl').read_bytes(), (HERE/'inputs/dev5_k0_all_methods.jsonl').read_bytes())

    def test_resume_skips_completed_and_no_model_on_finished_batch(self):
        report = self.run_batch(stop_after=1)
        self.assertEqual(report['missing'], 2)
        before = (self.output/'attempts.jsonl').read_bytes()
        report = self.run_batch(resume=True)
        self.assertTrue(report['all_generated'])
        self.assertTrue((self.output/'attempts.jsonl').read_bytes().startswith(before))
        self.assertEqual(self.generator.call_count, 3)
        self.run_batch(resume=True)
        self.assertEqual(self.generator.call_count, 3)
        self.assertEqual(len(self.journal()), 3)

    def test_technical_failure_retried_with_history_preserved(self):
        success = reader.answer_fields('SYNTHETIC', False)
        self.generator.side_effect = [success, RuntimeError('simulated OOM')]
        with self.assertRaisesRegex(RuntimeError, 'simulated OOM'):
            self.run_batch()
        self.assertEqual([r['status'] for r in self.journal()], ['generated', 'technical_failure'])
        self.generator.side_effect = lambda item: success
        self.assertTrue(self.run_batch(resume=True)['all_generated'])
        self.assertEqual(len(self.journal()), 4)
        self.assertEqual(self.journal()[2]['attempt'], 2)
        destination = self.root/'f.jsonl'
        self.assertEqual(export(self.output, destination), 3)
        rows = [json.loads(l) for l in destination.read_text().splitlines()]
        self.assertEqual(rows[1]['attempt'], 2)
        self.assertEqual(len({r['record_id'] for r in rows}), 3)
        self.assertTrue(all(r['status'] == 'ok' for r in rows))

    def test_keyboard_interrupt_retains_completed_rows(self):
        self.generator.side_effect = [reader.answer_fields('SYNTHETIC', False), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.run_batch()
        self.assertEqual(len(self.journal()), 1)
        self.assertFalse((self.output/'.writer.lock').exists())
        self.generator.side_effect = lambda item: reader.answer_fields('SYNTHETIC', False)
        self.assertTrue(self.run_batch(resume=True)['all_generated'])

    def test_torn_final_write_backed_up_and_retried(self):
        self.run_batch(stop_after=1)
        fragment = b'{"unfinished":"\xe4\xb8'
        with (self.output/'attempts.jsonl').open('ab') as handle:
            handle.write(fragment)
        with self.assertRaisesRegex(ValueError, 'Partial journal'):
            export(self.output, self.root/'f.jsonl')
        self.assertTrue(self.run_batch(resume=True)['all_generated'])
        self.assertEqual(next(self.output.glob('attempts.partial-*.bin')).read_bytes(), fragment)
        self.assertEqual(len(self.journal()), 3)

    def test_complete_corrupt_line_not_silently_discarded(self):
        self.run_batch(stop_after=1)
        with (self.output/'attempts.jsonl').open('ab') as handle:
            handle.write(b'broken\n')
        with self.assertRaises(json.JSONDecodeError):
            self.run_batch(resume=True)
        self.assertTrue((self.output/'attempts.jsonl').read_bytes().endswith(b'broken\n'))

    def test_changed_config_and_existing_output_rejected(self):
        self.run_batch(stop_after=1)
        before = (self.output/'attempts.jsonl').read_bytes()
        self.config['max_new_tokens'] = 999
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.run_batch(resume=True)
        with self.assertRaises(FileExistsError):
            self.run_batch()
        self.assertEqual((self.output/'attempts.jsonl').read_bytes(), before)

    def test_duplicate_changed_history_and_config_identities(self):
        row = self.rows[0]
        path = self.root/'dupes.jsonl'
        path.write_text((json.dumps(row)+'\n')*2)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            load_inputs(path)
        changed = dict(row, context=row['context']+'tampered')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            normalize(changed)
        changed = copy.deepcopy(row)
        changed['selection_config']['redundancy_weight'] = 0.37
        with self.assertRaisesRegex(ValueError, 'config hash'):
            normalize(changed)
        changed['selection_config_id'] = digest(changed['selection_config'])
        self.assertNotEqual(normalize(changed)['record_id'], row['record_id'])
        self.assertNotEqual(normalize(dict(row,index='K1'))['record_id'], row['record_id'])
        self.assertNotIn('answer', normalize(dict(row, answer='GOLD MUST NOT LEAK')))

    def test_writer_lock_blocks_second_writer_and_export(self):
        self.run_batch(stop_after=1)
        with run_lock(self.output):
            with self.assertRaises(FileExistsError):
                self.run_batch(resume=True)
            with self.assertRaisesRegex(ValueError, 'Writer lock'):
                export(self.output, self.root/'f.jsonl')
            self.assertTrue((self.output/'.writer.lock').exists())

    def test_truncated_empty_are_visible_and_never_auto_retried(self):
        self.generator.side_effect = [reader.answer_fields('cut', True), reader.answer_fields('', False),
                                      reader.answer_fields('Final answer: SYNTHETIC', False)]
        report = self.run_batch()
        self.assertFalse(report['all_generated'])
        self.run_batch(resume=True)
        self.assertEqual(self.generator.call_count, 3)
        dest = self.root/'f.jsonl'
        export(self.output, dest)
        rows = [json.loads(l) for l in dest.read_text().splitlines()]
        self.assertEqual([r['status'] for r in rows], ['truncated','empty','ok'])
        self.assertEqual(rows[0]['hypothesis'], '')

    def test_partial_export_requires_explicit_flag_and_preserves_raw(self):
        self.run_batch(stop_after=1)
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            export(self.output, self.root/'f.jsonl')
        self.assertEqual(export(self.output,self.root/'partial.jsonl',True),1)
        row = json.loads((self.root/'partial.jsonl').read_text())
        self.assertEqual(row['raw_output'], 'SYNTHETIC TEST ONLY')
        self.assertEqual(row['reader_config_version'], 'e02-v2')
        self.assertTrue(row['needs_review'])
        self.assertIn('reader_config_id', row)

    def test_foreign_or_duplicate_journal_records_rejected(self):
        self.run_batch(stop_after=1)
        row = self.journal()[0]
        from batch import append
        append(self.output/'attempts.jsonl',row)
        with self.assertRaisesRegex(ValueError, 'nonsequential'):
            self.run_batch(resume=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
