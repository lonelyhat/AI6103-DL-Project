"""Delivery completeness checks, including detection of tampered examples."""
import copy
import unittest
if __package__:
    from .verify_delivery import ROOT, read, verify_rows, verify_toy
    from .selection import CharacterTokenizer
else:
    from verify_delivery import ROOT, read, verify_rows, verify_toy
    from selection import CharacterTokenizer


class DeliveryTests(unittest.TestCase):
    def test_stored_toy_full_replay(self):
        self.assertTrue(verify_toy()['full_algorithm_replay'])
    def test_tampering_and_missing_method_detected(self):
        e=ROOT/'examples';requests=read(e/'toy_candidates.jsonl');rows=read(e/'toy_selections.jsonl')
        bad=copy.deepcopy(rows);bad[0]['history_text']+='tampered'
        for changed in [bad,rows[:-1],rows+rows[:1]]:
            with self.assertRaises(ValueError):
                verify_rows(requests,changed,lambda q:read(e/'turns'/(q+'.jsonl')),CharacterTokenizer())


if __name__=='__main__':unittest.main(verbosity=2)
