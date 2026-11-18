"""
F03 盲判表產生器：把開發回答整理成人工判斷用的表格

【做什麼】
  讀入一或多個 E 回答檔，去除重複回答，打亂順序並改用編號，輸出兩個檔案：
    1. 盲判表（給判斷者）：只有題型、問題、參考答案、模型回答與空白的判斷欄
       —— 刻意不放 judge 結果與策略名稱，避免判斷受到影響
    2. 對照檔（判完才打開）：編號 → 來源檔、策略、設定雜湊等識別欄位

【去重規則】
  history_sha256 與 raw_output 都相同的回答只保留第一筆（依 --answers 的順序），
  其餘來源記在對照檔的 duplicate_of 欄位。例：E03 的 R 與 E02 預算版完全相同。

【用法】（在程式根目錄執行）
  .venv/bin/python src/evaluation/make_f03_sheet.py \
      --answers <回答檔1> <回答檔2> ... --out-dir f03 [--seed 20261117]

  同一組輸入與 seed 每次產生的編號都相同；已存在的輸出檔不會被覆蓋。
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import A01_OUTPUT  # noqa: E402

EVAL_FILE = A01_OUTPUT / "eval" / "dev_eval.jsonl"
QUESTIONS_FILE = A01_OUTPUT / "public" / "dev_questions.jsonl"

SHEET_COLUMNS = ["編號", "題型", "問題日期", "問題", "參考答案", "模型回答",
                 "人工判斷(1對/0錯)", "猜測(Y)", "不確定(Y)", "理由"]
KEY_COLUMNS = ["編號", "question_id", "source_file", "stage", "index", "strategy",
               "budget_tokens", "variant", "topk", "config_version", "reader_config_version",
               "record_id", "reader_config_id", "selection_config_id", "history_sha256",
               "duplicate_of"]


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    p = argparse.ArgumentParser(description="產生 F03 盲判表與對照檔")
    p.add_argument("--answers", nargs="+", required=True, help="E 回答檔（JSONL），可多個")
    p.add_argument("--out-dir", required=True, help="輸出資料夾")
    p.add_argument("--seed", type=int, default=20261117, help="打亂順序用的亂數種子")
    p.add_argument("--prefix", default="dev5", help="輸出檔名前綴")
    args = p.parse_args()

    evals = {r["question_id"]: r for r in read_jsonl(EVAL_FILE)}
    questions = {r["question_id"]: r for r in read_jsonl(QUESTIONS_FILE)}

    # 讀入並去重
    samples, seen = [], {}
    for path in args.answers:
        for a in read_jsonl(path):
            sig = (a["question_id"], a.get("history_sha256"), a.get("raw_output"))
            if sig in seen:
                seen[sig]["duplicate_of"].append(f"{path}#{a.get('strategy')}/{a.get('variant')}")
                continue
            item = {"answer": a, "source_file": path, "duplicate_of": []}
            seen[sig] = item
            samples.append(item)

    # 依題目分組（同一題連續判，標準較一致），組內與組間順序皆打亂
    rng = random.Random(args.seed)
    qids = sorted({s["answer"]["question_id"] for s in samples})
    rng.shuffle(qids)
    ordered = []
    for qid in qids:
        group = [s for s in samples if s["answer"]["question_id"] == qid]
        rng.shuffle(group)
        ordered.extend(group)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = out_dir / f"{args.prefix}_blind_sheet.csv"
    key_path = out_dir / f"{args.prefix}_key_DO_NOT_OPEN.csv"
    for path in (sheet_path, key_path):
        if path.exists():
            sys.exit(f"已存在 {path}，為避免覆蓋已填寫的判斷，請先改名或刪除")

    # utf-8-sig：讓 Excel 正確顯示中文
    with open(sheet_path, "w", newline="", encoding="utf-8-sig") as fs, \
         open(key_path, "w", newline="", encoding="utf-8-sig") as fk:
        ws, wk = csv.writer(fs), csv.writer(fk)
        ws.writerow(SHEET_COLUMNS)
        wk.writerow(KEY_COLUMNS)
        for i, s in enumerate(ordered, 1):
            a, qid = s["answer"], s["answer"]["question_id"]
            sid = f"S{i:02d}"
            ev, q = evals[qid], questions[qid]
            ws.writerow([sid, ev["question_type"], q.get("question_date", ""), q["question"],
                         str(ev["answer"]), (a.get("raw_output") or "").strip(), "", "", "", ""])
            wk.writerow([sid, qid, s["source_file"]]
                        + [a.get(k) for k in KEY_COLUMNS[3:-1]]
                        + ["; ".join(s["duplicate_of"])])

    print(f"讀入 {sum(len(read_jsonl(x)) for x in args.answers)} 筆，去重後 {len(ordered)} 筆，"
          f"{len(qids)} 題")
    print(f"盲判表：{sheet_path}")
    print(f"對照檔：{key_path}（判完再打開）")


if __name__ == "__main__":
    main()
