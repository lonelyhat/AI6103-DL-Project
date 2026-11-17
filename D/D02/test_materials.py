"""D02 acceptance cases, intentionally not executed before B02 delivery."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
if __package__:
    from .materials import select_ranked
    from .prepare_materials import prepare_batch, write_bundle
    from ..D01.selection import CharacterTokenizer, render_context
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from D.D02.materials import select_ranked
    from D.D02.prepare_materials import prepare_batch, write_bundle
    from D.D01.selection import CharacterTokenizer, render_context


def turn(i, text, date=None):
    date=date or f'2024-01-{i+1:02d}T12:00';prefix=f'toy-s{i:03d}'
    return {'turn_id':prefix+'-t000','session_index':i,'session_date':date,
        'session_datetime':date,'sort_key':[date,i,0],
        'messages':[{'message_id':prefix+'-m000','role':'user','content':text},
                    {'message_id':prefix+'-m001','role':'assistant','content':'Noted.'}]}


def request(turns, budget=2048):
    return {'question_id':'toy','question':'old and new rent','question_date':'2026/11/01',
            'stage':'dev','index':'K0','strategy':None,'budget_tokens':budget,
            'config_version':'a01-v2','candidates':[{'turn_id':t['turn_id'],'rank':i+1,'score':1-i*.1}
                                                     for i,t in enumerate(turns)]}


class D02PendingTests(unittest.TestCase):
    def test_skip_oversize_and_continue_whole_round(self):
        ts=[turn(0,'x'*4000),turn(1,'short')];tk=CharacterTokenizer()
        budget=tk.count(render_context(ts[1:]))
        result=select_ranked(request(ts,budget),ts,tk)
        self.assertEqual(result['selected_turn_ids'],[ts[1]['turn_id']])
        self.assertEqual(result['candidate_trials'][0]['decision'],'skipped')
        self.assertTrue(result['candidate_trials'][0]['standalone_over_budget'])
        self.assertEqual(result['context_tokens'],budget)
        self.assertIn('Noted.',result['history_text'])
    def test_one_below_exact_boundary(self):
        ts=[turn(0,'rent')];budget=len(render_context(ts))-1
        result=select_ranked(request(ts,budget),ts,CharacterTokenizer())
        self.assertEqual(result['status'],'empty_material')
        self.assertEqual(result['selected_turn_ids'],[])
    def test_time_sort_not_turn_id(self):
        ts=[turn(0,'new','2025-01-01T00:00'),turn(1,'old','2024-01-01T00:00')]
        result=select_ranked(request(ts),ts,CharacterTokenizer())
        self.assertEqual(result['selection_order'],[ts[0]['turn_id'],ts[1]['turn_id']])
        self.assertEqual(result['selected_turn_ids'],[ts[1]['turn_id'],ts[0]['turn_id']])
    def test_identical_dates_original_position_tiebreak(self):
        ts=[turn(1,'second','2024-01-01T00:00'),turn(0,'first','2024-01-01T00:00')]
        result=select_ranked(request(ts),ts,CharacterTokenizer())
        self.assertEqual(result['selected_turn_ids'],[ts[1]['turn_id'],ts[0]['turn_id']])
    def test_overlapping_rounds_deduplicate_messages(self):
        a=turn(0,'first');a['messages'][1]['role']='user';a['messages'][1]['content']='shared'
        b=copy.deepcopy(a);b['turn_id']='toy-s000-t001';b['sort_key'][2]=1
        b['messages']=[copy.deepcopy(a['messages'][1]),{'message_id':'toy-s000-m002','role':'assistant','content':'last'}]
        ts=[a,b];result=select_ranked(request(ts),ts,CharacterTokenizer())
        self.assertEqual(result['history_text'].count('shared'),1)
        self.assertEqual(result['n_unique_messages'],3)
        self.assertEqual(result['n_duplicate_message_occurrences_removed'],1)
        self.assertEqual(result['candidate_trials'][1]['duplicate_message_ids_removed'],['toy-s000-m001'])
    def test_context_oversize_is_distinct_from_singleton_oversize(self):
        ts=[turn(0,'aaaaa'),turn(1,'bbbbb')];budget=len(render_context(ts[:1]))
        result=select_ranked(request(ts,budget),ts,CharacterTokenizer())
        trial=result['candidate_trials'][1]
        self.assertFalse(trial['standalone_over_budget'])
        self.assertEqual(trial['reason'],'over_budget')
    def test_rank_scan_never_revisits_skipped_candidates(self):
        ts=[turn(0,'large'),turn(1,'small'),turn(2,'later')]
        class Nonmonotonic:
            name='test:nonmonotonic'
            def count(self,text):
                if not text:return 0
                if 'later' in text:return 8
                if 'large' in text:return 20
                return 5
        result=select_ranked(request(ts,10),ts,Nonmonotonic())
        self.assertEqual(result['selection_order'],[ts[1]['turn_id'],ts[2]['turn_id']])
        self.assertEqual([x['visit'] for x in result['candidate_trials']],[1,2,3])
    def test_empty_candidates_exhausted_and_no_input_mutation(self):
        ts=[turn(0,'rent')];req=request(ts);before=copy.deepcopy((req,ts))
        select_ranked(req,ts,CharacterTokenizer());self.assertEqual((req,ts),before)
        req['candidates']=[]
        result=select_ranked(req,ts,CharacterTokenizer())
        self.assertEqual(result['stop_reason'],'empty_candidates')
        self.assertEqual(result['context_tokens'],0)
    def test_a01_version_and_tokenizer_must_match(self):
        ts=[turn(0,'rent')]
        for key,value in [('config_version','a01-v1'),('tokenizer','wrong-model'),('strategy','Q')]:
            req=request(ts);req[key]=value
            with self.assertRaises(ValueError):select_ranked(req,ts,CharacterTokenizer())
    def test_batch_question_join_and_missing_B02(self):
        ts=[turn(0,'rent')];row=request(ts);row.pop('question');row.pop('question_date')
        config={'question_ids':['toy'],'input_config_version':'a01-v2','stage':'dev','index':'K0','budget_tokens':2048}
        questions=[{'question_id':'toy','stage':'dev','question':'old and new rent','question_date':'2026/11/01'}]
        rows=prepare_batch([row],questions,lambda q:ts,CharacterTokenizer(),config)
        self.assertEqual(rows[0]['question'],'old and new rent')
        for candidate_rows in [[],[row,row]]:
            with self.assertRaises(ValueError):prepare_batch(candidate_rows,questions,lambda q:ts,CharacterTokenizer(),config)
    def test_bundle_does_not_overwrite_previous_batch(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'batch';target.mkdir()
            with self.assertRaises(FileExistsError):write_bundle(target,[],{})


if __name__=='__main__':unittest.main(verbosity=2)
