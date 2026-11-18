import copy
import json
from pathlib import Path
import tempfile
import unittest

from D.D02.prepare_materials import read_jsonl, sha
from D.D06.prepare import ROOT, PUBLIC, e_module
from D.D06.finalize import JSONL_FIXES, verify_sources


class JsonlRecoveryTests(unittest.TestCase):
    def test_unicode_separators_do_not_split_json_records(self):
        exporter = e_module('prepare_inputs')
        batch = e_module('batch')
        sample = read_jsonl(ROOT / 'E/E03/inputs/dev5_k0_all_methods.jsonl')[0]
        sample = copy.deepcopy(sample)
        sample['context'] = 'a\u0085b\u2028c\u2029d'
        sample['history_sha256'] = batch.sha(sample['context'].encode())
        text = json.dumps(sample, ensure_ascii=False) + '\n'
        # Reproduce the previous bug while proving that physical JSONL is valid.
        self.assertGreater(len(text.splitlines()), 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'unicode.jsonl'
            path.write_text(text, encoding='utf-8')
            self.assertEqual(exporter.read_rows(path), [sample])
            self.assertEqual(batch.load_inputs(path), [batch.normalize(sample)])

    def test_all_real_development_turns_are_readable(self):
        exporter = e_module('prepare_inputs')
        candidates = read_jsonl(ROOT / 'B-检索线/B03/candidates/dev_K0.jsonl')
        for row in candidates:
            path = PUBLIC / 'turns' / (row['question_id'] + '.jsonl')
            self.assertEqual(exporter.read_rows(path), read_jsonl(path))

    def test_recovery_accepts_only_exact_exporter_fix(self):
        hashes = {name: pair[0] for name, pair in JSONL_FIXES.items()}
        plan = {'files_sha256': hashes}
        changes = verify_sources(plan)
        self.assertEqual(set(changes), set(JSONL_FIXES))
        plan['files_sha256']['E/E03/batch.py'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'changed'):
            verify_sources(plan)
        for name, pair in JSONL_FIXES.items():
            self.assertEqual(sha(ROOT / name), pair[1])


if __name__ == '__main__':
    unittest.main()
