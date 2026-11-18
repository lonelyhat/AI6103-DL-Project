"""
F03 比對：人工判斷 vs judge

【做什麼】
  把盲判表（人工判斷）、對照檔（編號 → 來源與設定）和 judge 評分檔對起來，
  計算一致率、列出分歧，並輸出逐筆比對表。

【對應方式】
  對照檔每個編號記錄了「原始來源檔 + 策略 + 變體 + 題號」，
  以及被去重掉的重複回答（duplicate_of）。
  評分檔依 (question_id, strategy, variant, history_sha256) 找到對應的 judge 結果；
  同一編號的所有重複回答都必須找得到評分，且 judge 結果必須相同，否則列為問題。

【勾選欄】「Y」「V」「✓」（不分大小寫）視為有勾；空白或「N」視為沒勾。

【用法】
  .venv/bin/python src/evaluation/compare_f03.py \
      --sheet f03/dev5_blind_sheet.csv --key f03/dev5_key_DO_NOT_OPEN.csv \
      --scores scores/a.jsonl scores/b.jsonl --out f03/dev5_compare.csv
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict

CHECKED = {"y", "v", "✓", "✔"}
LABEL_COL = "人工判斷(1對/0錯)"


def checked(v):
    return (v or "").strip().lower() in CHECKED


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    p = argparse.ArgumentParser(description="F03 人工判斷與 judge 比對")
    p.add_argument("--sheet", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--scores", nargs="+", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    sheet = {r["編號"]: r for r in read_csv(args.sheet)}
    key = {r["編號"]: r for r in read_csv(args.key)}

    # 評分索引：(題號, 策略, 變體, 歷史雜湊) → 評分紀錄
    scores = defaultdict(list)
    for path in args.scores:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    s = json.loads(line)
                    scores[(s["question_id"], s.get("strategy"), s.get("variant"),
                            s.get("history_sha256"))].append(s)

    problems, rows = [], []
    for sid in sorted(sheet):
        h, k = sheet[sid], key[sid]
        label = (h.get(LABEL_COL) or "").strip()
        if label not in ("0", "1"):
            problems.append(f"{sid}：人工判斷不是 0/1（{label!r}）")
            continue
        # 這個編號代表的所有回答：本身 + 去重掉的重複
        members = [(k["strategy"], k["variant"])]
        for d in filter(None, (k.get("duplicate_of") or "").split("; ")):
            strat, var = d.split("#", 1)[1].split("/", 1)
            members.append((strat, var))
        judged = {}
        for strat, var in members:
            hit = scores.get((k["question_id"], strat, var, k["history_sha256"]), [])
            if hit:
                judged[f"{strat}/{var}"] = hit[-1]["label"]
        if not judged:
            problems.append(f"{sid}：找不到 judge 評分")
            continue
        if len(set(judged.values())) > 1:
            problems.append(f"{sid}：重複回答的 judge 結果不一致 {judged}")
        j = next(iter(judged.values()))
        rows.append({
            "編號": sid, "question_id": k["question_id"], "題型": h["題型"],
            "代表的設定": "、".join(f"{s}/{v}" for s, v in members),
            "judge 已評": "、".join(judged), "人工": int(label), "judge": j,
            "一致": "Y" if int(label) == j else "N",
            "猜測": "Y" if checked(h.get("猜測(Y)")) else "",
            "不確定": "Y" if checked(h.get("不確定(Y)")) else "",
            "理由": h.get("理由", ""),
        })

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    agree = sum(r["一致"] == "Y" for r in rows)
    conf = Counter((r["人工"], r["judge"]) for r in rows)
    print(f"不重複回答 {n} 筆：一致 {agree}，一致率 {agree / n:.3f}")
    print(f"  人工1/judge1 {conf[(1, 1)]}　人工0/judge0 {conf[(0, 0)]}　"
          f"人工1/judge0 {conf[(1, 0)]}　人工0/judge1 {conf[(0, 1)]}")
    for t in sorted({r["題型"] for r in rows}):
        sub = [r for r in rows if r["題型"] == t]
        print(f"  {t:28s} {sum(r['一致'] == 'Y' for r in sub)}/{len(sub)}")
    # 依設定展開（重複回答各算一次），方便和 judge 摘要對照
    expanded = sum(len(r["judge 已評"].split("、")) for r in rows)
    print(f"展開成 judge 已評的設定共 {expanded} 筆")
    flagged = [r["編號"] for r in rows if r["猜測"]]
    print(f"勾猜測：{flagged}（其中判 1 的：{[r['編號'] for r in rows if r['猜測'] and r['人工'] == 1]}）")
    print(f"勾不確定：{[r['編號'] for r in rows if r['不確定']]}")
    print("分歧：")
    for r in rows:
        if r["一致"] == "N":
            print(f"  {r['編號']} {r['question_id']} {r['代表的設定']}：人工 {r['人工']}、judge {r['judge']}")
    print("問題：" + ("無" if not problems else ""))
    for x in problems:
        print("  " + x)
    print(f"比對表：{args.out}")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
