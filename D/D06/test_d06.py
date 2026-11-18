import json
from pathlib import Path
import tempfile
import shutil
import unittest

from D.D01.selection import Config
from D.D02.prepare_materials import sha
from D.D06.prepare import ROOT, grid, paired_inputs
from D.D06.check_reader import check


class SweepTests(unittest.TestCase):
    def test_fair_grid_includes_zero_and_independent_c_q(self):
        settings = grid([1, 0, .5, .5], [1, 0, .5])
        self.assertEqual(len(settings), 17)
        c = {s['redundancy_weight'] for s in settings if s['strategy'] == 'C'}
        q = {(s['redundancy_weight'], s['coverage_weight']) for s in settings if s['strategy'] == 'Q'}
        self.assertEqual(q, {(l, g) for l in c for g in (0, .5, 1)})
        for bad in (-1, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                grid([bad], [0])

    def test_paired_real_development_inputs(self):
        k0 = ROOT / 'B-检索线/B03/candidates/dev_K0.jsonl'
        k1 = ROOT / 'B-检索线/B05/candidates/dev_K1.jsonl'
        result = paired_inputs(k0, k1, ['2318644b'])
        self.assertEqual(len(result['K0']), 34)
        self.assertEqual(set(result['K0']), set(result['K1']))
        with self.assertRaises(ValueError):
            paired_inputs(k0, k0, ['2318644b'])
        with self.assertRaises(ValueError):
            paired_inputs(k0, k1, ['unknown'])

    def test_existing_e_result_and_duplicate_rejection(self):
        run = ROOT / 'E/E03/results/dev5-k0-v1'
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory)
            (handoff / 'reader_inputs.jsonl').write_bytes((run / 'inputs.jsonl').read_bytes())
            (handoff / 'handoff.json').write_text(json.dumps({'input_sha256': sha(handoff / 'reader_inputs.jsonl')}))
            report = check(handoff, [run])
            self.assertEqual(report['recorded'], 25)
            self.assertEqual(report['status'], 'reader_complete_waiting_for_scores')
            self.assertFalse(report['parameters_selected'])
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                check(handoff, [run, run])
            with (handoff / 'reader_inputs.jsonl').open('a') as f:
                f.write('\n')
            with self.assertRaisesRegex(ValueError, 'changed'):
                check(handoff, [run])

    def test_recorded_truncation_is_complete_and_preserved(self):
        original = ROOT / 'E/E03/results/dev5-k0-v1'
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory)
            run = handoff / 'run'
            shutil.copytree(original, run)
            (handoff / 'reader_inputs.jsonl').write_bytes((run / 'inputs.jsonl').read_bytes())
            (handoff / 'handoff.json').write_text(json.dumps({'input_sha256': sha(handoff / 'reader_inputs.jsonl')}))
            for name in ('attempts.jsonl', 'results.jsonl'):
                with (run / name).open() as f:
                    rows = [json.loads(line) for line in f]
                rows[0].update(status='truncated', hit_output_limit=True)
                (run / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
            report = check(handoff, [run])
            self.assertEqual(report['status'], 'reader_complete_waiting_for_scores')
            self.assertEqual(report['truncated_retained_for_scoring'], 1)
            self.assertEqual(report['recorded'], 25)
            self.assertFalse(report['parameters_selected'])


if __name__ == '__main__':
    unittest.main()
