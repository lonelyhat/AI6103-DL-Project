"""Replay greedy choices independently of select(), and verify material provenance."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

from D.D01.selection import (
    Config, HFTokenizer, clues, digest, lexical, render_context, similarities, validate,
)
from D.D02.prepare_materials import read_jsonl, sha

REPO = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compare(actual, expected, label):
    if isinstance(expected, float):
        require(type(actual) in (int, float) and math.isfinite(actual)
                and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), label)
    else:
        require(actual == expected, label)


def verify_record(row, request, turns, counter, weights):
    """Recompute every feasible competitor and score; never calls the selector."""
    records = validate(request, turns)
    strategy = row["strategy"]
    require(strategy in ("MMR", "C", "Q", "FL"), "unsupported replay strategy")
    require(row["question_id"] == request["question_id"], "question identity")
    for field in ("question", "question_date", "stage", "index", "budget_tokens"):
        compare(row.get(field), request.get(field), field)
    require(row["tokenizer"] == counter.name, "reader tokenizer label")
    require(request.get("tokenizer") in (None, counter.name), "candidate tokenizer label")
    require(row["config"]["tokenizer_fingerprint"] == counter.fingerprint, "tokenizer content changed")
    require(row["config_id"] == digest(row["config"]), "config identity")
    require(row["config"]["redundancy_weight"] == weights.redundancy_weight, "redundancy weight")
    require(row["config"]["coverage_weight"] == weights.coverage_weight, "coverage weight")
    require(row["config"]["strategy"] == strategy, "strategy config")
    require(row["config"]["budget_tokens"] == request["budget_tokens"], "budget config")
    candidates = sorted(request["candidates"], key=lambda c: (c["rank"], c["turn_id"]))
    data = [records[c["turn_id"]] for c in candidates]
    require(row["input_sha256"] == digest({"request": request, "candidate_turns": data}), "request fingerprint")
    raw = [c["score"] for c in candidates]
    lo, hi = (min(raw), max(raw)) if raw else (0, 0)
    span = hi-lo
    rel = [((v-lo)/span if math.isfinite(span) else
            (v/2-lo/2)/(hi/2-lo/2)) if hi > lo else 1.0 for v in raw]
    texts = ["\n".join(m["content"] for m in t["messages"]) for t in data]
    sim = similarities(texts)
    query = clues(request["question"])
    hits = [query & set(lexical(text)) for text in texts]
    chosen, remaining, covered = [], list(range(len(data))), set()
    current = counter.count("")
    require(type(current) is int and current == 0, "empty tokenizer cost")
    step_index = 0
    def trial(i):
        total = counter.count(render_context([data[j] for j in chosen+[i]]))
        require(type(total) is int and total >= 0, "nonnegative tokenizer cost")
        delta = total-current
        denominator = max(1, delta)
        redundancy = max((sim[i][j] for j in chosen), default=0.0)
        new = hits[i]-covered
        coverage_gain = len(new)/max(1, len(query))
        # Direct objective subtraction is independent of selector's incremental cache.
        before = sum(rel[j]*max((sim[k][j] for k in chosen), default=0.0)
                     for j in range(len(data)))
        after = sum(rel[j]*max(sim[k][j] for k in chosen+[i]) for j in range(len(data)))
        gain = after-before
        numerator = rel[i]-weights.redundancy_weight*redundancy
        score = numerator if strategy == "MMR" else (
            gain/denominator if strategy == "FL" else
            (numerator+(weights.coverage_weight*coverage_gain if strategy == "Q" else 0))/denominator)
        return dict(turn_id=candidates[i]["turn_id"], rank=candidates[i]["rank"],
                    relevance=rel[i], redundancy=redundancy, new_clues=sorted(new),
                    coverage_gain=coverage_gain, facility_gain=gain, score=score,
                    marginal_tokens=delta, cost_denominator=denominator,
                    context_tokens=total, retrieval_score=candidates[i]["score"])
    stop = "exhausted"
    while remaining:
        feasible = [(i, trial(i)) for i in remaining]
        feasible = [(i, p) for i, p in feasible if p["context_tokens"] <= request["budget_tokens"]]
        if not feasible:
            stop = "no_candidate_fits"
            break
        # Use the incremental-equivalent gain for tie decisions to avoid cancellation
        # in the independent objective subtraction above. Validate that value separately.
        def decision_score(item):
            i, p = item
            if strategy != "FL":
                return p["score"]
            return sum(rel[j]*max(0, sim[i][j]-max(
                (sim[k][j] for k in chosen), default=0.0)) for j in range(len(data)))/p["cost_denominator"]
        best = max(feasible, key=lambda item: (decision_score(item), -candidates[item[0]]["rank"]))
        i, proposal = best
        if decision_score(best) <= 0:
            stop = "nonpositive_gain"
            break
        require(step_index < len(row["steps"]), "missing greedy selection step")
        saved = row["steps"][step_index]
        compare(saved["step"], step_index+1, "step number")
        for field, expected in proposal.items():
            compare(saved.get(field), expected, f'{strategy} step {step_index+1}: {field}')
        chosen.append(i)
        remaining.remove(i)
        covered.update(hits[i])
        current = proposal["context_tokens"]
        step_index += 1
    require(step_index == len(row["steps"]), "extra selection steps")
    compare(row["stop_reason"], stop, "stop reason")
    compare(row["selection_order"], [candidates[i]["turn_id"] for i in chosen], "selection order")
    chronological = sorted((data[i] for i in chosen), key=lambda t: (t["sort_key"], t["turn_id"]))
    history = render_context(chronological)
    compare(row["selected_turn_ids"], [t["turn_id"] for t in chronological], "chronological IDs")
    compare(row["selected_message_ids"], list(dict.fromkeys(
        m["message_id"] for t in chronological for m in t["messages"])), "message union")
    compare(row["history_text"], history, "whole original history")
    compare(row["context_tokens"], counter.count(history), "actual token budget")
    require(row["context_tokens"] <= request["budget_tokens"], "budget overflow")
    compare(row["history_sha256"], __import__("hashlib").sha256(history.encode()).hexdigest(), "history hash")
    compare(row["n_candidates"], len(candidates), "candidate count")
    compare(row["n_selected_turns"], len(chosen), "selected count")
    compare(row["status"], "ready_for_reader" if chosen else "empty_material", "material status")
    compare(row["budget_check"], {"passed": True}, "budget check")
    compare(row["question_clues"], sorted(query), "question clues")
    compare(row["covered_clues"], sorted(covered), "covered clues")
    require(len(row["skipped"]) == len(remaining), "skipped count")
    compare(row["skipped_turn_ids"], [candidates[i]["turn_id"] for i in remaining], "skipped IDs")
    for i, saved in zip(remaining, row["skipped"]):
        proposal = trial(i)
        compare(saved["turn_id"], candidates[i]["turn_id"], "skipped identity")
        compare(saved["proposed_context_tokens"], proposal["context_tokens"], "skipped cost")
        compare(saved["score"], proposal["score"], "skipped score")
        compare(saved["reason"], "over_budget" if proposal["context_tokens"] > request["budget_tokens"]
                else "nonpositive_gain", "skip reason")


def verify_bundle(output, counter):
    from D.selection_batch import VERSION, active_config
    output = Path(output).resolve()
    manifest = json.loads((output/"batch_manifest.json").read_text(encoding="utf-8"))
    require(manifest["config_version"] == VERSION, "batch version")
    settings = manifest["config"]
    require(counter.name == manifest["tokenizer_label"], "batch tokenizer label")
    require(counter.fingerprint == manifest["tokenizer_fingerprint"], "batch tokenizer fingerprint")
    def locate(path):
        return REPO/Path(path)
    for group in ("input_sha256", "source_sha256"):
        for path, expected in manifest[group].items():
            require(sha(locate(path)) == expected, f"changed {group}: {path}")
    candidates = read_jsonl(locate(manifest["candidate_file"]))
    require(len(candidates) == len(settings["question_ids"]), "candidate row count")
    by_id = {r["question_id"]: r for r in candidates}
    require(set(by_id) == set(settings["question_ids"]), "candidate IDs")
    root = locate(manifest["public_root"])
    questions = read_jsonl(root/"dev_questions.jsonl")
    public = {q["question_id"]: q for q in questions}
    require(len(public) == len(questions), "duplicate public questions")
    rows = read_jsonl(output/"selections.jsonl")
    expected_pairs = [(qid, strategy) for qid in settings["question_ids"] for strategy in settings["strategies"]]
    require([(r["question_id"], r["strategy"]) for r in rows] == expected_pairs, "missing/duplicate batch records")
    require(len(rows) == manifest["n_records"], "manifest record count")
    require(len(by_id) == manifest["n_questions"], "manifest question count")
    for row in rows:
        qid = row["question_id"]
        request = dict(by_id[qid])
        for key, value in public[qid].items():
            require(key not in request or request[key] == value, "public metadata conflict")
            request[key] = value
        require(request.get("budget_tokens") in (None, settings["budget_tokens"]), "input budget")
        require(request.get("strategy") is None and request.get("config_version") == "a01-v2", "input condition")
        require(request["index"] == settings["index"] and request["stage"] == settings["stage"], "stage/index")
        request["budget_tokens"] = settings["budget_tokens"]
        weights = active_config(row["strategy"], settings["redundancy_weight"], settings["coverage_weight"])
        verify_record(row, request, read_jsonl(root/"turns"/f"{qid}.jsonl"), counter, weights)
        expected_file = f'materials/{row["strategy"]}-{qid}.txt'
        require(row["history_file"] == expected_file, "material file identity")
        require((output/expected_file).read_bytes() == row["history_text"].encode(), "saved text differs")
    expected_records = [{"question_id": r["question_id"], "strategy": r["strategy"],
                         "context_tokens": r["context_tokens"], "history_file": r["history_file"],
                         "history_sha256": r["history_sha256"]} for r in rows]
    require(manifest["records"] == expected_records, "manifest summaries differ")
    return {
        "status": "passed", "scope": "input/source hashes, greedy replay, score components, "
        "stop/skip decisions, original messages, ordering, deduplication, tokenizer and budget",
        "n_questions": len(by_id), "n_records": len(rows),
        "all_ready_for_reader": all(r["status"] == "ready_for_reader" for r in rows),
        "answer_or_evidence_evaluation": "not_performed",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--tokenizer", help="override original source with identical tokenizer files")
    args = p.parse_args()
    manifest = json.loads((args.output_dir/"batch_manifest.json").read_text(encoding="utf-8"))
    counter = HFTokenizer(args.tokenizer or manifest["tokenizer_source"])
    counter.name = manifest["tokenizer_label"]
    report = verify_bundle(args.output_dir, counter)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_ready_for_reader"]:
        raise SystemExit("empty materials require review")


if __name__ == "__main__":
    main()
