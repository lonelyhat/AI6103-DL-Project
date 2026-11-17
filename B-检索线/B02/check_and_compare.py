#!/usr/bin/env python3
"""B02 结果核对（在本机跑，不需要 GPU）。

1. 检查 dev_K0.jsonl 的格式：5 行、每行 100 条、排名 1..100、分数有限且不增、编号无重复、
   且都能在 A01 公开轮次里找到；输出里不含官方编号 / 答案 / 题型。
2. 若给了官方检索日志：用 A01 的 map 把官方 corpus_id 换成 turn_id，比较前 100 的顺序是否一致。
   map 含官方编号，只在这里读取，不会写进候选文件。

用法：python3 check_and_compare.py <dev_K0.jsonl> [官方日志 dev5_retrievallog_turn_flat-stella]
"""
import json
import math
import sys
from pathlib import Path

A01 = Path(__file__).resolve().parents[2] / "A-数据线/A01/output"
FORBIDDEN = ("official", "answer", "question_type", "has_answer", "noans", "sharegpt", "ultrachat")


def jl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def check_format(rows):
    problems = []
    manifest = json.loads((A01 / "dev_manifest.json").read_text(encoding="utf-8"))
    want = [x["question_id"] for x in manifest["first_batch"]]
    if [r["question_id"] for r in rows] != want:
        problems.append(f"题号/顺序不是首批5题: {[r['question_id'] for r in rows]}")
    for r in rows:
        q = r["question_id"]
        expected = {"stage": "dev", "index": "K0", "strategy": None,
                    "budget_tokens": 2048, "tokenizer": "meta-llama/Llama-3.1-8B-Instruct",
                    "config_version": manifest["config_version"]}
        for key, value in expected.items():
            if r.get(key) != value:
                problems.append(f"{q}: {key} 应为 {value!r}")
        public = {t["turn_id"] for t in jl(A01 / f"public/turns/{q}.jsonl")}
        c = r["candidates"]
        if len(c) != 100:
            problems.append(f"{q}: 候选数 {len(c)} != 100")
        if [x["rank"] for x in c] != list(range(1, len(c) + 1)):
            problems.append(f"{q}: 排名不是 1..{len(c)}")
        sc = [x["score"] for x in c]
        if not all(math.isfinite(s) for s in sc) or any(a < b for a, b in zip(sc, sc[1:])):
            problems.append(f"{q}: 分数非有限或不是降序")
        ids = [x["turn_id"] for x in c]
        if len(set(ids)) != len(ids):
            problems.append(f"{q}: 候选编号重复")
        missing = [i for i in ids if i not in public]
        if missing:
            problems.append(f"{q}: {len(missing)} 个编号不在 A01 公开轮次里，如 {missing[:2]}")
        blob = json.dumps(r, ensure_ascii=False).lower()
        for w in FORBIDDEN:
            if w in blob:
                problems.append(f"{q}: 输出里出现敏感字样 {w!r}")
    return problems


def compare_official(rows, official_log):
    off = {r["question_id"]: r for r in jl(official_log)}
    print("\n== 与官方排序对比（前100名，按 turn_id）==")
    ok_all = True
    for r in rows:
        q = r["question_id"]
        m = {t["official_corpus_id"]: t["turn_id"] for t in jl(A01 / f"map/{q}.turns.jsonl")}
        theirs = [m[x["corpus_id"]] for x in off[q]["retrieval_results"]["ranked_items"][:100]]
        mine = [x["turn_id"] for x in r["candidates"]]
        same_order = theirs == mine
        same_set = set(theirs) == set(mine)
        first_diff = next((i + 1 for i, (a, b) in enumerate(zip(theirs, mine)) if a != b), None)
        print(f"{q}: 前100顺序完全一致={same_order}  集合一致={same_set}  首个不同名次={first_diff}")
        ok_all &= same_order
    print("结论:", "完全一致" if ok_all else "存在差异（可能是并列分数/数值精度，需逐项看）")
    return ok_all


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    rows = jl(sys.argv[1])
    problems = check_format(rows)
    print("格式检查:", "通过" if not problems else "")
    for p in problems:
        print(" -", p)
    matches = compare_official(rows, sys.argv[2]) if len(sys.argv) > 2 and not problems else True
    sys.exit(1 if problems or not matches else 0)
