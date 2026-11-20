"""
F06 主結果與差值區間

【做什麼】（任務表 F06；口徑依 G02 README 與《项目解释和大纲》第三、四節）
  讀入 F04 的正式評分、A03 的證據組、A04 的證據指標，輸出：
    1. 主結果表：十種設定（K0/K1 × R/MMR/C/Q/FL）的正確率、證據保留、材料長度
    2. 配對差值：同題由錯變對／由對變錯的題數、差值與 95% 信賴區間
         覆蓋增量  Q − R、Q − MMR、Q − C、Q − FL（各索引）
         事實增量  K1 − K0（各策略），以及 K1-R − K0-Q
         交互變化  I = (Q1 − C1) − (Q0 − C0)
    3. 證據與回答：A04 的四類診斷（候選沒找齊、放不下、沒選到、證據齊全）× 答對／答錯
    4. 逐題表：每題十種設定的分數與證據診斷（供 A05 選案例）

【信賴區間】
  按題配對：每題算一個差值 d（1、0 或 −1；交互項可到 ±2）。
  共享證據的題目不獨立（A03 的 80 題屬於 78 個證據組），
  因此以「證據組」為單位重抽樣（cluster bootstrap）：每次有放回地抽 78 組，
  差值 = 抽到的題目 d 的總和 ÷ 抽到的題數；重複 B 次取 2.5% 與 97.5% 分位數。
  80 題時一題 = 1.25 個百分點。

【檢查】（任一項不符即停止）
  評分檔 800 筆＝題單 80 題 × 10 種設定、每筆 status 為 ok 或 no_answer、無重複；
  A04 每筆設定都有對應的證據指標，且 history_sha256 與評分一致（同一份材料）；
  每題都有證據組。

【F05】
  依 SCORING_CONFIG 第六節，主要準確率用 judge 分數，人工抽查只估計 judge 可靠度，
  不替換分數；F05 完成後另外補上人工對照，本程式結果不受影響。

【用法】（在程式根目錄執行；A03/A04 預設讀組內 repo，見 paths.py）
  .venv/bin/python src/evaluation/f06_analysis.py \
      --scores scores/formal_g02-v1_all.jsonl --out-dir f06
  直接讀團隊歸檔的 8 批（在組內 repo 的 F/ 目錄執行）：
  python src/evaluation/f06_analysis.py \
      --scores scores/formal_g02-v1_batch-0{1,2,3,4,5,6,7,8}.jsonl --out-dir F06
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge import final_label, load_jsonl  # noqa: E402
from paths import A_LINE  # noqa: E402

INDEXES = ["K0", "K1"]
STRATEGIES = ["R", "MMR", "C", "Q", "FL"]
SETTINGS = [(i, s) for i in INDEXES for s in STRATEGIES]
DIAGNOSES = [  # A04 的診斷 → 《大纲》的四類錯誤來源
    ("candidates_missing", "候選沒找齊"),
    ("minimal_cover_over_budget", "證據放不下"),
    ("selection_missed", "可放下但沒選齊"),
    ("all_retained", "證據齊全"),
]


def parse_args():
    p = argparse.ArgumentParser(description="F06 主結果與差值區間")
    p.add_argument("--scores", nargs="+", required=True,
                   help="F04 正式評分檔，可給多個（例如團隊歸檔的 8 批），合起來須剛好 800 筆、無重複")
    p.add_argument("--questions", default=str(A_LINE / "A03/output/public/formal_questions.jsonl"))
    p.add_argument("--audit", default=str(A_LINE / "A03/output/eval/selection_audit.jsonl"),
                   help="A03 題目篩選紀錄（含 evidence_group）")
    p.add_argument("--metrics", default=str(A_LINE / "A04/output/selection_metrics.jsonl"),
                   help="A04 選材證據指標")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--bootstrap", type=int, default=10000, help="重抽樣次數")
    p.add_argument("--seed", type=int, default=20261120)
    return p.parse_args()


def load_inputs(args):
    """讀入並檢查四個輸入，回傳 (題號清單, 證據組, 分數[題][設定], 證據指標[題][設定], 題型)。"""
    problems = []
    qids = [r["question_id"] for r in load_jsonl(args.questions)]
    qset = set(qids)

    group = {r["question_id"]: r["evidence_group"] for r in load_jsonl(args.audit) if r.get("selected")}
    if set(group) != qset:
        problems.append(f"證據組與題單不一致：缺 {sorted(qset - set(group))[:5]}、多 {sorted(set(group) - qset)[:5]}")

    label, qtype, history = defaultdict(dict), {}, {}
    seen = Counter()
    for r in (x for path in args.scores for x in load_jsonl(path)):
        key = (r["question_id"], r["index"], r["strategy"])
        seen[key] += 1
        if r.get("stage") != "formal":
            problems.append(f"{key}：stage 不是 formal")
        if r["status"] not in ("ok", "no_answer"):
            problems.append(f"{key}：評分未完成（status={r['status']}）")
            continue
        label[r["question_id"]][(r["index"], r["strategy"])] = final_label(r)
        qtype[r["question_id"]] = r["question_type"]
        history[key] = r.get("history_sha256")
    dup = [k for k, n in seen.items() if n > 1]
    if dup:
        problems.append(f"評分檔有重複紀錄 {len(dup)} 筆（請用團隊歸檔的評分檔，或每筆只留一次的合併檔），例如 {dup[0]}")
    missing = [(q, i, s) for q in qids for (i, s) in SETTINGS if (i, s) not in label.get(q, {})]
    if missing:
        problems.append(f"缺評分 {len(missing)} 筆，例如 {missing[:3]}")
    extra = set(label) - qset
    if extra:
        problems.append(f"評分檔有題單以外的題目：{sorted(extra)[:5]}")

    metrics = defaultdict(dict)
    for m in load_jsonl(args.metrics):
        key = (m["question_id"], m["index"], m["strategy"])
        metrics[m["question_id"]][(m["index"], m["strategy"])] = m
        if key in history and history[key] != m.get("history_sha256"):
            problems.append(f"{key}：評分與 A04 的 history_sha256 不同（不是同一份材料）")
    miss_m = [(q, i, s) for q in qids for (i, s) in SETTINGS if (i, s) not in metrics.get(q, {})]
    if miss_m:
        problems.append(f"A04 缺證據指標 {len(miss_m)} 筆，例如 {miss_m[:3]}")

    if problems:
        print("[停止] 輸入檢查未通過：")
        for x in problems[:20]:
            print("  - " + x)
        sys.exit(1)
    return qids, group, label, metrics, qtype


def cluster_bootstrap(diff, group, n_boot, seed):
    """以證據組為單位重抽樣，回傳 (2.5%, 97.5%) 分位數。diff：{題號: 差值}。"""
    by_group = defaultdict(list)
    for q, d in diff.items():
        by_group[group[q]].append(d)
    sums = [(sum(v), len(v)) for v in by_group.values()]
    rng = random.Random(seed)
    k = len(sums)
    stats = []
    for _ in range(n_boot):
        tot = cnt = 0
        for _ in range(k):
            s, n = sums[rng.randrange(k)]
            tot += s
            cnt += n
        stats.append(tot / cnt)
    stats.sort()
    return stats[int(0.025 * n_boot)], stats[int(0.975 * n_boot) - 1]


def pct(x):
    return f"{100 * x:+.1f}" if x is not None else ""


def main():
    args = parse_args()
    qids, group, label, metrics, qtype = load_inputs(args)
    n = len(qids)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---- 1. 主結果表 ----
    main_rows = []
    for (i, s) in SETTINGS:
        ms = [metrics[q][(i, s)] for q in qids]
        main_rows.append({
            "索引": i, "策略": s,
            "答對題數": sum(label[q][(i, s)] for q in qids), "題數": n,
            "正確率": round(sum(label[q][(i, s)] for q in qids) / n, 4),
            "證據齊全題數": sum(m["selected"]["all_retained"] for m in ms),
            "平均消息級保留率": round(sum(m["selected"]["msg_retention"] for m in ms) / n, 4),
            "平均材料長度(token)": round(sum(m["context_tokens"] for m in ms) / n, 1),
        })

    # ---- 2. 配對差值 ----
    def y(q, i, s):
        return label[q][(i, s)]

    comparisons = []
    for i in INDEXES:  # 覆蓋增量：Q 對其他策略
        for other in ["R", "MMR", "C", "FL"]:
            comparisons.append(("覆蓋", f"{i}: Q − {other}", (i, "Q"), (i, other)))
    for s in STRATEGIES:  # 事實增量：同策略 K1 − K0
        comparisons.append(("事實", f"{s}: K1 − K0", ("K1", s), ("K0", s)))
    comparisons.append(("事實", "K1-R − K0-Q（只加事實 vs 只加覆蓋）", ("K1", "R"), ("K0", "Q")))

    diff_rows = []
    for kind, name, a, b in comparisons:
        d = {q: y(q, *a) - y(q, *b) for q in qids}
        lo, hi = cluster_bootstrap(d, group, args.bootstrap, args.seed)
        diff_rows.append({
            "類別": kind, "比較": name,
            "A 答對": sum(y(q, *a) for q in qids), "B 答對": sum(y(q, *b) for q in qids),
            "錯→對（A 對 B 錯）": sum(v == 1 for v in d.values()),
            "對→錯（A 錯 B 對）": sum(v == -1 for v in d.values()),
            "差值(百分點)": pct(sum(d.values()) / n),
            "95%CI 下限": pct(lo), "95%CI 上限": pct(hi),
        })
    # 交互變化 I = (Q1 − C1) − (Q0 − C0)
    d = {q: (y(q, "K1", "Q") - y(q, "K1", "C")) - (y(q, "K0", "Q") - y(q, "K0", "C")) for q in qids}
    lo, hi = cluster_bootstrap(d, group, args.bootstrap, args.seed)
    diff_rows.append({
        "類別": "交互", "比較": "I = (Q1 − C1) − (Q0 − C0)",
        "A 答對": "", "B 答對": "",
        "錯→對（A 對 B 錯）": f"I>0 的題 {sum(v > 0 for v in d.values())}",
        "對→錯（A 錯 B 對）": f"I<0 的題 {sum(v < 0 for v in d.values())}",
        "差值(百分點)": pct(sum(d.values()) / n), "95%CI 下限": pct(lo), "95%CI 上限": pct(hi),
    })

    # ---- 3. 證據診斷 × 答對答錯 ----
    diag_rows = []
    for (i, s) in SETTINGS:
        row = {"索引": i, "策略": s}
        for code, name in DIAGNOSES:
            qs = [q for q in qids if metrics[q][(i, s)]["diagnosis"] == code]
            row[f"{name}(對/總)"] = f"{sum(label[q][(i, s)] for q in qs)}/{len(qs)}"
        other = [q for q in qids if metrics[q][(i, s)]["diagnosis"] not in dict(DIAGNOSES)]
        if other:
            row["其他診斷"] = len(other)
        diag_rows.append(row)

    # ---- 4. 逐題表 ----
    per_q = []
    for q in qids:
        row = {"question_id": q, "題型": qtype[q], "證據組": group[q]}
        row.update({f"{i}-{s}": label[q][(i, s)] for (i, s) in SETTINGS})
        row["十種設定答對數"] = sum(label[q][x] for x in SETTINGS)
        row.update({f"診斷 {i}-{s}": metrics[q][(i, s)]["diagnosis"] for (i, s) in SETTINGS})
        per_q.append(row)

    def write(name, rows):
        fields = list(dict.fromkeys(k for r in rows for k in r))
        with open(out / name, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write("f06_main_table.csv", main_rows)
    write("f06_paired_diffs.csv", diff_rows)
    write("f06_evidence_by_outcome.csv", diag_rows)
    write("f06_per_question.csv", per_q)

    # ---- 畫面摘要 ----
    print(f"輸入檢查通過：{n} 題 × {len(SETTINGS)} 種設定 = {n * len(SETTINGS)} 筆；"
          f"證據組 {len(set(group.values()))} 個；bootstrap {args.bootstrap} 次（seed {args.seed}）")
    print("\n[主結果]")
    print(f"  {'設定':8s} {'正確率':>8s} {'證據齊全':>8s} {'保留率':>8s} {'長度':>7s}")
    for r in main_rows:
        print(f"  {r['索引']}-{r['策略']:5s} {r['正確率']:8.3f} {r['證據齊全題數']:5d}/{n} "
              f"{r['平均消息級保留率']:8.3f} {r['平均材料長度(token)']:7.0f}")
    print("\n[配對差值]（百分點；一題 = %.2f）" % (100 / n))
    for r in diff_rows:
        print(f"  {r['比較']:34s} {r['差值(百分點)']:>6s}  [{r['95%CI 下限']:>6s}, {r['95%CI 上限']:>6s}]  "
              f"{r['錯→對（A 對 B 錯）']} / {r['對→錯（A 錯 B 對）']}")
    print(f"\n輸出：{out}/f06_main_table.csv、f06_paired_diffs.csv、f06_evidence_by_outcome.csv、f06_per_question.csv")
    print("提醒：主要準確率用 judge 分數；F05 人工抽查完成後另補 judge 可靠度，不替換分數。")


if __name__ == "__main__":
    main()
