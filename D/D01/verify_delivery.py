"""Reproduce D01 examples, recheck history integrity and run regression tests."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
if __package__:
    from .selection import CharacterTokenizer, Config, HFTokenizer, STRATEGIES, digest, render_context, select, validate
else:
    from selection import CharacterTokenizer, Config, HFTokenizer, STRATEGIES, digest, render_context, select, validate

ROOT = Path(__file__).resolve().parent


def read(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_rows(requests, rows, turns_for, counter, replay=False):
    expected = {(r['question_id'], r['index'], m) for r in requests for m in STRATEGIES}
    actual = [(r['question_id'], r['index'], r['strategy']) for r in rows]
    require(len(actual)==len(set(actual)) and set(actual)==expected, 'missing/duplicate question-index-strategy rows')
    by_key={(r['question_id'],r['index']):r for r in requests}
    props=json.loads((ROOT/'schemas/selection.schema.json').read_text())['properties']
    for row in rows:
        require(set(row)==set(props), 'selection schema fields mismatch')
        request=by_key[(row['question_id'],row['index'])]
        turns=turns_for(row['question_id']);records=validate(request,turns)
        candidates=sorted(request['candidates'],key=lambda c:(c['rank'],c['turn_id']))
        data=[records[c['turn_id']] for c in candidates]
        candidate_ids={c['turn_id'] for c in candidates}
        selected=row['selected_turn_ids'];skipped=row['skipped_turn_ids']
        require(len(selected)==len(set(selected)) and len(skipped)==len(set(skipped)), 'duplicate selected/skipped ID')
        require(set(selected).isdisjoint(skipped) and set(selected)|set(skipped)==candidate_ids, 'candidate partition mismatch')
        chronological=sorted((records[t] for t in selected),key=lambda t:(t['sort_key'],t['turn_id']))
        require(selected==[t['turn_id'] for t in chronological], 'selection chronology mismatch')
        require(row['history_text']==render_context(chronological), 'history differs from whole original messages')
        require(row['history_sha256']==hashlib.sha256(row['history_text'].encode()).hexdigest(), 'history hash mismatch')
        require(row['input_sha256']==digest({'request':request,'candidate_turns':data}), 'input hash mismatch')
        require(row['config_id']==digest(row['config']), 'configuration hash mismatch')
        require(counter.count(row['history_text'])==row['context_tokens']<=row['budget_tokens'], 'token count/budget mismatch')
        require(row['budget_tokens']==request['budget_tokens'], 'request/output budget mismatch')
        message_ids=list(dict.fromkeys(m['message_id'] for t in chronological for m in t['messages']))
        require(row['selected_message_ids']==message_ids, 'message deduplication mismatch')
        require(row['selection_order']==[s['turn_id'] for s in row['steps']] and
                set(row['selection_order'])==set(selected), 'step/selection mismatch')
        require(row['config']['tokenizer_fingerprint']==getattr(counter,'fingerprint',counter.name), 'tokenizer contents mismatch')
        if replay:
            replay_counter=copy.copy(counter)
            # Stored model path is a label; matching content fingerprint establishes identity.
            replay_counter.name=row['tokenizer']
            cfg=Config(row['config']['redundancy_weight'],row['config']['coverage_weight'])
            require(select(request,turns,replay_counter,row['strategy'],cfg)==row,'full replay mismatch')
    return {'rows':len(rows),'questions':len(requests),'all_within_budget':True,
            'histories_reconstructed':True,'hashes_verified':True,'full_algorithm_replay':replay,
            'min_context_tokens':min((r['context_tokens'] for r in rows),default=0),
            'max_context_tokens':max((r['context_tokens'] for r in rows),default=0)}


def verify_toy(root=ROOT):
    examples=Path(root)/'examples'
    request=read(examples/'toy_candidates.jsonl')
    rows=read(examples/'toy_selections.jsonl')
    result=verify_rows(request,rows,lambda q:read(examples/'turns'/(q+'.jsonl')),CharacterTokenizer(),True)
    require(rows==read(examples/'cli_selections.jsonl'),'API/CLI example outputs differ')
    result['cli_api_identical']=True
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tokenizer',help='optional local Qwen tokenizer for saved real-token examples')
    p.add_argument('--public-root',type=Path,default=ROOT.parents[1]/'A-数据线/A01/output/public')
    p.add_argument('--replay-public',action='store_true',help='also rerun selection for all saved public smoke cases')
    p.add_argument('--output',type=Path,default=ROOT/'examples/verification.json')
    args=p.parse_args()
    require(not args.replay_public or args.tokenizer is not None,'--replay-public requires --tokenizer')
    # Computed test count, not a manually entered assertion.
    suite=unittest.defaultTestLoader.discover(str(ROOT),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    require(result.wasSuccessful(),'regression tests failed')
    report={'implementation':'d01-v1','test_command':"python3 -m unittest discover -s D/D01 -p 'test_*.py' -v",
            'unit_tests_passed':result.testsRun,'toy':verify_toy(),
            'public_smoke':{'status':'not checked; pass --tokenizer for real-token verification'}}
    if args.tokenizer:
        examples=ROOT/'examples/qwen';tk=HFTokenizer(args.tokenizer)
        report['qwen_toy']=verify_rows(read(examples/'toy_candidates.jsonl'),read(examples/'toy_selections.jsonl'),
              lambda q:read(examples/'turns'/(q+'.jsonl')),tk,True)
        report['public_smoke']=verify_rows(read(examples/'public_smoke_candidates.jsonl'),read(examples/'public_smoke_selections.jsonl'),
              lambda q:read(args.public_root/'turns'/(q+'.jsonl')),tk,args.replay_public)
        report['public_smoke']['score_source']='synthetic lexical overlap; not B retrieval'
        report['tokenizer_fingerprint']=tk.fingerprint
    report['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob('*.py'))}
    report['schemas_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'schemas').glob('*.json'))}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
