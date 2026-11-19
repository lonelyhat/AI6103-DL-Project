"""从固定的 LongMemEval-S 清洗数据生成正式题清单和审计记录。"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "A01"))
from build_a01 import CONFIG_VERSION, build_question, dump_jsonl

TARGET = 80
VERSION = "a03-v2"  # v2：补登 baseline_v1 旧实验用题
SEED = "a03-v1"  # 抽样顺序沿用 v1，只因排除范围变化而换题


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def evidence_keys(question, evaluation):
    """用官方证据会话和消息标记会话的并集定位证据来源。"""
    official_ids = set(question["answer_session_ids"])
    session_ids = question["haystack_session_ids"]
    sessions = question["haystack_sessions"]
    keys = {("session_id", session_id) for session_id in official_ids}
    for index in set(evaluation["evidence_session_indices"]) | {
        int(message_id.rsplit("-", 2)[1][1:])
        for message_id in evaluation["evidence_message_ids"]
    }:
        keys.add(("session_id", session_ids[index]))
        content = [(message["role"], message["content"]) for message in sessions[index]]
        keys.add(("session_content", sha256(json.dumps(content, ensure_ascii=False).encode())))
    return keys


def connected_groups(evidence):
    owners = defaultdict(set)
    for question_id, keys in evidence.items():
        for key in keys:
            owners[key].add(question_id)
    groups = {}
    for question_id in sorted(evidence):
        if question_id in groups:
            continue
        pending = [question_id]
        while pending:
            member = pending.pop()
            if member in groups:
                continue
            groups[member] = question_id
            for key in evidence[member]:
                pending.extend(owners.pop(key, ()))
    return groups


def allocate_quotas(pool):
    counts = Counter(row["question_type"] for row in pool)
    total = len(pool)
    quotas = {kind: TARGET * count // total for kind, count in counts.items()}
    by_remainder = sorted(counts, key=lambda kind: (-(TARGET * counts[kind] % total), kind))
    for kind in by_remainder[:TARGET - sum(quotas.values())]:
        quotas[kind] += 1
    return quotas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "output")
    parser.add_argument("--extra-used-id", action="append", default=[])
    parser.add_argument("--extra-used-file", type=Path, action="append", default=[],
                        help="每行一个已用题号的文件")
    args = parser.parse_args()

    raw = args.data.read_bytes()
    data_sha = sha256(raw)
    manifest_raw = (HERE.parent / "A01/output/dev_manifest.json").read_bytes()
    dev = json.loads(manifest_raw)
    if data_sha != dev["data_sha256"] or dev["config_version"] != CONFIG_VERSION:
        raise ValueError("数据或配置版本与 A01 清单不一致")
    data = json.loads(raw)
    all_ids = {q["question_id"] for q in data}
    dev_ids = set(dev["dev_ids"])
    extra_raw = list(args.extra_used_id)
    for path in args.extra_used_file:
        extra_raw += [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    extra_ids = set(extra_raw) - dev_ids
    used_ids = dev_ids | extra_ids
    if len(all_ids) != len(data) or used_ids - all_ids:
        raise ValueError(f"题号重复或用题记录含未知题号：{sorted(used_ids - all_ids)}")

    public, evaluations, evidence = {}, {}, {}
    for q in data:
        question_id = q["question_id"]
        public[question_id], ev, _, _ = build_question(q)
        evaluations[question_id] = ev
        evidence[question_id] = evidence_keys(q, ev)
    groups = connected_groups(evidence)
    used_groups = {groups[qid] for qid in used_ids}
    audits = {}
    pool = []
    for qid, ev in sorted(evaluations.items()):
        reasons = []
        if qid in dev_ids:
            reasons.append("a01_dev")
        if qid in extra_ids:
            reasons.append("extra_prior_use")
        if ev["is_abstention"]:
            reasons.append("abstention")
        elif not ev["evidence_message_ids"]:
            reasons.append("no_annotated_evidence")
        if qid not in used_ids and groups[qid] in used_groups:
            reasons.append("shared_evidence_with_prior_use")
        row = {
            "question_id": qid,
            "question_type": ev["question_type"],
            "evidence_group": groups[qid],
            "unreachable_evidence_count": len(ev["unreachable_evidence_message_ids"]),
            "reasons": reasons,
        }
        audits[qid] = row
        if not reasons:
            pool.append(row)
    if len(pool) < TARGET:
        raise ValueError(f"可用题只有 {len(pool)} 道，低于目标 {TARGET}")

    quotas = allocate_quotas(pool)
    remaining = quotas.copy()
    selected = []
    for row in sorted(pool, key=lambda row: sha256(f"{SEED}:{row['question_id']}".encode())):
        kind = row["question_type"]
        if remaining[kind] > 0:
            selected.append(row["question_id"])
            remaining[kind] -= 1
        else:
            row["reasons"].append("not_sampled")
    if len(selected) != TARGET or any(remaining.values()):
        raise RuntimeError("未达到正式题抽样配额")

    selected_set = set(selected)
    formal_groups = defaultdict(list)
    for qid in selected:
        formal_groups[groups[qid]].append(qid)
    for qid, row in audits.items():
        row["selected"] = qid in selected_set
    result = {
        "config_version": VERSION,
        "sampling_seed": SEED,
        "data_file": args.data.name,
        "data_sha256": data_sha,
        "a01_manifest_sha256": sha256(manifest_raw),
        "target_count": TARGET,
        "actual_count": len(selected),
        "eligible_count": len(pool),
        "eligible_type_counts": dict(sorted(Counter(row["question_type"] for row in pool).items())),
        "formal_type_counts": dict(sorted(quotas.items())),
        "formal_ids": selected,
        "evidence_groups": [sorted(ids) for _, ids in sorted(formal_groups.items())],
        "extra_prior_use_ids": sorted(extra_ids),
        "excluded_reason_counts": dict(sorted(Counter(
            reason for row in audits.values() for reason in row["reasons"]
        ).items())),
        "selected_with_unreachable_evidence_ids": [
            qid for qid in selected if audits[qid]["unreachable_evidence_count"]
        ],
    }
    eval_dir = args.out / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "formal_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    dump_jsonl(eval_dir / "selection_audit.jsonl", audits.values())
    dump_jsonl(args.out / "public/formal_questions.jsonl", (
        {**public[qid], "stage": "formal"} for qid in selected
    ))
    print(f"正式题 {len(selected)}/{TARGET}，候选池 {len(pool)}，分层配额 {dict(sorted(quotas.items()))}")


if __name__ == "__main__":
    main()
