"""Integration and corruption checks for D03-D05 real-batch adapters and replay."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from D.D01.selection import CharacterTokenizer, Config, render_context
from D.D01.test_selection import turn, request
from D.selection_batch import prepare_results
from D.verify_selection import verify_record


class Counter(CharacterTokenizer):
    fingerprint = "test-character-counter"


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.counter = Counter()
        self.turns = [turn(0, "alpha "*15), turn(1, "bravo rent"), turn(2, "charlie")]
        self.input = request(self.turns, [3, 2, 1], budget=2048, question="bravo rent")
        self.public = {k: self.input[k] for k in ("question_id", "stage", "question")}
        self.candidate = {k: v for k, v in self.input.items() if k != "question"}
        self.settings = dict(question_ids=["toy"], strategies=["MMR", "C", "Q", "FL"],
                             stage="dev", index="K0", budget_tokens=2048,
                             redundancy_weight=.5, coverage_weight=.5)

    def batch(self, **settings):
        return prepare_results([self.candidate], [self.public], lambda _: self.turns,
                               self.counter, dict(self.settings, **settings))

    def check_record(self, row):
        weights = Config(0 if row["strategy"] == "FL" else .5,
                         .5 if row["strategy"] == "Q" else 0)
        verify_record(row, self.input, self.turns, self.counter, weights)

    def test_all_methods_replay_and_input_immutability(self):
        before = copy.deepcopy((self.candidate, self.turns, self.public))
        rows = self.batch()
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.check_record(row)
            self.assertEqual(row["question"], "bravo rent")
            self.assertIn("retrieval_score", row["steps"][0])
        self.assertEqual((self.candidate, self.turns, self.public), before)

    def test_gamma_zero_is_cost_ablation(self):
        c, q = self.batch(strategies=["C", "Q"], coverage_weight=0)
        self.assertEqual(c["selection_order"], q["selection_order"])
        self.assertEqual(c["steps"], q["steps"])
        self.assertEqual(c["history_text"], q["history_text"])

    def test_missing_duplicate_foreign_or_labelled_inputs_rejected(self):
        for rows in ([], [self.candidate, self.candidate],
                     [dict(self.candidate, question_id="foreign")],
                     [dict(self.candidate, answer="secret")],
                     [dict(self.candidate, strategy="R")],
                     [dict(self.candidate, config_version="a01-v1")],
                     [dict(self.candidate, budget_tokens=1024)]):
            with self.assertRaises(ValueError):
                prepare_results(rows, [self.public], lambda _: self.turns,
                                self.counter, self.settings)

    def test_conflicting_public_metadata_rejected(self):
        with self.assertRaises(ValueError):
            prepare_results([dict(self.candidate, question="conflict")], [self.public],
                            lambda _: self.turns, self.counter, self.settings)

    def test_invalid_parameters_and_duplicate_methods(self):
        for settings in (dict(redundancy_weight=float("nan")), dict(coverage_weight=-1),
                         dict(strategies=["Q", "Q"]), dict(question_ids=["toy", "toy"])):
            with self.assertRaises(ValueError):
                self.batch(**settings)

    def test_replay_detects_score_cost_history_and_selection_tampering(self):
        for strategy in self.settings["strategies"]:
            original = self.batch(strategies=[strategy])[0]
            for field, replacement in (("score", 123), ("redundancy", 42),
                                       ("cost_denominator", 999), ("retrieval_score", -99)):
                row = copy.deepcopy(original)
                row["steps"][0][field] = replacement
                with self.assertRaises(ValueError):
                    self.check_record(row)
            row = copy.deepcopy(original)
            row["selection_order"] = []
            with self.assertRaises(ValueError):
                self.check_record(row)
            row = copy.deepcopy(original)
            row["history_text"] += "extra"
            with self.assertRaises(ValueError):
                self.check_record(row)

    def test_replay_empty_and_oversize_stop(self):
        self.turns = [turn(0, "x"*3000)]
        self.input = request(self.turns, [1], budget=2048, question="bravo rent")
        self.candidate = {k: v for k, v in self.input.items() if k != "question"}
        for row in self.batch():
            self.check_record(row)
            self.assertEqual(row["stop_reason"], "no_candidate_fits")
            self.assertEqual(row["status"], "empty_material")

    def test_replay_zero_and_negative_marginal_cost(self):
        class Nonmonotone(Counter):
            def count(self, text):
                if not text:
                    return 0
                return 10 if text.count("Session Content:") == 1 else 8
        self.counter = Nonmonotone()
        self.turns = [turn(0, "alpha"), turn(1, "bravo"), turn(2, "charlie")]
        self.input = request(self.turns, [1, 1, 1], budget=2048, question="bravo rent")
        self.candidate = {k: v for k, v in self.input.items() if k != "question"}
        for row in self.batch():
            self.check_record(row)
            self.assertTrue(any(s["marginal_tokens"] <= 0 for s in row["steps"][1:]))
            self.assertTrue(all(s["cost_denominator"] >= 1 for s in row["steps"]))

    def test_replay_overlap_preserves_message_union(self):
        first = turn(0, "alpha", "shared")
        first["messages"][1]["role"] = "user"
        second = copy.deepcopy(first)
        second["turn_id"] = "toy-s000-t001"
        second["sort_key"][2] = 1
        second["messages"] = [copy.deepcopy(first["messages"][1]),
                              dict(message_id="toy-s000-m002", role="assistant", content="bravo")]
        self.turns = [first, second]
        self.input = request(self.turns, [1, 1], budget=2048, question="bravo rent")
        self.candidate = {k: v for k, v in self.input.items() if k != "question"}
        for row in self.batch():
            self.check_record(row)
            self.assertLessEqual(row["history_text"].count("shared"), 1)

    def test_bundle_detects_saved_text_and_source_corruption(self):
        from D.D02.prepare_materials import sha, write_bundle
        from D.verify_selection import verify_bundle
        rows = self.batch()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            public = root/"public"
            (public/"turns").mkdir(parents=True)
            candidate = root/"candidates.jsonl"
            candidate.write_text(json.dumps(self.candidate)+"\n")
            (public/"dev_questions.jsonl").write_text(json.dumps(self.public)+"\n")
            turns = public/"turns/toy.jsonl"
            turns.write_text("".join(json.dumps(t)+"\n" for t in self.turns))
            source = root/"source.py"
            source.write_text("# source version 1")
            manifest = {
                "config_version": "d03-d05-v1", "config": self.settings,
                "tokenizer_label": self.counter.name, "tokenizer_fingerprint": self.counter.fingerprint,
                "candidate_file": str(candidate), "public_root": str(public),
                "input_sha256": {str(p): sha(p) for p in [candidate, public/"dev_questions.jsonl", turns]},
                "source_sha256": {str(source): sha(source)},
                "n_records": 4, "n_questions": 1,
                "records": [{k: r[k] for k in ("question_id", "strategy", "context_tokens",
                                               "history_file", "history_sha256")} for r in rows],
            }
            output = root/"output"
            write_bundle(output, rows, manifest)
            self.assertTrue(verify_bundle(output, self.counter)["all_ready_for_reader"])
            material = output/rows[0]["history_file"]
            original = material.read_bytes()
            material.write_bytes(original+b"tampered")
            with self.assertRaisesRegex(ValueError, "saved text"):
                verify_bundle(output, self.counter)
            material.write_bytes(original)
            source.write_text("# changed source")
            with self.assertRaisesRegex(ValueError, "changed source_sha256"):
                verify_bundle(output, self.counter)


if __name__ == "__main__":
    unittest.main()
