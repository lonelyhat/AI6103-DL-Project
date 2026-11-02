"""B03 public input validation and immutable run identity (no GPU imports)."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A01 = ROOT / 'A-数据线/A01/output'
B02 = ROOT / 'B-检索线/B02'
TOKENIZER = 'meta-llama/Llama-3.1-8B-Instruct'


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = module_at('b02_baseline', B02 / 'retrieve_k0.py')


def jl(path):
    return baseline.read_jsonl(Path(path))


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def load_inputs(a01=A01):
    from D.D01.selection import validate
    manifest = json.loads((a01 / 'dev_manifest.json').read_text())
    ids = manifest['dev_ids']
    answerable, abstention = manifest['dev_answerable_ids'], manifest['dev_abstention_ids']
    if len(ids) != 40 or len(set(ids)) != 40 or len(answerable) != 34 or len(abstention) != 6:
        raise ValueError('Expected the frozen 40-question A01 split (34 + 6)')
    if set(answerable) & set(abstention) or set(ids) != set(answerable) | set(abstention):
        raise ValueError('Inconsistent A01 split')
    questions = jl(a01 / 'public/dev_questions.jsonl')
    if len({q['question_id'] for q in questions}) != len(questions):
        raise ValueError('Duplicate public question')
    questions = {q['question_id']: q for q in questions}
    items = []
    for qid in ids:
        question = questions[qid]
        if set(question) != {'question_id', 'stage', 'question', 'question_date'}:
            raise ValueError(f'{qid}: unexpected public question fields')
        turns = jl(a01 / 'public/turns' / f'{qid}.jsonl')
        if len(turns) < 100:
            raise ValueError(f'{qid}: fewer than 100 available turns')
        validate(dict(question, index='K0', budget_tokens=2048, candidates=[]), turns)
        items.append((question, turns))
    return manifest, items


def settings(manifest, batch_size=64):
    return {'index': 'K0', 'config_version': manifest['config_version'], 'top_k': 100,
            'max_length': 512, 'batch_size': batch_size, 'dtype': 'float32',
            'projection_dim': 1024, 'pooling': 'attention-mask mean',
            'normalization': 'sklearn L2', 'query_prefix': '', 'score': 'NumPy dot product',
            'retrieval_text': 'first user message only', 'budget_tokens': 2048,
            'tokenizer': TOKENIZER}


def public_row(question, candidates, config):
    return {'question_id': question['question_id'], 'stage': 'dev', 'index': 'K0',
            'strategy': None, 'budget_tokens': config['budget_tokens'], 'tokenizer': TOKENIZER,
            'config_version': config['config_version'], 'candidates': candidates}
