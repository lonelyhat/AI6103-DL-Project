"""
產生評分程式的測試用輸入檔（A01 格式）

【為什麼需要】
評分程式要讀 A01 的兩個檔案：
    public/dev_questions.jsonl  → 問題原文
    eval/dev_eval.jsonl         → 題型、是否拒答、參考答案
但 A01 只為 40 道開發題產生這兩個檔案，而我們的 22 筆測試案例大多不在開發題中。
所以這支程式從官方資料中，替測試題目產生「同樣格式」的兩個檔案。

【只產生評分需要的欄位】
A01 的評價檔還有證據位置等欄位（給 A02 用），評分用不到，這裡不產生。

【使用方式】（在專案根目錄執行，只需執行一次；輸出已經放在 tests/fixtures/）
    .venv/bin/python tests/build_test_fixtures.py
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_DATA = PROJECT_ROOT / "data" / "longmemeval_s_cleaned.json"
OUT_DIR = PROJECT_ROOT / "tests" / "fixtures"

# 測試案例用到的題目：7 種題型 × 3 題，加上 1 題模擬「E 線回答失敗」
TEST_QUESTION_IDS = [
    "e47becba", "118b2229", "51a45a95",                  # single-session-user
    "c4f10528", "4c36ccef", "6ae235be",                  # single-session-assistant
    "8a2466db", "06878be2", "32260d93",                  # single-session-preference
    "0a995998", "6d550036", "gpt4_d84a3211",             # multi-session
    "gpt4_76048e76", "2c63a862", "gpt4_2312f94c",        # temporal-reasoning
    "852ce960", "6a1eabeb", "945e3d21",                  # knowledge-update
    "0862e8bf_abs", "982b5123_abs", "eeda8a6d_abs",      # abstention
    "1e043500",                                          # E 線回答失敗（不會送去評分）
]


def main():
    with open(OFFICIAL_DATA, encoding="utf-8") as f:
        official = {e["question_id"]: e for e in json.load(f)}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "test_questions.jsonl", "w", encoding="utf-8") as fq, \
         open(OUT_DIR / "test_eval.jsonl", "w", encoding="utf-8") as fe:
        for qid in TEST_QUESTION_IDS:
            e = official[qid]
            # 對應 A01 第 4.1 節：public/dev_questions.jsonl 的欄位
            fq.write(json.dumps({
                "question_id": qid,
                "stage": "dev",
                "question": e["question"],
                "question_date": e["question_date"],
            }, ensure_ascii=False) + "\n")
            # 對應 A01 第 4.2 節：eval/dev_eval.jsonl 中評分會用到的欄位
            fe.write(json.dumps({
                "question_id": qid,
                "question_type": e["question_type"],
                "is_abstention": qid.endswith("_abs"),
                "answer": e["answer"],
            }, ensure_ascii=False) + "\n")
    print(f"已產生 {len(TEST_QUESTION_IDS)} 題 → {OUT_DIR}")


if __name__ == "__main__":
    main()
