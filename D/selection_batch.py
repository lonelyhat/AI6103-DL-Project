"""D03/D04/D05: real candidate batches, exact history budgets, replay verification."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from D.D01.selection import Config, HFTokenizer, digest, select
from D.D02.materials import INPUT_VERSIONS
from D.D02.prepare_materials import read_jsonl, sha, write_bundle

REPO = Path(__file__).resolve().parents[1]
CONFIG = Path(__file__).with_name("selection_config.json")
VERSION = "d03-d05-v1"
METHODS = ("MMR", "C", "Q", "FL")


def active_config(strategy, redundancy_weight, coverage_weight):
    # Validate even inactive CLI parameters, but only active weights identify a run.
    weights = Config(redundancy_weight, coverage_weight)
    return Config(0 if strategy == "FL" else weights.redundancy_weight,
                  weights.coverage_weight if strategy == "Q" else 0)


def prepare_results(candidate_rows, questions, load_turns, counter, settings):
    expected = settings["question_ids"]
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("question IDs must be nonempty and unique")
    strategies = settings["strategies"]
    if not strategies or len(strategies) != len(set(strategies)) or set(strategies)-set(METHODS):
        raise ValueError("choose distinct MMR/C/Q/FL strategies")
    if type(settings["budget_tokens"]) is not int or settings["budget_tokens"] < 0:
        raise ValueError("budget must be a nonnegative integer")
    public = {}
    for q in questions:
        if not isinstance(q, dict) or set(q)-{"question_id", "stage", "question", "question_date"}:
            raise ValueError("only A01 public question fields are allowed")
        qid = q["question_id"]
        if qid in public:
            raise ValueError("duplicate public question")
        public[qid] = q
    inputs = {}
    for row in candidate_rows:
        if not isinstance(row, dict):
            raise ValueError("candidate rows must be objects")
        qid = row.get("question_id")
        if qid not in expected or qid in inputs:
            raise ValueError("unexpected or duplicate candidate question")
        inputs[qid] = row
    if set(inputs) != set(expected):
        raise ValueError("candidate file must contain exactly the requested questions")
    results = []
    for qid in expected:
        if qid not in public:
            raise ValueError(f"missing public question: {qid}")
        request = dict(inputs[qid])
        for key, value in public[qid].items():
            if key in request and request[key] != value:
                raise ValueError(f"{qid}: conflicting public metadata: {key}")
            request[key] = value
        if request.get("config_version") not in INPUT_VERSIONS.get(settings["stage"], ()):
            raise ValueError("require the candidate version for the requested dev/formal stage")
        if request.get("stage") != settings["stage"] or request.get("index") != settings["index"]:
            raise ValueError("candidate stage/index differs from experiment")
        if request.get("strategy") is not None:
            raise ValueError("require unselected B candidates (strategy=null or absent)")
        # Candidate budget is provenance for the default condition; a sweep must be explicit.
        if request.get("budget_tokens") not in (None, settings["budget_tokens"]):
            raise ValueError("candidate budget differs; reconcile metadata before running")
        request["budget_tokens"] = settings["budget_tokens"]
        turns = load_turns(qid)
        for strategy in strategies:
            weights = active_config(strategy, settings["redundancy_weight"], settings["coverage_weight"])
            started = time.perf_counter()
            result = select(request, turns, counter, strategy, weights)
            elapsed = time.perf_counter()-started
            result.update(
                question=request["question"], question_date=request.get("question_date"),
                config_version=VERSION, n_candidates=len(request["candidates"]),
                n_selected_turns=len(result["selected_turn_ids"]),
                history_file=f"materials/{strategy}-{qid}.txt",
                selection_elapsed_s=elapsed,
                status="ready_for_reader" if result["selected_turn_ids"] else "empty_material",
                budget_check={"passed": result["context_tokens"] <= settings["budget_tokens"]},
            )
            result["config"].update(batch_implementation=VERSION)
            result["config_id"] = digest(result["config"])
            by_id = {c["turn_id"]: c for c in request["candidates"]}
            for step in result["steps"]:
                step["retrieval_score"] = by_id[step["turn_id"]]["score"]
            results.append(result)
    return results


def main():
    defaults = json.loads(CONFIG.read_text(encoding="utf-8"))
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidates", type=Path, default=REPO/"B-检索线/B02/candidates/dev_K0.jsonl")
    p.add_argument("--public-root", type=Path, default=REPO/"A-数据线/A01/output/public")
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--tokenizer-label")
    p.add_argument("--allow-download", action="store_true")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--strategies", nargs="+", choices=METHODS, default=defaults["strategies"])
    p.add_argument("--redundancy-weight", type=float, default=defaults["redundancy_weight"])
    p.add_argument("--coverage-weight", type=float, default=defaults["coverage_weight"])
    p.add_argument("--question-ids", nargs="+", default=defaults["question_ids"])
    p.add_argument("--index", choices=("K0", "K1"), default=defaults["index"])
    args = p.parse_args()
    settings = dict(defaults, strategies=args.strategies, question_ids=args.question_ids,
                    redundancy_weight=args.redundancy_weight,
                    coverage_weight=args.coverage_weight, index=args.index)
    active_config("Q", args.redundancy_weight, args.coverage_weight)
    if args.tokenizer.startswith("demo:"):
        p.error("real batches require the actual reader tokenizer")
    if args.output_dir.exists():
        p.error("output exists; choose a new batch directory")
    sources = [Path(__file__), CONFIG, REPO/"D/D01/selection.py",
               REPO/"D/D02/prepare_materials.py", REPO/"D/verify_selection.py"]
    inputs = [args.candidates, args.public_root/"dev_questions.jsonl"]
    inputs += [args.public_root/"turns"/f"{qid}.jsonl" for qid in args.question_ids]
    out = args.output_dir.resolve()
    protected = [args.public_root.resolve(), *[path.resolve() for path in inputs+sources]]
    if any(out == path or out.is_relative_to(path) or path.is_relative_to(out) for path in protected):
        p.error("output must not contain or overlap input/source paths")
    def location(path):
        absolute = path.resolve()
        return str(absolute.relative_to(REPO)) if absolute.is_relative_to(REPO) else str(absolute)
    input_hashes = {location(path): sha(path) for path in inputs}
    source_hashes = {location(path): sha(path) for path in sources}
    counter = HFTokenizer(args.tokenizer, allow_download=args.allow_download)
    if args.tokenizer_label:
        counter.name = args.tokenizer_label
    started = time.perf_counter()
    rows = prepare_results(read_jsonl(args.candidates), read_jsonl(inputs[1]),
                           lambda qid: read_jsonl(args.public_root/"turns"/f"{qid}.jsonl"),
                           counter, settings)
    for path in inputs+sources:
        expected = input_hashes.get(location(path), source_hashes.get(location(path)))
        if sha(path) != expected:
            raise RuntimeError("inputs/source changed while preparing batch")
    manifest = {
        "config_version": VERSION, "config": settings,
        "n_questions": len(args.question_ids), "n_records": len(rows),
        "tokenizer_source": str(Path(args.tokenizer).resolve()) if Path(args.tokenizer).exists() else args.tokenizer,
        "tokenizer_label": counter.name, "tokenizer_fingerprint": counter.fingerprint,
        "candidate_file": location(args.candidates), "public_root": location(args.public_root),
        "input_sha256": input_hashes, "source_sha256": source_hashes,
        "selection_total_elapsed_s": time.perf_counter()-started,
        "status": "materials_generated_pending_replay",
        "records": [{"question_id": r["question_id"], "strategy": r["strategy"],
                     "context_tokens": r["context_tokens"], "history_file": r["history_file"],
                     "history_sha256": r["history_sha256"]} for r in rows],
    }
    write_bundle(out, rows, manifest)
    from D.verify_selection import verify_bundle
    report = verify_bundle(out, counter)
    (out/"verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    for row in rows:
        print(f'{row["strategy"]:3} {row["question_id"]}: {row["n_selected_turns"]} turns, '
              f'{row["context_tokens"]}/{settings["budget_tokens"]} tokens, '
              f'{row["selection_elapsed_s"]:.2f}s, {row["stop_reason"]}')
    print(f"Replay PASS: {len(rows)} records -> {out}")
    if not report["all_ready_for_reader"]:
        raise SystemExit("Structurally valid batch contains empty materials; inspect before reader handoff")


if __name__ == "__main__":
    main()
