"""Split a verified multi-method batch into D03/D04/D05 Git deliverables."""
import argparse
import json
from pathlib import Path
import shutil
from D.D01.selection import HFTokenizer
from D.D02.prepare_materials import read_jsonl, sha, write_bundle
from D.verify_selection import verify_bundle

REPO = Path(__file__).resolve().parents[1]


def package(source, ablation, tokenizer):
    source, ablation = Path(source), Path(ablation)
    base = json.loads((source/"batch_manifest.json").read_text())
    counter = HFTokenizer(tokenizer or base["tokenizer_source"])
    counter.name = base["tokenizer_label"]
    verify_bundle(source, counter)
    verify_bundle(ablation, counter)
    ablation_rows = read_jsonl(ablation/"selections.jsonl")
    indexed = {(r["question_id"], r["strategy"]): r for r in ablation_rows}
    qids = base["config"]["question_ids"]
    if set(indexed) != {(qid, s) for qid in qids for s in ("C", "Q")}:
        raise ValueError("ablation must cover exactly the same questions")
    for qid in qids:
        c, q = indexed[qid, "C"], indexed[qid, "Q"]
        if c["config"]["coverage_weight"] != 0 or q["config"]["coverage_weight"] != 0:
            raise ValueError("ablation coverage weight must be zero")
        for field in ("selection_order", "steps", "selected_message_ids", "history_text", "context_tokens"):
            if c[field] != q[field]:
                raise ValueError(f"{qid}: gamma zero differs in {field}")
    rows = read_jsonl(source/"selections.jsonl")
    for task, strategies in (("D03", ["MMR"]), ("D04", ["C", "Q"]), ("D05", ["FL"])):
        target = REPO/"D"/task/"output"/source.name
        selected = [r for r in rows if r["strategy"] in strategies]
        manifest = dict(base)
        manifest["config"] = dict(base["config"], strategies=strategies)
        manifest["n_records"] = len(selected)
        manifest["selection_total_elapsed_s"] = sum(r["selection_elapsed_s"] for r in selected)
        manifest["derived_from_manifest_sha256"] = sha(source/"batch_manifest.json")
        manifest["records"] = [r for r in base["records"] if r["strategy"] in strategies]
        if not target.exists():
            write_bundle(target, selected, manifest)
        else:
            if json.loads((target/"batch_manifest.json").read_text()) != manifest:
                raise FileExistsError(f"another batch already occupies {target}")
        report = verify_bundle(target, counter)
        if not report["all_ready_for_reader"]:
            raise ValueError(f"{task}: empty material")
        (target/"verification.json").write_text(json.dumps(report, indent=2)+"\n")
        status_path = REPO/"D"/task/"STATUS.json"
        status = json.loads(status_path.read_text())
        status["results"] = str(target.relative_to(REPO))
        status["verification"] = str((target/"verification.json").relative_to(REPO))
        if task == "D04":
            dest = REPO/"D/D04/output"/ablation.name
            if not dest.exists():
                shutil.copytree(ablation, dest)
            verify_bundle(dest, counter)
            status["gamma_zero_results"] = str(dest.relative_to(REPO))
            (dest/"ablation_verification.json").write_text(json.dumps({
                "coverage_weight": 0,
                "checks": [{"question_id": qid, "status": "passed"} for qid in qids]
            }, indent=2)+"\n")
        status_path.write_text(json.dumps(status, indent=2)+"\n")
        shutil.copyfile(REPO/"D/validation/unit_tests.txt", target/"unit_tests.txt")
        print(f"{task}: {len(selected)} records, verified -> {target}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--ablation", type=Path, required=True)
    p.add_argument("--tokenizer")
    args = p.parse_args()
    package(args.source, args.ablation, args.tokenizer)
