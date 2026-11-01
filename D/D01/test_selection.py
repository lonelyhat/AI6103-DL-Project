"""Deterministic regression checks for budget, overlap, scoring and data contracts."""
import copy
import math
import unittest
if __package__:
    from .selection import CharacterTokenizer, Config, STRATEGIES, clues, render_context, select, similarities
else:
    from selection import CharacterTokenizer, Config, STRATEGIES, clues, render_context, select, similarities


def turn(i, text, reply='ok', date=None):
    date = date or f'2024-01-{i+1:02d}T12:00'
    prefix = f'toy-s{i:03d}'
    return {'turn_id': prefix+'-t000', 'session_index': i, 'session_date': date,
            'session_datetime': date, 'sort_key': [date, i, 0],
            'messages': [{'message_id': prefix+'-m000', 'role': 'user', 'content': text},
                         {'message_id': prefix+'-m001', 'role': 'assistant', 'content': reply}]}


def request(turns, scores=None, budget=10000, question='old new rent'):
    return {'question_id':'toy', 'stage':'dev', 'index':'K0', 'question':question,
            'budget_tokens':budget, 'config_version':'a01-v2',
            'candidates':[{'turn_id':t['turn_id'], 'rank':i+1, 'score':s}
                          for i,(t,s) in enumerate(zip(turns, scores if scores is not None else [1]*len(turns)))]}


class SelectionTests(unittest.TestCase):
    def setUp(self): self.tk=CharacterTokenizer()
    def run_method(self, ts, method='R', scores=None, budget=10000, config=None, question='old new rent'):
        return select(request(ts,scores,budget,question),ts,self.tk,method,config)
    def test_whole_round_skip_and_exact_budget(self):
        ts=[turn(0,'x'*1000),turn(1,'new rent')]
        b=self.tk.count(render_context(ts[1:]))
        for method in STRATEGIES:
            r=self.run_method(ts,method,budget=b)
            self.assertEqual(r['selected_turn_ids'],[ts[1]['turn_id']])
            self.assertEqual(r['context_tokens'],b)
            self.assertEqual(r['skipped'][0]['reason'],'over_budget')
            self.assertIn('assistant',r['history_text'])
    def test_one_character_below_boundary(self):
        ts=[turn(0,'rent')]; b=len(render_context(ts))
        for method in STRATEGIES:
            self.assertEqual(self.run_method(ts,method,budget=b-1)['selected_turn_ids'],[])
    def test_chronological_and_same_timestamp(self):
        ts=[turn(2,'late','ok','2025-01-01T00:00'),turn(1,'second','ok','2024-01-01T00:00'),turn(0,'first','ok','2024-01-01T00:00')]
        r=self.run_method(ts)
        self.assertEqual(r['selected_turn_ids'],[ts[2]['turn_id'],ts[1]['turn_id'],ts[0]['turn_id']])
        self.assertEqual(r['selection_order'],[t['turn_id'] for t in ts])
    def test_overlap_dedup_and_zero_marginal(self):
        first=turn(0,'a','shared')
        first['messages'][1]['role']='user'
        second=copy.deepcopy(first); second['turn_id']='toy-s000-t001'; second['sort_key'][2]=1
        second['messages']=[copy.deepcopy(first['messages'][1])]
        for method in STRATEGIES:
            r=self.run_method([first,second],method,config=Config(0,0))
            self.assertEqual(len(r['selected_message_ids']),2)
            self.assertEqual(r['history_text'].count('shared'),1)
            self.assertLessEqual(r['context_tokens'],10000)
    def test_mmr_prefers_different_content(self):
        ts=[turn(0,'alpha alpha','alpha'),turn(1,'alpha alpha','alpha'),turn(2,'beta beta','beta'),turn(3,'gamma','gamma')]
        r=self.run_method(ts,'MMR',[1,.99,.98,0],config=Config(2,0))
        self.assertEqual(r['selection_order'][:2],[ts[0]['turn_id'],ts[2]['turn_id']])
        self.assertNotIn(ts[1]['turn_id'],r['selected_turn_ids'])
    def test_cost_prefers_shorter(self):
        ts=[turn(0,'alpha '*100),turn(1,'beta')]
        r=self.run_method(ts,'C',config=Config(0,0))
        self.assertEqual(r['selection_order'][0],ts[1]['turn_id'])
    def test_q_rewards_new_clue(self):
        ts=[turn(0,'alpha'),turn(1,'bravo')]
        c=self.run_method(ts,'C',config=Config(0,2),question='bravo')
        q=self.run_method(ts,'Q',config=Config(0,2),question='bravo')
        self.assertEqual(c['selection_order'][0],ts[0]['turn_id'])
        self.assertEqual(q['selection_order'][0],ts[1]['turn_id'])
        self.assertEqual(q['steps'][0]['new_clues'],['bravo'])
    def test_gamma_zero_exact_ablation(self):
        ts=[turn(0,'old rent '*5),turn(1,'new rent'),turn(2,'irrelevant')]
        c=self.run_method(ts,'C',[4,3,1],config=Config(.3,0))
        q=self.run_method(ts,'Q',[4,3,1],config=Config(.3,0))
        self.assertEqual(c['selection_order'],q['selection_order'])
        self.assertEqual(c['steps'],q['steps'])
    def test_fl_gain_matches_objective(self):
        ts=[turn(0,'alpha','alpha'),turn(1,'alpha','alpha'),turn(2,'beta','beta')]
        result=self.run_method(ts,'FL')
        # Equal scores -> unit facility weights: F({alpha})=2, then gain(beta)=1.
        self.assertAlmostEqual(result['steps'][0]['facility_gain'],2)
        self.assertAlmostEqual(result['steps'][1]['facility_gain'],1)
        self.assertEqual(len(result['selected_turn_ids']),2)
        self.assertEqual(result['stop_reason'],'nonpositive_gain')
    def test_features_do_not_depend_on_index_or_labels(self):
        ts=[turn(0,'alpha'),turn(1,'bravo')]
        a=request(ts);b=copy.deepcopy(a);b['index']='K1'
        for method in STRATEGIES:
            ra=select(a,ts,self.tk,method);rb=select(b,ts,self.tk,method)
            self.assertEqual(ra['steps'],rb['steps'])
            self.assertEqual(ra['history_text'],rb['history_text'])
    def test_reproducible_and_no_mutation(self):
        ts=[turn(0,'alpha'),turn(1,'beta')];req=request(ts);before=copy.deepcopy((req,ts))
        for method in STRATEGIES:
            self.assertEqual(select(req,ts,self.tk,method),select(req,list(reversed(ts)),self.tk,method))
        self.assertEqual((req,ts),before)
    def test_empty_and_zero_budget(self):
        for method in STRATEGIES:
            for ts,b in [([],100),([turn(0,'a')],0)]:
                r=self.run_method(ts,method,budget=b)
                self.assertEqual(r['selected_turn_ids'],[])
                self.assertEqual(r['context_tokens'],0)
    def test_bad_candidates_and_labels_rejected(self):
        ts=[turn(0,'alpha')];base=request(ts)
        bad=[]
        for score in [None,float('nan'),float('inf'),True]:
            x=copy.deepcopy(base);x['candidates'][0]['score']=score;bad.append(x)
        x=copy.deepcopy(base);x['candidates']*=2;bad.append(x)
        x=copy.deepcopy(base);x['answer']='secret';bad.append(x)
        x=copy.deepcopy(base);x['candidates'][0]['official_corpus_id']='answer_secret';bad.append(x)
        x=copy.deepcopy(base);x['candidates'][0]['turn_id']='foreign-s000-t000';bad.append(x)
        x=copy.deepcopy(base);x['budget_tokens']=-1;bad.append(x)
        x=copy.deepcopy(base);x['tokenizer']='another';bad.append(x)
        for req in bad:
            with self.assertRaises(ValueError):select(req,ts,self.tk,'R')
    def test_message_conflict_and_label_rejected(self):
        ts=[turn(0,'a')];x=copy.deepcopy(ts);x[0]['messages'][0]['has_answer']=True
        with self.assertRaises(ValueError):self.run_method(x)
        first=turn(0,'a','b');first['messages'][1]['role']='user'
        second=copy.deepcopy(first);second['turn_id']='toy-s000-t001';second['sort_key'][2]=1
        second['messages']=[{'message_id':'toy-s000-m001','role':'user','content':'DIFFERENT'}]
        with self.assertRaises(ValueError):self.run_method([first,second])
    def test_negative_scores_normalized_finite(self):
        ts=[turn(0,'a'),turn(1,'b')]
        for method in STRATEGIES:
            r=self.run_method(ts,method,[-2,-3])
            self.assertEqual(r['steps'][0]['relevance'],1)
            self.assertTrue(all(math.isfinite(s['score']) for s in r['steps']))
    def test_lexical_rules_and_similarity(self):
        self.assertEqual(clues('How much is my rent in 2024?'),{'rent','2024'})
        s=similarities(['alpha alpha','alpha alpha','beta'])
        self.assertAlmostEqual(s[0][1],1);self.assertEqual(s[0][2],0)
    def test_extreme_finite_scores(self):
        ts=[turn(0,'alpha'),turn(1,'beta')]
        for method in STRATEGIES:
            r=self.run_method(ts,method,[1e308,-1e308])
            self.assertTrue(all(math.isfinite(p['score']) for p in r['steps']))
    def test_exact_counter_nonadditivity(self):
        class Counter:
            name='test:nonadditive'
            def count(self,text):return len(text)//3
        ts=[turn(0,'alpha'),turn(1,'beta')];req=request(ts)
        counter=Counter();req['budget_tokens']=counter.count(render_context(ts))
        for method in STRATEGIES:
            r=select(req,ts,counter,method,Config(0,0))
            self.assertEqual(r['context_tokens'],counter.count(r['history_text']))
            self.assertLessEqual(r['context_tokens'],req['budget_tokens'])
    def test_equivalent_numeric_config_identity(self):
        ts=[turn(0,'alpha')]
        a=self.run_method(ts,'Q',config=Config(1,1))
        b=self.run_method(ts,'Q',config=Config(1.0,1.0))
        self.assertEqual(a,b)
    def test_invalid_calendar_and_metadata(self):
        for date in ['2024-13-01T12:00', '2024-02-30T12:00']:
            with self.assertRaises(ValueError):self.run_method([turn(0,'a',date=date)])
        ts=[turn(0,'a')];ts[0]['session_index']=False
        with self.assertRaises(ValueError):self.run_method(ts)
        ts=[turn(0,'a')];ts[0]['messages'][0]='broken'
        with self.assertRaises(ValueError):self.run_method(ts)
        ts=[turn(0,'a')];req=request(ts);req['config_version']={'answer':'secret'}
        with self.assertRaises(ValueError):select(req,ts,self.tk,'R')
    def test_negative_marginal_cost(self):
        class Counter:
            name='test:nonmonotonic'
            def count(self,text):return {0:0,1:10,2:5}[text.count('Session Date:')]
        ts=[turn(0,'alpha'),turn(1,'beta')];req=request(ts,budget=10)
        for method in STRATEGIES:
            r=select(req,ts,Counter(),method,Config(0,0))
            self.assertEqual(r['context_tokens'],5)
            self.assertEqual(r['steps'][-1]['marginal_tokens'],-5)
            self.assertEqual(r['steps'][-1]['cost_denominator'],1)
    def test_invalid_weight(self):
        for x in [-1,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):Config(x,0)


if __name__=='__main__':unittest.main(verbosity=2)

