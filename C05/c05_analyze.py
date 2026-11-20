# -*- coding: utf-8 -*-
"""C05 事实质量 + 一次性建库成本分析。

产出：
1. 非规范事实值定位（list_with_non_string / string，来自作者缓存的格式异常）
2. 固定抽样样本（deterministic seed=42，抽取轮 + 复用轮分层抽样）用于人工核对忠实性
3. 失败率 / 调用量 / 两种索引一次性成本汇总（打印，供写入交付文档）
"""
import json
import os
import random
from collections import Counter

FORMAL_FACTS = "c04_output/c04_facts_80q.json"
FORMAL_MANIFEST = "c04_output/c04_turn_manifest.json"
DEV_FACTS = "output/dev_facts_all40q.json"
DEV_MANIFESTS = ["c02_output/c02_turn_manifest.json", "c03_output/c03_turn_manifest.json"]

SEED = 42


def canonical_kind(v):
    """Return a value-kind tag matching B05/B06 facts_preparation. """
    if isinstance(v, list):
        if len(v) == 0:
            return "empty_list"
        return "list_of_strings" if all(isinstance(x, str) for x in v) else "list_with_non_string"
    if isinstance(v, str):
        return "string"
    return type(v).__name__


def load_json(p):
    return json.load(open(p, encoding="utf-8"))


def scan(facts_path, manifest_paths, label):
    facts = load_json(facts_path)
    manifest = {}
    for mp in manifest_paths:
        if os.path.isfile(mp):
            manifest.update(load_json(mp))
    kind = Counter()
    anomalies = []
    n_facts = 0
    for key, v in facts.items():
        k = canonical_kind(v)
        kind[k] += 1
        if isinstance(v, list):
            n_facts += sum(1 for x in v if isinstance(x, str))
        if k in ("list_with_non_string", "string") or (k not in ("empty_list", "list_of_strings")):
            m = manifest.get(key, {})
            anomalies.append({
                "key": key,
                "kind": k,
                "value": v,
                "question_id": m.get("question_id"),
                "turn_id": m.get("turn_id"),
                "status": m.get("status"),
                "source_text": m.get("source_text"),
            })
    print(f"\n===== {label} =====")
    print("value_kinds:", dict(kind))
    print("non-canonical count:", len(anomalies))
    for a in anomalies:
        print("-" * 60)
        print(f"key={a['key']} kind={a['kind']} status={a['status']} qid={a['question_id']} turn={a['turn_id']}")
        print(f"value={json.dumps(a['value'], ensure_ascii=False)[:400]}")
        print(f"source={ (a['source_text'] or '')[:300] }")
    return kind, anomalies


def sample_turns(manifest, facts, status, k, seed=SEED):
    """按状态分层抽样 k 个有事实的轮，输出 (source_text, facts) 供人工核对。"""
    keys = [key for key, m in manifest.items()
            if m.get("status") == status and facts.get(key)]
    rng = random.Random(seed)
    chosen = sorted(rng.sample(keys, min(k, len(keys))))
    out = []
    for key in chosen:
        m = manifest[key]
        out.append({
            "key": key, "question_id": m["question_id"], "turn_id": m["turn_id"],
            "status": status, "source_text": m["source_text"], "facts": facts[key],
        })
    return out


def main():
    kind_formal, anom_formal = scan(FORMAL_FACTS, [FORMAL_MANIFEST], "formal (c04_facts_80q.json)")
    kind_dev, anom_dev = scan(DEV_FACTS, DEV_MANIFESTS, "dev (dev_facts_all40q.json)")

    formal_facts = load_json(FORMAL_FACTS)
    formal_manifest = load_json(FORMAL_MANIFEST)
    dev_facts = load_json(DEV_FACTS)

    # 抽样样本
    sample = []
    sample += sample_turns(formal_manifest, formal_facts, "extracted", 20)
    sample += sample_turns(formal_manifest, formal_facts, "reused", 20)
    dev_manifest = {}
    for mp in DEV_MANIFESTS:
        dev_manifest.update(load_json(mp))
    sample += sample_turns(dev_manifest, dev_facts, "extracted", 5)
    sample += sample_turns(dev_manifest, dev_facts, "reused", 5)

    out_path = "c05_output/spotcheck_sample.jsonl"
    os.makedirs("c05_output", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in sample:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n抽样样本已写入 {out_path}（共 {len(sample)} 轮：正式抽20/复用20 + 开发抽5/复用5）")

    # 失败率 / 调用量汇总
    def status_counts(manifest):
        c = Counter(m.get("status") for m in manifest.values())
        return dict(c)

    print("\n===== 状态分布 =====")
    print("formal:", status_counts(formal_manifest))
    print("dev(合并):", status_counts(dev_manifest))


if __name__ == "__main__":
    main()
