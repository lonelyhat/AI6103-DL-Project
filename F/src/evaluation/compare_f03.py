"""
F03 比對：人工判斷 vs judge

【做什麼】
  把盲判表（人工判斷）、成員檔（編號 → 每一筆來源紀錄）和 judge 評分檔對起來，
  計算一致率、列出分歧，並輸出逐筆比對表。

【對應方式】（2026-11-18 依 E 線審閱回覆第 1 點改寫）
  一個盲判編號可能代表多筆來源紀錄（內容相同而被去重，例如 E03 的 R 與 E02 預算版）。
  成員檔把每一筆來源紀錄都列出來（含被去重的），記錄來源檔、行號、
  完整識別鍵（與 judge.py 的 record_key 相同）和回答指紋。

  比對時「每一個成員」都必須：
    1. 來源檔那一行的內容和產生盲判表時相同（指紋一致）；
    2. 在評分檔中找得到自己識別鍵的評分（不共用其他成員的分數）；
    3. 該評分是針對這份回答評的（answer_sha256 或相容規則），且不是 api_error；
    4. 若同一識別鍵在多個評分檔都有紀錄，分數必須相同。
  同一編號所有成員的 judge 分數也必須相同。
  任何一項不符都列為問題，校準狀態標為「未完成」，並以退出碼 1 結束。

【樣本數的三種算法】（報告時照這個寫）
  來源紀錄：成員檔的列數
  設定紀錄：依 (題號, 策略, 變體, 預算, topk) 合併跨批重複後的數目
  不重複回答：盲判表的列數（依題號、歷史、原始輸出去重）

【勾選欄】「Y」「V」「✓」（不分大小寫）視為有勾；空白或「N」視為沒勾。

【用法】
  .venv/bin/python src/evaluation/compare_f03.py \
      --sheet f03/dev5_blind_sheet.csv --members f03/dev5_members_DO_NOT_OPEN.csv \
      --scores scores/a.jsonl scores/b.jsonl --out f03/dev5_compare.csv
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from judge import answer_fingerprint, final_label, load_jsonl, record_key, score_matches_answer  # noqa: E402

CHECKED = {"y", "v", "✓", "✔"}
LABEL_COL = "人工判斷(1對/0錯)"


def checked(v):
    return (v or "").strip().lower() in CHECKED


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    p = argparse.ArgumentParser(description="F03 人工判斷與 judge 比對")
    p.add_argument("--sheet", required=True, help="填好的盲判表")
    p.add_argument("--members", required=True, help="成員檔 *_members_DO_NOT_OPEN.csv")
    p.add_argument("--scores", nargs="+", required=True, help="judge 評分檔，可多個")
    p.add_argument("--out", required=True, help="逐筆比對表輸出路徑")
    args = p.parse_args()

    sheet = {r["編號"]: r for r in read_csv(args.sheet)}
    members = defaultdict(list)
    for m in read_csv(args.members):
        members[m["編號"]].append(m)

    # 評分索引：識別鍵 → [(評分檔, 該檔中此鍵的最後一筆)]
    scores = defaultdict(list)
    for path in args.scores:
        latest = {}
        for s in load_jsonl(path):
            latest[record_key(s)] = s
        for k, s in latest.items():
            scores[k].append((path, s))

    source_cache = {}

    def load_source(path, line_no):
        if path not in source_cache:
            source_cache[path] = load_jsonl(path) if Path(path).exists() else None
        rows = source_cache[path]
        return rows[line_no - 1] if rows and 0 < line_no <= len(rows) else None

    problems, rows, settings = [], [], set()
    for sid in sorted(set(sheet) | set(members)):
        if sid not in sheet:
            problems.append(f"{sid}：成員檔有、盲判表沒有")
            continue
        if sid not in members:
            problems.append(f"{sid}：盲判表有、成員檔沒有")
            continue
        h = sheet[sid]
        label = (h.get(LABEL_COL) or "").strip()
        if label not in ("0", "1"):
            problems.append(f"{sid}：人工判斷不是 0/1（{label!r}）")
            continue

        judged = {}            # 成員名稱 → judge 最終分數
        for m in members[sid]:
            name = f"{m['strategy']}/{m['variant']}@{Path(m['source_file']).parent.name}"
            a = load_source(m["source_file"], int(m["line_no"]))
            if a is None:
                problems.append(f"{sid}：找不到來源 {m['source_file']} 第 {m['line_no']} 行")
                continue
            if record_key(a) != m["record_key"] or answer_fingerprint(a) != m["answer_sha256"]:
                problems.append(f"{sid}：{name} 的來源內容和產生盲判表時不同（E 可能重新匯出過）")
                continue
            settings.add((a["question_id"], a.get("strategy"), a.get("variant"),
                          a.get("budget_tokens"), a.get("topk")))
            hits = scores.get(m["record_key"], [])
            if not hits:
                problems.append(f"{sid}：{name} 沒有評分")
                continue
            labels = {}
            for path, s in hits:
                if s.get("status") not in ("ok", "no_answer"):
                    problems.append(f"{sid}：{name} 在 {path} 的評分未完成（status={s.get('status')}）")
                elif not score_matches_answer(s, a):
                    problems.append(f"{sid}：{name} 在 {path} 的評分對應的是舊的回答內容")
                else:
                    labels[path] = final_label(s)
            if len(set(labels.values())) > 1:
                problems.append(f"{sid}：{name} 在不同評分檔的分數衝突 {labels}")
            elif labels:
                judged[name] = next(iter(labels.values()))

        names = [f"{m['strategy']}/{m['variant']}@{Path(m['source_file']).parent.name}"
                 for m in members[sid]]
        if len(judged) < len(names):
            continue           # 有成員缺評分，問題已列出，不計入一致率
        if len(set(judged.values())) > 1:
            problems.append(f"{sid}：同一份回答的成員 judge 分數不一致 {judged}")
            continue
        j = next(iter(judged.values()))
        rows.append({
            "編號": sid, "question_id": members[sid][0]["question_id"], "題型": h["題型"],
            "成員數": len(names), "成員（皆已評）": "、".join(names),
            "人工": int(label), "judge": j, "一致": "Y" if int(label) == j else "N",
            "猜測": "Y" if checked(h.get("猜測(Y)")) else "",
            "不確定": "Y" if checked(h.get("不確定(Y)")) else "",
            "理由": h.get("理由", ""),
        })

    if rows:
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    n_members = sum(len(v) for v in members.values())
    print(f"樣本：來源紀錄 {n_members} 筆 → 設定紀錄 {len(settings)} 筆 → 不重複回答 {len(sheet)} 筆")
    n = len(rows)
    agree = sum(r["一致"] == "Y" for r in rows)
    if n:
        conf = Counter((r["人工"], r["judge"]) for r in rows)
        print(f"可比對的回答 {n} 筆：一致 {agree}/{n}")
        print(f"  人工1/judge1 {conf[(1, 1)]}　人工0/judge0 {conf[(0, 0)]}　"
              f"人工1/judge0 {conf[(1, 0)]}　人工0/judge1 {conf[(0, 1)]}")
        for t in sorted({r["題型"] for r in rows}):
            sub = [r for r in rows if r["題型"] == t]
            print(f"  {t:28s} {sum(r['一致'] == 'Y' for r in sub)}/{len(sub)}")
        print(f"勾猜測：{[r['編號'] for r in rows if r['猜測']]}"
              f"（其中判 1 的：{[r['編號'] for r in rows if r['猜測'] and r['人工'] == 1]}）")
        print(f"勾不確定：{[r['編號'] for r in rows if r['不確定']]}")
        print("分歧：")
        for r in rows:
            if r["一致"] == "N":
                print(f"  {r['編號']} {r['question_id']} {r['成員（皆已評）']}：人工 {r['人工']}、judge {r['judge']}")
    print("問題：" + ("無" if not problems else ""))
    for x in problems:
        print("  " + x)
    if rows:
        print(f"比對表：{args.out}")
    if problems:
        print("校準狀態：未完成（請先處理上面的問題）")
        sys.exit(1)
    print("校準狀態：完整（每個成員都有自己的評分且一致）")


if __name__ == "__main__":
    main()
