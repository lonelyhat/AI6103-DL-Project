"""Generate reproducible toy runs; optionally smoke-test A01 public history."""
import argparse
import json
from pathlib import Path
if __package__:
    from .selection import CharacterTokenizer, Config, HFTokenizer, STRATEGIES, clues, lexical, render_context, select
else:
    from selection import CharacterTokenizer, Config, HFTokenizer, STRATEGIES, clues, lexical, render_context, select


def read(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8-sig').splitlines() if x.strip()]


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(x, ensure_ascii=False, allow_nan=False)+'\n' for x in rows), encoding='utf-8')


def toy_turn(i, text):
    date=f'2024-01-{i+1:02d}T12:00';prefix=f'toy-s{i:03d}'
    return {'turn_id':prefix+'-t000', 'session_index':i, 'session_date':date,
            'session_datetime':date, 'sort_key':[date,i,0],
            'messages':[{'message_id':prefix+'-m000','role':'user','content':text},
                        {'message_id':prefix+'-m001','role':'assistant','content':'Noted.'}]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',default=str(Path(__file__).parent/'examples'))
    p.add_argument('--tokenizer',default='demo:characters')
    p.add_argument('--public-root',help='A01 output/public; enables real-history smoke test with synthetic scores')
    args=p.parse_args();out=Path(args.output_dir)
    tk=CharacterTokenizer() if args.tokenizer=='demo:characters' else HFTokenizer(args.tokenizer)
    ts=[toy_turn(0,'New rent is 1500.'),toy_turn(1,'New rent is 1500.'),
        toy_turn(2,'Old rent was 2000.'),toy_turn(3,'Unrelated story. '*200)]
    budget=tk.count(render_context([ts[0],ts[2]]))
    req={'question_id':'toy','question':'What was old rent and new rent?', 'question_date':'2026/11/01',
         'stage':'dev','index':'K0','budget_tokens':budget,'tokenizer':tk.name,'config_version':'d01-toy-v1',
         'candidates':[{'turn_id':t['turn_id'],'rank':i+1,'score':s} for i,(t,s) in enumerate(zip(ts,[1,.99,.95,.1]))]}
    results=[select(req,ts,tk,m,Config(1,1)) for m in STRATEGIES]
    write(out/'toy_candidates.jsonl',[req]);write(out/'turns'/'toy.jsonl',ts);write(out/'toy_selections.jsonl',results)
    summary={'purpose':'D01 functional examples, not retrieval/QA effectiveness results',
             'tokenizer':tk.name,'toy':[{k:r[k] for k in ('strategy','selected_turn_ids','selection_order','context_tokens','budget_tokens','stop_reason')} for r in results]}
    if args.public_root:
        public=Path(args.public_root);requests=[];selections=[]
        for f in sorted((public/'turns').glob('*.jsonl')):
            qid=f.stem
            q=next(q for q in read(public/'dev_questions.jsonl') if q['question_id']==qid)
            turns=read(f);qc=clues(q['question'])
            scored=[(len(qc & set(lexical('\n'.join(m['content'] for m in t['messages']))))/max(1,len(qc)), t) for t in turns]
            scored.sort(key=lambda x:(-x[0],x[1]['turn_id']))
            row={**q,'index':'K0','strategy':None,'budget_tokens':2048,'tokenizer':tk.name,
                 'config_version':'d01-smoke-synthetic-overlap-v1',
                 'candidates':[{'turn_id':t['turn_id'],'rank':i+1,'score':s} for i,(s,t) in enumerate(scored[:100])]}
            requests.append(row)
            selections.extend(select(row,turns,tk,m) for m in STRATEGIES)
        write(out/'public_smoke_candidates.jsonl',requests);write(out/'public_smoke_selections.jsonl',selections)
        summary['public_smoke']={'score_source':'synthetic lexical question/original-round overlap; NOT B retrieval scores',
            'questions':len(requests),'records':len(selections),'all_within_budget':all(r['context_tokens']<=r['budget_tokens'] for r in selections),
            'rows':[{k:r[k] for k in ('question_id','strategy','context_tokens','budget_tokens','stop_reason')} for r in selections]}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
