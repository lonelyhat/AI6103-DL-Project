"""Reconcile the frozen C04 ledger, formal fact spot check and v2 index costs."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
LEDGER = ROOT / "C04运行账本/c04_fact_audit.json"
RETRIEVAL = ROOT / "B-检索线"
SAMPLE = HERE / "formal_v2_spotcheck.jsonl"
SUMMARY = HERE / "formal_v2_summary.json"
SEED = 42
SAMPLE_SIZE = 20


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_json(path):
    return json.loads(path.read_bytes())


def rows(path):
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def source_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def canonical_kind(value):
    if isinstance(value, list):
        if not value:
            return "empty_list"
        return "list_of_strings" if all(isinstance(x, str) for x in value) else "list_with_non_string"
    return "string" if isinstance(value, str) else type(value).__name__


def formal_inputs(plan):
    formal = plan["formal"]
    manifest = ROOT / formal["manifest"]
    public = ROOT / formal["public_root"]
    facts_path = ROOT / formal["fact_snapshot"]["path"]
    sources_path = RETRIEVAL / "B06/inputs/formal_fact_sources.jsonl"
    index_facts_path = RETRIEVAL / "B06/inputs/formal_facts_by_turn.jsonl"
    candidates = {index: ROOT / path for index, path in formal["candidates"].items()}
    for path in (manifest, public / "formal_questions.jsonl", facts_path, sources_path,
                 index_facts_path, *candidates.values()):
        relative = path.relative_to(ROOT).as_posix()
        require(source_hash(path) == plan["source_sha256"][relative], f"Frozen input changed: {relative}")
    question_ids = load_json(manifest)["formal_ids"]
    require(len(set(question_ids)) == len(question_ids) == formal["questions"], "Invalid formal manifest")

    user_messages = {}
    for qid in question_ids:
        path = public / "turns" / f"{qid}.jsonl"
        require(source_hash(path) == formal["turn_sha256"][qid], f"Changed dialog: {qid}")
        for turn in rows(path):
            for message in turn["messages"]:
                if message["role"] == "user":
                    key = (qid, turn["turn_id"], message["message_id"])
                    require(key not in user_messages, f"Repeated source: {key}")
                    user_messages[key] = message["content"]
    sources = {(r["question_id"], r["turn_id"]): r for r in rows(sources_path)}
    index_facts = {(r["question_id"], r["turn_id"]): r["facts"] for r in rows(index_facts_path)}
    counts = Counter(qid for qid, _ in sources)
    facts = load_json(facts_path)
    require(sources.keys() == index_facts.keys() and set(counts) == set(question_ids),
            "B06 source and index positions differ")
    require({r["fact_key"] for r in sources.values()} == set(facts), "B06 fact-key coverage differs")
    require(all((*position, r["source_message_id"]) in user_messages for position, r in sources.items()),
            "A B06 source does not map to an original user message")
    return facts, sources, user_messages, index_facts, candidates, counts, manifest, index_facts_path


def audit_extraction(ledger, facts, sources, user_messages):
    groups = {"extracted": ledger["extracted_turns"], "reused": ledger["reused_turns"]}
    by_key = {r["cache_key"]: r for group in groups.values() for r in group}
    require(len(by_key) == sum(map(len, groups.values())) and by_key.keys() == facts.keys(),
            "C04 ledger does not cover exactly the frozen keys")
    texts = {}
    for key, record in by_key.items():
        position = (record["question_id"], record["turn_id"])
        source = sources[position]
        require(source["fact_key"] == key and canonical_kind(facts[key]) == record["value_kind"],
                f"Fact source or type mismatch: {key}")
        texts[key] = user_messages[(*position, source["source_message_id"])]

    extracted = groups["extracted"]
    for record in extracted:
        key = record["cache_key"]
        require(record["source_text"] == texts[key] and record["facts"] == facts[key],
                f"Extracted fact or original user text differs: {key}")
    failures = {r["cache_key"]: r for r in ledger["failures"]}
    retried = {r["cache_key"]: r for r in extracted if r["attempts"] > 1}
    require(failures.keys() == retried.keys() and all(
        r["attempts"] == retried[key]["attempts"] and r["finalized"] == retried[key]["finalized"]
        for key, r in failures.items()
    ), "Failure and retry receipts disagree")

    usage = {
        "recorded_turn_seconds": round(math.fsum(r["elapsed_s"] for r in extracted), 2),
        "recorded_input_tokens": sum(r["usage"]["n_input_tokens"] for r in extracted),
        "recorded_output_tokens": sum(r["usage"]["n_output_tokens"] for r in extracted),
    }
    supplied = ledger["summary"]["extracted"]
    require(list(usage.values()) == [supplied[k] for k in (
        "elapsed_s_total", "input_tokens_total", "output_tokens_total"
    )], "Per-turn usage disagrees with the C04 totals")
    stats = {
        "model": ledger["meta"]["model"],
        "unique_keys": len(facts),
        "reused_keys": len(groups["reused"]),
        "extracted_keys": len(extracted),
        "initial_pass_keys": sum(r["attempts"] == 1 for r in extracted),
        "first_pass_issue_keys": len(failures),
        "first_pass_issue_rate": len(failures) / len(extracted),
        "recorded_attempts": sum(r["attempts"] for r in extracted),
        "finalization": dict(sorted(Counter(r["finalized"] for r in failures.values()).items())),
        "failure_reasons": dict(sorted(Counter(r["reason"] for r in failures.values()).items())),
        "null_final_values": sum(value is None for value in facts.values()),
        "value_kinds_by_origin": {
            origin: dict(sorted(Counter(r["value_kind"] for r in group).items()))
            for origin, group in groups.items()
        },
        "canonical_facts_by_origin": {
            origin: sum(sum(isinstance(item, str) for item in facts[r["cache_key"]])
                        for r in group if isinstance(facts[r["cache_key"]], list))
            for origin, group in groups.items()
        },
        **usage,
        "author_cache_original_usage": None,
        "per_attempt_usage": None,
        "batch_wall_time_s": None,
    }
    return groups, texts, stats


def audit_sample(groups, facts, texts):
    sampled = []
    for origin, group in groups.items():
        lookup = {r["cache_key"]: r for r in group}
        eligible = [key for key in lookup if canonical_kind(facts[key]) == "list_of_strings"]
        keys = sorted(random.Random(SEED).sample(eligible, SAMPLE_SIZE))
        for key in keys:
            record = lookup[key]
            sampled.append({
                "key": key, "question_id": record["question_id"], "turn_id": record["turn_id"],
                "status": origin, "source_text": texts[key], "facts": facts[key],
            })
    review = rows(SAMPLE)
    require(len(review) == len(sampled), "Spot-check count differs from the reproduced sample")
    by_origin = {}
    for expected, reviewed in zip(sampled, review, strict=True):
        require(all(reviewed[field] == value for field, value in expected.items()),
                f"Spot-check source or selection changed: {expected['key']}")
        judgments = reviewed["judgments"]
        labels = {"supported", "uncertain", "unsupported"}
        require(len(judgments) == len(expected["facts"]) and all(
            j["status"] in labels and (j["status"] == "supported" or j.get("reason"))
            for j in judgments
        ), f"Incomplete fact review: {expected['key']}")
        by_origin.setdefault(expected["status"], Counter()).update(j["status"] for j in judgments)
    return {
        "seed": SEED,
        "turns_per_origin": SAMPLE_SIZE,
        "by_origin": {k: dict(sorted(v.items())) for k, v in by_origin.items()},
        "all": dict(sorted(sum(by_origin.values(), Counter()).items())),
    }


def index_cost(path, q_counts, manifest, index_facts_path, index, extract_seconds):
    cost = load_json(path)
    provenance_path = path.with_name("provenance.json")
    provenance = load_json(provenance_path)
    require(cost["identity"] == provenance["identity"]
            and provenance["manifest_sha256"] == source_hash(manifest)
            and provenance["config"]["index"] == index
            and provenance["facts_sha256"] == (source_hash(index_facts_path) if index == "K1" else None),
            f"Index receipt uses different inputs: {index}")
    per_question = cost["per_question"]
    require(cost["questions"] == len(q_counts)
            and {q: r["n_turns"] for q, r in per_question.items()} == q_counts,
            f"Cost scope disagrees with the frozen histories: {index}")
    for total, detail in (
        ("index_build_s", "index_encode_s"), ("indexed_turns", "n_turns"),
        ("indexed_tokens_after_truncation", "index_tokens"),
        ("index_tokens_before_truncation", "index_tokens_raw"),
        ("truncated_index_texts", "n_truncated"),
    ):
        require(math.isclose(cost[total], math.fsum(r[detail] for r in per_question.values())),
                f"Cost total and per-question records disagree: {index} {total}")
    query = math.fsum(r["query_encode_s"] for r in per_question.values())
    rank = math.fsum(r["rank_s"] for r in per_question.values())
    require(math.isclose(query + rank, cost["retrieval_s"]), f"Retrieval time disagrees: {index}")
    return {
        "source": path.relative_to(ROOT).as_posix(),
        "cost_sha256": source_hash(path),
        "provenance_sha256": source_hash(provenance_path),
        "model_load_s": cost["model_load_s"],
        "index_build_s": cost["index_build_s"],
        "recorded_fact_turn_seconds": extract_seconds,
        "known_one_time_s": math.fsum((cost["model_load_s"], cost["index_build_s"], extract_seconds)),
        "query_encode_s": query,
        "rank_s": rank,
        "retrieval_s": cost["retrieval_s"],
        "mean_retrieval_s": cost["retrieval_s"] / len(q_counts),
        "indexed_turns": cost["indexed_turns"],
        "stella_tokens_before_truncation": cost["index_tokens_before_truncation"],
        "stella_tokens_after_truncation": cost["indexed_tokens_after_truncation"],
        "truncated_index_texts": cost["truncated_index_texts"],
    }


def analyze():
    plan_path = ROOT / "G/G02/plan.json"
    plan = load_json(plan_path)
    formal = plan["formal"]
    facts, sources, messages, index_facts, candidates, counts, manifest, index_path = formal_inputs(plan)
    ledger = load_json(LEDGER)
    require(plan["status"] == "frozen" and ledger["meta"]["a03_version"] == formal["config_version"]
            and ledger["meta"]["formal_questions"] == len(counts), "Expected matching frozen G02/C04 versions")
    groups, texts, stats = audit_extraction(ledger, facts, sources, messages)
    noncanonical = {key for key, value in facts.items()
                    if canonical_kind(value) not in ("list_of_strings", "empty_list")}
    require(noncanonical == {r["cache_key"] for r in ledger["noncanonical_reused"]},
            "Ledger anomaly list does not match the frozen cache")
    hits = {
        index: Counter(sources[record["question_id"], candidate["turn_id"]]["fact_key"]
                       for record in rows(path) for candidate in record["candidates"])
        for index, path in candidates.items()
    }
    extraction = stats["recorded_turn_seconds"]
    costs = {index: index_cost(RETRIEVAL / team / "results/cost.json", counts, manifest,
                              index_path, index, charge)
             for index, team, charge in (("K0", "B04", 0), ("K1", "B06", extraction))}
    return {
        "g02_version": plan["config_version"],
        "a03_version": formal["config_version"],
        "questions": len(counts),
        "plan_sha256": source_hash(plan_path),
        "ledger_sha256": source_hash(LEDGER),
        "spotcheck_sha256": source_hash(SAMPLE),
        "notes_on_cost_scope": "Recorded per-turn extraction plus Stella model load and encoding; retrieval is per question. Cached author's original costs and unrecorded attempt costs remain unknown.",
        "fact_snapshot_sha256": formal["fact_snapshot"]["git_blob_sha256"],
        "fact_quality": audit_sample(groups, facts, texts),
        "c04_extraction": stats,
        "formal_turn_positions": len(sources),
        "fallback_to_original_user_text_positions": sum(not value for value in index_facts.values()),
        "noncanonical_keys": {
            key: {"kind": canonical_kind(facts[key]), "candidate_occurrences": {i: a[key] for i, a in hits.items()}}
            for key in sorted(noncanonical)
        },
        "index_cost": costs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-summary", action="store_true", help="Regenerate the checked JSON summary")
    args = parser.parse_args()
    summary = analyze()
    if args.write_summary:
        SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    else:
        require(load_json(SUMMARY) == summary, "Tracked summary differs from rebuilt C05 results")
    print(f"C05 PASS: {summary['questions']} questions, {summary['formal_turn_positions']} source positions")


if __name__ == "__main__":
    main()
