"""Batch CLI contract: joins public questions and preserves output on failure."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
if __package__:
    from .test_selection import request, turn
else:
    from test_selection import request, turn


class CLITests(unittest.TestCase):
    def prepare(self, root):
        root=Path(root);ts=[turn(0,'old rent'),turn(1,'new rent')]
        row=request(ts);row.pop('question')
        (root/'turns').mkdir()
        (root/'turns/toy.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in ts),encoding='utf-8')
        (root/'questions.jsonl').write_text(json.dumps({'question_id':'toy','question':'old new rent','stage':'dev'})+'\n',encoding='utf-8')
        (root/'input.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
        return row
    def run_cli(self,root,*extra):
        return subprocess.run([sys.executable,str(Path(__file__).with_name('run_selection.py')),
             '--input',str(Path(root)/'input.jsonl'),'--questions',str(Path(root)/'questions.jsonl'),
             '--turns-dir',str(Path(root)/'turns'),'--output',str(Path(root)/'output.jsonl'),
             '--tokenizer','demo:characters',*extra],capture_output=True,text=True)
    def test_batch_all_methods_and_question_join(self):
        with tempfile.TemporaryDirectory() as root:
            self.prepare(root);p=self.run_cli(root)
            self.assertEqual(p.returncode,0,p.stderr)
            rows=[json.loads(x) for x in (Path(root)/'output.jsonl').read_text().splitlines()]
            self.assertEqual([r['strategy'] for r in rows],['R','MMR','C','Q','FL'])
            self.assertEqual(len({r['config_id'] for r in rows}),5)
    def test_failure_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as root:
            row=self.prepare(root);row['answer']='secret'
            (Path(root)/'input.jsonl').write_text(json.dumps(row)+'\n')
            out=Path(root)/'output.jsonl';out.write_text('prior output')
            self.assertNotEqual(self.run_cli(root).returncode,0)
            self.assertEqual(out.read_text(),'prior output')
    def test_duplicate_batch_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            row=self.prepare(root)
            (Path(root)/'input.jsonl').write_text((json.dumps(row)+'\n')*2)
            self.assertNotEqual(self.run_cli(root).returncode,0)
            self.assertFalse((Path(root)/'output.jsonl').exists())
    def test_module_entrypoint(self):
        repo=Path(__file__).resolve().parents[2]
        p=subprocess.run([sys.executable,'-m','D.D01.run_selection','--help'],cwd=repo,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        p=subprocess.run([sys.executable,'-c','from D.D01 import select; print(callable(select))'],cwd=repo,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('True',p.stdout)
    def test_tokenizer_mismatch_not_silently_overridden(self):
        with tempfile.TemporaryDirectory() as root:
            row=self.prepare(root);row['tokenizer']='actual-reader-model'
            (Path(root)/'input.jsonl').write_text(json.dumps(row)+'\n')
            self.assertNotEqual(self.run_cli(root).returncode,0)


if __name__=='__main__':unittest.main(verbosity=2)
