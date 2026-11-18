"""Offline upload integrity and mocked Slurm sequencing; never contacts a server."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from D.D06.prepare import ROOT

PACKAGE = ROOT / 'D/D06/upload/d06-dev34-server-v1'


class ServerPackageTests(unittest.TestCase):
    @unittest.skipUnless(PACKAGE.with_suffix('.tar.gz').exists(), 'Generate the optional local server upload package first')
    def test_archive_inventory_and_all_inputs(self):
        with tarfile.open(PACKAGE.with_suffix('.tar.gz')) as archive:
            members = {m.name: m for m in archive.getmembers() if m.isfile()}
            manifest = archive.extractfile(members[PACKAGE.name + '/SHA256SUMS']).read().decode()
            for line in manifest.splitlines():
                expected, name = line.split('  ', 1)
                data = archive.extractfile(members[PACKAGE.name + '/' + name]).read()
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
                if name.endswith('.py'):
                    ast.parse(data)
            self.assertFalse(any('safetensors' in name or '/.git/' in name or '/hf_cache/' in name
                                 for name in members))
        result = subprocess.run([sys.executable, 'E/E03/run_generation.py', '--input',
                                 'inputs/reader_inputs.jsonl', '--schema-only'],
                                cwd=PACKAGE, text=True, capture_output=True, check=True)
        self.assertIn('1156 records', result.stdout)

    def test_shell_syntax(self):
        for path in (ROOT / 'D/D06/server').glob('*.sh'):
            subprocess.run(['bash', '-n', str(path)], check=True, capture_output=True)

    def test_resume_jobs_are_serial_and_share_smoke_node(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            shutil.copytree(ROOT / 'D/D06/server', temp / 'server')
            (temp / 'payload').write_bytes(b'test')
            (temp / 'SHA256SUMS').write_text(hashlib.sha256(b'test').hexdigest() + '  payload\n')
            run = temp / 'runs/dev34-grid-v1'
            run.mkdir(parents=True)
            (run / 'summary.json').write_text(json.dumps(dict(expected=1156, recorded=2, missing=1154,
                statuses={'technical_failure': 0})))
            (run / 'runtime.jsonl').write_text(json.dumps({'host': 'TC2N01'}) + '\n')
            fake = temp / 'bin'
            fake.mkdir()
            stubs = {'module': '#!/bin/bash\nexit 0\n', 'conda': '#!/bin/bash\nexit 0\n',
                     'squeue': '#!/bin/bash\nexit 0\n',
                     'sbatch': '#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n'
                               'p=Path(os.environ["D06_TEST_SUBMISSIONS"])\n'
                               'n=len(p.read_text().splitlines()) if p.exists() else 0\n'
                               'with p.open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                               'print(1001+n)\n'}
            for name, content in stubs.items():
                path = fake / name
                path.write_text(content)
                path.chmod(0o755)
            log = temp / 'submissions.jsonl'
            env = dict(os.environ, PATH=str(fake) + os.pathsep + str(Path(sys.executable).parent)
                       + os.pathsep + os.environ['PATH'],
                       USER='d06-test', D06_TEST_SUBMISSIONS=str(log))
            subprocess.run(['bash', 'server/submit_remaining.sh'], cwd=temp, env=env,
                           text=True, capture_output=True, check=True)
            with log.open() as handle:
                submissions = [json.loads(line) for line in handle]
            self.assertEqual(len(submissions), 6)
            for i, args in enumerate(submissions):
                self.assertIn('--nodelist=TC2N01', args)
                self.assertEqual(args[-3:], ['--resume', '--stop-after', '200'])
                dependencies = [a for a in args if a.startswith('--dependency=')]
                self.assertEqual(dependencies, [] if i == 0 else [f'--dependency=afterok:{1000+i}'])
            (fake / 'squeue').write_text('#!/bin/bash\necho d06-reader\n')
            refused = subprocess.run(['bash', 'server/submit_remaining.sh'], cwd=temp, env=env,
                                     text=True, capture_output=True)
            self.assertNotEqual(refused.returncode, 0)
            with log.open() as handle:
                self.assertEqual(len(list(handle)), 6)


if __name__ == '__main__':
    unittest.main()
