"""
產生 F02 串聯程式的測試資料

【資料來源】
  1. A02 提供的範例：AI6103-DL-Project-main_V1/A-数据线/A02/examples/sample_selections.jsonl
     （2318644b 的兩筆選中材料：R 只留下一條證據、Q 兩條都留下）→ 原樣複製，不修改
  2. 另外補上首批題目中的兩題，讓四種結果都有例子：
     4c36ccef：證據在助手回覆裡，K0 候選中沒有證據 → 預期「沒找到」
     c960da58：證據有被選中，且答對 → 預期「答對」
  3. 候選、評分、每輪 token 數都是「模擬」的，只用來測試程式流程，不代表真實結果。

【刻意放入的資料問題】（用來檢查程式能不能發現）
  - A02 範例的 config_version 是舊版 a01-v1，候選檔是 a01-v2 → 應記錄「config_version 不一致」
    （2026-11-17 起 config_version 是對應鍵，評分紀錄改成與 A02 範例相同的 a01-v1）
  - c960da58 的評分標記 E/F 提取不一致 → 應記錄
  - 1cea1afa 只有評分、沒有選中材料 → 應記錄「評分檔有、選中檔沒有」

【使用方式】（在專案根目錄執行）
    .venv/bin/python tests/f02/build_f02_fixtures.py
"""

import json
from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "evaluation"))
from paths import A_LINE, A01_OUTPUT as A01_OUT  # noqa: E402  （組內專案路徑統一由 paths.py 決定）
A02_EXAMPLE = A_LINE / "A02" / "examples" / "sample_selections.jsonl"
OUT = PROJECT_ROOT / "tests" / "f02"

COMMON = {"stage": "dev", "index": "K0", "budget_tokens": 2048,
          "tokenizer": "meta-llama/Llama-3.1-8B-Instruct", "config_version": "a01-v2"}


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def all_turn_ids(qid):
    """依 A01 的映射檔列出一題的全部輪 ID。"""
    return [t["turn_id"] for t in load_jsonl(A01_OUT / "map" / f"{qid}.turns.jsonl")]


def fake_candidates(qid, must_include, must_exclude=()):
    """
    模擬 B 線的前 100 名候選：先放入指定的輪，再依序補其他輪到 100 個。
    分數與排名都是假的。
    """
    ids = list(must_include)
    for t in all_turn_ids(qid):
        if len(ids) >= 100:
            break
        if t not in ids and t not in must_exclude:
            ids.append(t)
    return {"question_id": qid, **COMMON, "strategy": None,
            "candidates": [{"turn_id": t, "rank": i + 1, "score": round(1 - i * 0.005, 3)}
                           for i, t in enumerate(ids)]}


def fake_score(qid, strategy, label, extract_agrees=True, config_version=None):
    """
    模擬 judge.py 輸出的評分紀錄（只放串聯會用到的欄位）。
    2026-11-17 起 config_version 也是對應鍵，所以評分紀錄的版本必須與選中紀錄相同；
    A02 範例是 a01-v1，對應的評分也要設成 a01-v1。
    """
    common = dict(COMMON, config_version=config_version or COMMON["config_version"])
    return {"question_id": qid, **common, "strategy": strategy, "status": "ok", "label": label,
            "judge_output": "Yes" if label else "No", "response_sent": "（模擬回答）",
            "extract_agrees": extract_agrees, "parse_status": "clean"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- 選中材料：A02 範例 2 筆（原樣）+ 補充 2 筆 ----
    selections = load_jsonl(A02_EXAMPLE)
    selections.append({"question_id": "4c36ccef", **COMMON, "strategy": "R",
                       "selected_turn_ids": ["4c36ccef-s000-t000", "4c36ccef-s001-t000"],
                       "context_tokens": 1500, "_note": "補充：證據不在候選中"})
    selections.append({"question_id": "c960da58", **COMMON, "strategy": "R",
                       "selected_turn_ids": ["c960da58-s004-t001", "c960da58-s000-t000"],
                       "context_tokens": 900, "_note": "補充：證據有選中"})
    write_jsonl(OUT / "selections_dev_K0.jsonl", selections)

    # ---- 候選：2318644b 含兩條證據；4c36ccef 刻意排除證據輪；c960da58 含證據 ----
    candidates = [
        fake_candidates("2318644b", ["2318644b-s016-t000", "2318644b-s020-t001",
                                     "2318644b-s000-t000", "2318644b-s001-t000"]),
        fake_candidates("4c36ccef", ["4c36ccef-s000-t000", "4c36ccef-s001-t000"],
                        must_exclude=["4c36ccef-s046-t001"]),
        fake_candidates("c960da58", ["c960da58-s004-t001", "c960da58-s000-t000"]),
    ]
    write_jsonl(OUT / "candidates_dev_K0.jsonl", candidates)

    # ---- 評分 ----
    scores = [
        fake_score("2318644b", "R", 0, config_version="a01-v1"),  # 只留一條證據 → 答錯
        fake_score("2318644b", "Q", 1, config_version="a01-v1"),  # 兩條都留 → 答對
        fake_score("4c36ccef", "R", 0),                         # 沒找到證據 → 答錯
        fake_score("c960da58", "R", 1, extract_agrees=False),   # 答對，但 E/F 提取不一致
        fake_score("1cea1afa", "R", 1),                         # 沒有對應的選中材料
    ]
    write_jsonl(OUT / "scores_dev_K0.jsonl", scores)

    # ---- 每輪 token 數（粗估：字元數 ÷ 4；正式使用時須用 D02 的實際計數） ----
    turn_tokens = {}
    for qid in ["2318644b", "4c36ccef", "c960da58"]:
        for t in load_jsonl(A01_OUT / "public" / "turns" / f"{qid}.jsonl"):
            chars = sum(len(m["content"]) for m in t["messages"])
            turn_tokens[t["turn_id"]] = max(1, chars // 4)
    with open(OUT / "turn_tokens_approx.json", "w", encoding="utf-8") as f:
        json.dump(turn_tokens, f)

    print(f"已產生測試資料 → {OUT}")


if __name__ == "__main__":
    main()
