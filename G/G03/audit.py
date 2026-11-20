"""Verify the frozen G02 result chain against the published E04 Git archive."""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
E04 = "95438df71b0730d58ab260d97f4528e3b3228e72"
BASE = "09bdcad139bad6d26c4b6cc9db417bb37b8dc570"
D08_COMMIT = "5b1c02fa45ae9c71e8ed0bcc5b0171daec530c89"
E04_PATH = "E/E04/results/g02-v1"
A = ROOT / "A-数据线"
D08 = ROOT / "D/D08/delivery"
F = ROOT / "F"
sys.path[:0] = [str(ROOT / "E/E03"), str(F / "src/evaluation")]
from batch import digest, normalize  # noqa: E402
from export_for_f import e02_export  # noqa: E402
from judge import answer_fingerprint, choose_response, parse_judge_label  # noqa: E402


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def blob(revision, path):
    return git("cat-file", "blob", f"{revision}:{path}")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def jsonl(raw):
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def indexed(records, fields, source):
    result = {tuple(row[field] for field in fields): row for row in records}
    require(len(result) == len(records), f"{source}: duplicate record")
    return result


def audit_batch(batch, spec, archive, plan_sha, plan, questions, evaluations, metrics, costs):
    prefix = f"{E04_PATH}/{batch}"
    files = set(git("ls-tree", "--name-only", E04, prefix + "/").decode().splitlines())
    raw = {Path(path).name: blob(E04, path) for path in files}
    config = json.loads(raw["config.json"])
    frozen_reader = plan["reader"]
    require(all(config[key] == value for key, value in frozen_reader.items())
            and config["stage"] == "formal" and config["records"] == spec["expected_records"],
            f"{batch}: frozen reader configuration")
    require(all(sha(blob(BASE, "E/" + path)) == value
                for path, value in config["source_sha256"].items()),
            f"{batch}: reader code from audited main")
    require(config["gpu"] == "NVIDIA " + costs["GPU"], f"{batch}: GPU in cost table")
    require(sha(raw["results.jsonl"]) == costs["results.jsonl sha256"],
            f"{batch}: raw result hash in cost table")

    package = D08 / archive["archive"]
    require(sha(package.read_bytes()) == archive["archive_sha256"], f"{batch}: D08 archive")
    with zipfile.ZipFile(package) as source:
        inputs = source.read("reader_inputs.jsonl")
        selections = source.read("selections.jsonl")
        receipt = json.loads(source.read("receipt.json"))
    require(receipt["batch_id"] == batch and receipt["plan_sha256"] == plan_sha
            and spec["question_ids"] == archive["question_ids"] == receipt["question_ids"]
            and sha(inputs) == archive["input_sha256"] == receipt["input_sha256"] == config["input_sha256"]
            and sha(selections) == archive["selections_sha256"] == receipt["selections_sha256"],
            f"{batch}: plan, D08 receipt or E04 input hash")
    if "inputs.jsonl" in raw:
        require(raw["inputs.jsonl"] == inputs, f"{batch}: original E04 input bytes")
    if "attempts.jsonl" in raw:
        require(jsonl(raw["attempts.jsonl"]) == jsonl(raw["results.jsonl"]),
                f"{batch}: journal and final results")

    fields = ("question_id", "index", "strategy")
    sources = {
        "D08 selection": selections,
        "D08 reader": inputs,
        "E04 result": raw["results.jsonl"],
        "E04 export": raw["answers_for_f.jsonl"],
        "F04 score": (F / f"scores/formal_g02-v1_{batch}.jsonl").read_bytes(),
    }
    expected = {(q, i, s) for q in spec["question_ids"] for i in plan["indices"] for s in plan["methods"]}
    tables = [indexed(jsonl(source), fields, f"{batch} {name}") for name, source in sources.items()]
    require(len(expected) == spec["expected_records"] and all(table.keys() == expected for table in tables),
            f"{batch}: expected question and setting grid")
    summary = json.loads(raw["summary.json"])
    statuses = Counter()
    truncated = []
    correct = 0
    reader_config_id = digest(config)
    for key in sorted(expected):
        select, item, result, answer, score = (table[key] for table in tables)
        q, _, strategy = key
        detail = "/".join(key)
        question = questions[q]
        metric = metrics[key]
        require(normalize(item) == item and all(result[k] == v for k, v in item.items())
                and item["question"] == select["question"] == question["question"]
                and item["question_date"] == select["question_date"] == question["question_date"],
                f"{detail}: frozen reader input or result identity")
        require(select["history_text"] == item["context"]
                and select["history_sha256"] == item["history_sha256"] == metric["history_sha256"]
                and select["selected_turn_ids"] == item["selected_turn_ids"]
                and select["config"] == item["selection_config"]
                and select["config_id"] == item["selection_config_id"] == metric["config_id"]
                and select["context_tokens"] == item["context_tokens"] == metric["context_tokens"]
                and item["budget_tokens"] == metric["budget_tokens"] == plan["history_budget_tokens"]
                and metric["batch_id"] == batch and select["budget_check"]["passed"]
                and item["tokenizer_fingerprint"] == frozen_reader["tokenizer_fingerprint"],
                f"{detail}: selection or evidence metrics")
        if strategy != "R":
            require(all(select["config"][k] == v for k, v in plan["methods"][strategy].items()),
                    f"{detail}: frozen method weights")
        evidence = evaluations[q]["evidence_message_ids"]
        selected = set(select["selected_message_ids"])
        missing = [message for message in evidence if message not in selected]
        require(metric["selected"]["missing_message_ids"] == missing
                and metric["selected"]["n_retained_msgs"] == len(evidence) - len(missing),
                f"{detail}: selected evidence versus official message IDs")
        require(result["reader_config_id"] == reader_config_id
                and result["reader_config_version"] == config["reader_config_version"]
                and result["batch_runner_version"] == config["batch_runner_version"]
                and result["attempt"] == 1
                and all(answer[k] == v for k, v in e02_export.convert(result).items())
                and all(answer[k] == result[k] for k in
                        ("record_id", "selected_turn_ids", "input_record_sha256",
                         "reader_config_id", "selection_config_id", "attempt")),
                f"{detail}: E04 result/export")
        response, source, agrees = choose_response(answer)
        require(all(score[k] == answer[k] for k in
                    ("record_id", "reader_config_id", "selection_config_id", "history_sha256",
                     "generation_status"))
                and score["e_status"] == answer["status"] and score["answer_sha256"] == answer_fingerprint(answer)
                and (score["response_sent"], score["response_source"], score["extract_agrees"])
                    == (response, source, agrees)
                and score["scoring_config_version"] == plan["scoring"]["config_version"]
                and score["judge_model"] == plan["scoring"]["judge_model"]
                and score["status"] == "ok" and type(score["label"]) is int and score["label"] in (0, 1)
                and parse_judge_label(score["judge_output"]) == (score["label"], "clean")
                and score["parse_status"] == "clean",
                f"{detail}: actual E04 response and F04 score linkage")
        correct += score["label"]
        status = result["status"]
        statuses[status] += 1
        if status == "truncated":
            require(result["hit_output_limit"], f"{detail}: truncation flag")
            truncated.append(dict(zip(fields, key), record_id=item["record_id"], label=score["label"]))
    require(summary["expected"] == summary["recorded"] == summary["attempts"] == len(expected)
            and summary["missing"] == 0 and Counter(summary["statuses"]) == statuses,
            f"{batch}: final counts and attempts")
    optional = {"inputs.jsonl", "attempts.jsonl", "runtime.jsonl", "invocations.jsonl", "slurm_final.txt"}
    job_ids = sorted({r["slurm_job_id"] for r in tables[2].values()})
    optional.update(f"e03-{job_id}.{ext}" for job_id in job_ids for ext in ("out", "err"))
    report = {"records": len(expected), "statuses": dict(sorted(statuses.items())),
              "correct": correct, "job_ids": job_ids,
              "gpu": config["gpu"], "archive_missing": sorted(optional - raw.keys()),
              "truncated": truncated}
    return report, tables[0], tables[-1]


def audit_f05(scores):
    f05 = F / "F05/g02-v1"
    by_id = {row["record_id"]: row for row in scores.values()}
    decisions = {row["编号"]: row for row in csv_rows(f05 / "results/F05_人机对照_定稿.csv")}
    memberships = defaultdict(set)
    for member in csv_rows(f05 / "audit/formal_members_DO_NOT_OPEN.csv"):
        score = by_id[member["record_id"]]
        review_id = member["編號"]
        require(member["answer_sha256"] == score["answer_sha256"]
                and int(decisions[review_id]["GPT-4o 判分"]) == score["label"],
                f"{review_id}: score identity or label in F05")
        memberships[review_id].add(member["record_id"])
    require(decisions.keys() == memberships.keys() and all(
        len(memberships[rid]) == int(row["关联设置记录数"]) for rid, row in decisions.items()),
        "F05: decision membership counts")
    mismatches = sorted(rid for rid, row in decisions.items()
                        if row["人工定案"] != row["GPT-4o 判分"])
    return {"reviews": len(decisions), "settings": sum(map(len, memberships.values())),
            "agreed": len(decisions) - len(mismatches), "mismatches": mismatches}


def audit_cases(questions, evaluations, selections, scores, metrics, public):
    cases = json.loads((A / "A05/cases.json").read_bytes())
    candidates = {}
    for index, folder in (("K0", "B04"), ("K1", "B06")):
        path = ROOT / f"B-检索线/{folder}/candidates/formal_{index}.jsonl"
        candidates[index] = {r["question_id"]: r["candidates"] for r in jsonl(path.read_bytes())}
    count = 0
    for case in cases:
        q = case["question_id"]
        turns = jsonl((public / "turns" / f"{q}.jsonl").read_bytes())
        messages = {m["message_id"]: m for t in turns for m in t["messages"]}
        eval_row = evaluations[q]
        evidence = case["evidence"]
        require(case["question"] == questions[q]["question"] and case["reference_answer"] == eval_row["answer"]
                and [e["message_id"] for e in evidence] == eval_row["evidence_message_ids"]
                and all(messages[e["message_id"]] == e for e in evidence),
                f"{q}: A05 reference or archived evidence text")
        evidence_ids = set(eval_row["evidence_message_ids"])
        mapping = {r["turn_id"]: r["message_ids"]
                   for r in jsonl((A / "A03/output/map" / f"{q}.turns.jsonl").read_bytes())}
        for variant in case["variants"]:
            index, strategy = variant["index"], variant["strategy"]
            key = q, index, strategy
            select, score, metric = selections[key], scores[key], metrics[key]
            ranks = [{"turn_id": c["turn_id"], "rank": c["rank"]} for c in candidates[index][q]
                     if evidence_ids.intersection(mapping[c["turn_id"]])]
            require(variant["evidence_candidate_ranks"] == ranks
                    and variant["evidence_retained_ids"] == [
                        e["message_id"] for e in evidence if e["message_id"] in select["selected_message_ids"]]
                    and variant["candidate_missing_message_ids"] == metric["candidate"]["missing_message_ids"]
                    and all(variant[k] == score[k] for k in
                            ("record_id", "history_sha256", "response_sent", "response_source", "judge_output"))
                    and all(variant[k] == metric[k] for k in ("batch_id", "cover", "diagnosis", "context_tokens"))
                    and variant["selected_turn_ids"] == select["selected_turn_ids"]
                    and variant["judge_label"] == score["label"],
                    f"{q}/{index}/{strategy}: A05 source linkage")
            count += 1
    return {"cases": len(cases), "variants": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write a JSON audit receipt")
    args = parser.parse_args()
    plan_raw = blob(BASE, "G/G02/plan.json")
    plan = json.loads(plan_raw)
    for path, expected in plan["source_sha256"].items():
        source = blob(D08_COMMIT, path)
        require(sha(source.replace(b"\r\n", b"\n")) == expected, f"frozen source checksum: {path}")
    eval_raw = (A / "A04/output/formal_eval.jsonl").read_bytes().replace(b"\r\n", b"\n")
    require(sha(eval_raw) == plan["scoring"]["evaluation_sha256"], "frozen F04 evaluation input")
    evaluations = {row["question_id"]: row for row in jsonl(eval_raw)}
    manifest = json.loads((D08 / "manifest.json").read_bytes())
    public = ROOT / plan["formal"]["public_root"]
    questions = {r["question_id"]: r for r in jsonl((public / "formal_questions.jsonl").read_bytes())}
    metrics = indexed(jsonl((A / "A04/output/selection_metrics.jsonl").read_bytes()),
                      ("question_id", "index", "strategy"), "A04")
    costs = {r["批次"]: r for r in csv_rows(F / "F07/f07_e04_by_batch.csv")}
    batches = plan["formal"]["batches"]
    qids = [q for spec in batches.values() for q in spec["question_ids"]]
    require(len(qids) == plan["formal"]["questions"] == len(questions) and set(qids) == questions.keys()
            and questions.keys() == evaluations.keys()
            and batches.keys() == manifest["batches"].keys() == costs.keys()
            and manifest["plan_sha256"] == sha(plan_raw), "frozen formal grid or D08 manifest")
    report = {"result_commit": BASE, "d08_commit": D08_COMMIT, "e04_commit": E04,
              "plan_sha256": sha(plan_raw), "evaluation_sha256": sha(eval_raw),
              "questions": len(questions), "batches": {}}
    selections, scores = {}, {}
    for batch, spec in batches.items():
        result, selects, labels = audit_batch(batch, spec, manifest["batches"][batch], sha(plan_raw),
                                              plan, questions, evaluations, metrics, costs[batch])
        report["batches"][batch] = result
        selections.update(selects)
        scores.update(labels)
    require(scores.keys() == metrics.keys() and len(scores) == plan["scoring"]["expected_records"],
            "800 records must line up with A04")
    report["records"] = len(scores)
    report["correct"] = sum(r["label"] for r in scores.values())
    report["f05"] = audit_f05(scores)
    report["a05"] = audit_cases(questions, evaluations, selections, scores, metrics, public)
    g01 = json.loads((ROOT / "G/G01/audit_5q.json").read_bytes())["c02_ledger"]
    old_keys = {r["cache_key"] for r in g01["retry_parse_failures_with_empty_fallback"]}
    snapshot = plan["formal"]["fact_snapshot"]
    facts_raw = blob(plan["refs"]["main"], snapshot["path"])
    require(sha(facts_raw) == snapshot["git_blob_sha256"], "frozen C04 fact snapshot")
    facts = json.loads(facts_raw)
    report["g01_known_failure_keys"] = len(old_keys)
    report["g01_keys_in_frozen_c04"] = sorted(old_keys.intersection(facts))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8", newline="\n")
    print(f"G03 PASS: {len(questions)} questions, {len(scores)} settings, {len(report['batches'])} batches")


if __name__ == "__main__":
    main()
