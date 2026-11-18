"""
F02 串聯程式：把「候選、選中材料、官方證據、評分」接成每題一列

【這支程式做什麼】
對每一題、每一種設定（index / strategy / budget），回答四個問題：
  1. 檢索候選（B 線）有沒有找齊證據？        → 用 A02 計算候選的證據保留率
  2. 選中材料（D 線）有沒有留下證據？        → 用 A02 計算選中材料的證據保留率
  3. 證據是在哪個環節丟掉的？                → 用 A02 的 diagnose() 歸因
  4. 最後答對了嗎？                          → 讀 F 線的評分檔
並把過程中發現的資料問題逐筆記錄下來（F02 完成標準：「發現的映射、解析和評分問題有記錄」）。

【輸入（皆為 A01 第 4.3 節格式）】
  --candidates  B 候選檔   candidates/{stage}_{index}.jsonl        欄位 candidates: [{turn_id, rank, score}]
  --selections  D 選中檔   selections/{stage}_{index}_{strategy}_{budget}.jsonl  欄位 selected_turn_ids
  --scores      F 評分檔   scores/{同上}.jsonl                     （judge.py 的輸出）
  --turn-tokens 每輪 token 數（選填）  {"turn_id": token 數, ...}
                有提供才能區分「放不下（over_budget）」與「沒選到（selection_missed）」；
                A02 文件第 2 節說明 token 數應依 D02 實際渲染格式計算，正式使用時請向 D 線索取。

【輸出】
  --out 指定的 JSONL（每題每設定一列），以及同名的 .csv（可用 Excel 開啟）

【證據口徑】
  完全沿用 A02（Nathan）的 evidence_metrics.py：以「消息級 has_answer」為準，
  不用官方輪級標記（原因見 A02 文件第 1 節）。拒答題不參與證據平均。

【使用方式】（詳見 EVAL_NOTES.md）
  .venv/bin/python src/evaluation/join_f02.py --candidates candidates/dev_K0.jsonl \
      --selections selections/dev_K0_R_2048.jsonl --scores scores/dev_K0_R_2048.jsonl \
      --out f02/dev_K0_R_2048.jsonl
"""

# ===========================================================================
# 0. 匯入
# ===========================================================================
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 路徑統一在 paths.py 設定（本機與組內 repo 都適用）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import A02_DIR  # noqa: E402

# A02 的程式放在組內專案裡；把它的資料夾加入搜尋路徑後即可 import
sys.path.insert(0, str(A02_DIR))
from evidence_metrics import Evidence  # noqa: E402  （A02 的證據計算類別）


# ===========================================================================
# 1. 設定
# ===========================================================================
# A01 第 4.3 節的公共欄位
COMMON_FIELDS = ["question_id", "stage", "index", "strategy",
                 "budget_tokens", "tokenizer", "config_version"]

# 「選中材料」和「評分」用這些欄位對應（同一題、同一設定）
#   2026-11-17 起加入 config_version、variant、topk（依 E02 交接補丁），
#   避免預算版（variant=budget）和 top-50 參照版（variant=original_topk）的結果混在一起。
#   舊資料沒有 variant 時視為 budget（見 make_key）。
SELECTION_KEY = ["question_id", "stage", "index", "strategy", "budget_tokens",
                 "config_version", "variant", "topk"]
DEFAULT_VARIANT = "budget"
# 「候選」只跟索引有關（同一索引下五種選擇辦法共用同一份候選），所以只用 3 個欄位對應
CANDIDATE_KEY = ["question_id", "stage", "index"]

# A02 diagnose() 的歸因結果 → 任務表 A05 的四類錯誤（答錯時才使用）
OUTCOME_IF_WRONG = {
    "candidates_missing": "沒找到",        # 候選裡就沒有找齊證據
    "over_budget": "放不下",               # 證據都在候選中，但最少也要超過預算才放得下
    "selection_missed": "沒選到",          # 放得下卻沒選齊（未提供 token 數時，也包含放不下的情況）
    "all_retained": "選到仍答錯",          # 證據全部留下，問題在閱讀、提取或評分
    "no_evidence": "無證據題",             # 沒有證據標註的題目（例如部分拒答題）
}


# ===========================================================================
# 2. 讀檔工具
# ===========================================================================
def load_jsonl(path):
    """讀 JSONL（每行一筆），回傳 list。"""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def make_key(record, fields):
    """用指定欄位組成對應用的鍵，例如 ("2318644b", "dev", "K0", "R", 2048)。"""
    return tuple(record.get(k, DEFAULT_VARIANT if k == "variant" else None) for k in fields)


def index_records(records, fields, file_label, issues):
    """
    把一個檔案的紀錄依鍵放進 dict。
    同一個鍵出現兩次代表檔案有重複紀錄：保留最後一筆，並記錄問題。
    （評分檔因為支援斷點續跑，同一題可能先失敗後成功，取最後一筆是正確的做法，不算問題。）
    """
    table = {}
    for r in records:
        k = make_key(r, fields)
        if k in table and file_label != "scores":
            issues.append({"key": k, "type": "duplicate_record",
                           "detail": f"{file_label} 檔中同一筆紀錄出現多次，保留最後一筆"})
        table[k] = r
    return table


# ===========================================================================
# 3. 每一列的檢查與計算
# ===========================================================================
def check_config_match(selection, other, other_label):
    """
    檢查兩個檔案的設定版本與分詞器是否一致。
    不一致代表兩邊用了不同版本的規則，結果不能直接比較，需要記錄。

    【候選的版本要另外對照】
      B（候選）和 D（選中）是不同階段，版本號本來就不同（例如 B 是 a01-v2、D 是 d02-v1）。
      D 會另外記錄它依據的 B 版本 input_config_version（在最外層或 config 裡），
      所以比對候選時改用這個值；沒有記錄時才退回比較 config_version。
    """
    problems = []
    for field in ("config_version", "tokenizer"):
        expected = selection.get(field)
        if other_label == "candidates" and field == "config_version":
            expected = selection.get("input_config_version",
                                     (selection.get("config") or {}).get("input_config_version", expected))
        if other.get(field) != expected:
            problems.append(f"{field} 不一致：selections={selection.get(field)!r}，"
                            f"{other_label}={other.get(field)!r}")
    return problems


def evidence_block(evidence, qid, turn_ids, prefix):
    """
    呼叫 A02 計算證據保留指標，並在欄位名稱前加上前綴（cand_ 或 sel_）。
    A02 遇到「不屬於本題的輪 ID」或「未知輪 ID」會直接報錯；這裡接住錯誤並回傳錯誤訊息，
    讓程式繼續處理其他題目，同時把問題記錄下來。
    """
    try:
        m = evidence.retention(qid, turn_ids)
    except (KeyError, ValueError) as e:
        return {f"{prefix}error": str(e)}, f"A02 無法計算{prefix[:-1]}證據：{e}"
    keep = ["n_turns_given", "n_evidence_msgs", "n_retained_msgs",
            "msg_retention", "all_retained", "missing_message_ids"]
    return {f"{prefix}{k}": m[k] for k in keep}, None


def tokens_from_d02(selection):
    """
    從 D02 選中紀錄的 candidate_trials 取出每個候選輪的 token 數，回傳 {turn_id: tokens}。
    使用 standalone_context_tokens：該輪單獨序列化（含 session 標頭）後的 token 數，
    由 D02 用閱讀模型的 tokenizer 實際計算，比「字元數 ÷ 4」準確。
    沒有 candidate_trials（例如 top-k 參照版、舊格式）時回傳 None。
    """
    trials = selection.get("candidate_trials")
    if not trials:
        return None
    return {t["turn_id"]: t["standalone_context_tokens"] for t in trials
            if t.get("standalone_context_tokens") is not None}


def build_row(selection, candidate, score, evidence, turn_tokens):
    """
    組出一列：公共欄位 + 候選證據 + 選中證據 + 歸因 + 評分 + 問題清單。
    candidate 或 score 可能是 None（對應不到），此時相關欄位留空並記錄問題。
    """
    qid = selection["question_id"]
    ev = evidence.eval[qid]
    issues = []

    row = {k: selection.get(k) for k in COMMON_FIELDS}
    row["variant"] = selection.get("variant", DEFAULT_VARIANT)
    row["topk"] = selection.get("topk")
    row["question_type"] = ev["question_type"]
    row["is_abstention"] = ev["is_abstention"]
    row["answer"] = ev["answer"]

    selected_ids = selection.get("selected_turn_ids") or []
    row["context_tokens"] = selection.get("context_tokens")

    # ---- (1) 候選的證據 ----
    candidate_ids = None
    if candidate is None:
        issues.append("找不到對應的候選紀錄")
    else:
        issues += check_config_match(selection, candidate, "candidates")
        candidate_ids = [c["turn_id"] for c in candidate.get("candidates", [])]
        block, err = evidence_block(evidence, qid, candidate_ids, "cand_")
        row.update(block)
        if err:
            issues.append(err)
        # 選中的輪應該全部來自候選；否則代表 D 線讀錯候選檔或對應錯題
        outside = [t for t in selected_ids if t not in set(candidate_ids)]
        if outside:
            issues.append(f"有 {len(outside)} 個選中輪不在候選中，例如 {outside[:2]}")

    # ---- (2) 選中材料的證據 ----
    block, err = evidence_block(evidence, qid, selected_ids, "sel_")
    row.update(block)
    if err:
        issues.append(err)

    # ---- (3) 證據在哪個環節丟掉（A02 diagnose） ----
    if candidate_ids is not None and "cand_error" not in row and "sel_error" not in row:
        budget = selection.get("budget_tokens")
        # 每輪 token 數的來源：優先用 --turn-tokens 檔；沒有的話，用 D02 選中紀錄內建的
        # candidate_trials（D02 對每個候選輪記錄了單獨序列化後的 token 數）
        if not turn_tokens:
            turn_tokens = tokens_from_d02(selection)
        tokens = turn_tokens if (turn_tokens and budget is not None) else None
        if tokens is not None:
            lacking = [t for t in candidate_ids if t not in tokens]
            if lacking:
                issues.append(f"turn-tokens 檔缺少 {len(lacking)} 個候選輪的 token 數，改為不區分放不下")
                tokens = None
        row["diagnosis"] = evidence.diagnose(qid, candidate_ids, selected_ids,
                                             turn_tokens=tokens, budget=budget if tokens else None)
        row["diagnosis_has_tokens"] = tokens is not None
    else:
        row["diagnosis"] = None

    # ---- (4) 評分 ----
    if score is None:
        issues.append("找不到對應的評分紀錄")
        row["label"] = None
    else:
        issues += check_config_match(selection, score, "scores")
        row["score_status"] = score.get("status")
        row["e_status"] = score.get("e_status")
        row["label"] = score.get("label")
        row["response_sent"] = score.get("response_sent")
        row["judge_output"] = score.get("judge_output")
        if score.get("status") == "no_answer":
            # E 沒有可評的回答（空回答、技術失敗）：依 SCORING_CONFIG 第五節算錯
            #   舊評分檔的 label 為 null，這裡一律補為 0
            row["label"] = 0
            issues.append(f"沒有可評的回答（E status={score.get('e_status')}），算錯")
        elif score.get("status") != "ok":
            issues.append(f"評分狀態不是 ok：{score.get('status')}（結果未完成，請重跑 judge.py）")
        if score.get("e_status") == "truncated":
            issues.append("回答截斷（已照樣送評）")
        if score.get("extract_agrees") is False:
            issues.append("E 的 hypothesis 與 F 的提取不一致")
        if score.get("parse_status") == "unclear":
            issues.append("judge 回覆格式不明確")

    # ---- (5) 結果分類 ----
    #   答對：correct；若證據不齊卻答對，另外標記（可能是猜對、或證據標註不完整，值得看一下）
    #   答錯：依歸因對應到 A05 的四類
    if row.get("score_status") == "no_answer":
        row["outcome"] = "生成失敗"          # 沒有回答，不歸因到證據
    elif row["label"] == 1:
        row["outcome"] = "答對"
        if row.get("sel_all_retained") is False:
            row["outcome"] = "答對但證據不齊"
    elif row["label"] == 0:
        row["outcome"] = OUTCOME_IF_WRONG.get(row["diagnosis"], "無法歸因")
    else:
        row["outcome"] = "未評分"

    row["issues"] = issues
    return row


# ===========================================================================
# 4. 摘要
# ===========================================================================
def summarize(rows, global_issues):
    """依設定分組，印出準確率、候選與選中的證據指標、結果分類、問題數。"""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["stage"], r["index"], r["strategy"], r["budget_tokens"])].append(r)

    def mean(values):
        values = [v for v in values if v is not None]
        return f"{sum(values) / len(values):.3f}" if values else "—"

    print("\n" + "=" * 64)
    for (stage, index, strategy, budget), g in sorted(groups.items(), key=str):
        print(f"[{stage} / {index} / {strategy} / {budget}]  共 {len(g)} 題")
        # 分母：有分數的列（含「生成失敗」算 0）；缺評分或 api_error 的列不計入並警告
        scored = [r for r in g if r["label"] is not None]
        if scored:
            print(f"    準確率：{sum(r['label'] for r in scored) / len(scored):.3f}"
                  f"（{sum(r['label'] for r in scored)}/{len(scored)}）")
        if len(scored) < len(g):
            print(f"    [警告] {len(g) - len(scored)} 題沒有分數（缺評分或 api_error），"
                  f"未計入準確率，結果未完成")
        # A02 規則：拒答題不參與證據平均
        ev_rows = [r for r in g if not r["is_abstention"]]
        print(f"    候選：平均保留率 {mean(r.get('cand_msg_retention') for r in ev_rows)}，"
              f"證據齊全率 {mean(r.get('cand_all_retained') for r in ev_rows)}")
        print(f"    選中：平均保留率 {mean(r.get('sel_msg_retention') for r in ev_rows)}，"
              f"證據齊全率 {mean(r.get('sel_all_retained') for r in ev_rows)}")
        print(f"    結果分類：{dict(Counter(r['outcome'] for r in g))}")

    n_row_issues = sum(len(r["issues"]) for r in rows)
    print(f"\n發現的問題：逐題 {n_row_issues} 項，檔案層級 {len(global_issues)} 項")
    for r in rows:
        for msg in r["issues"]:
            print(f"    {r['question_id']} [{r['index']}/{r['strategy']}/{r['budget_tokens']}]：{msg}")
    for gi in global_issues:
        print(f"    {gi['key']}：{gi['detail']}")
    print("=" * 64)


# ===========================================================================
# 5. 輸出
# ===========================================================================
CSV_COLUMNS = [
    "question_id", "question_type", "is_abstention", "index", "strategy", "budget_tokens", "variant",
    "cand_n_turns_given", "cand_msg_retention", "cand_all_retained",
    "sel_n_turns_given", "sel_msg_retention", "sel_all_retained", "context_tokens",
    "diagnosis", "e_status", "label", "outcome", "sel_missing_message_ids", "issues",
]


def write_outputs(rows, global_issues, out_path):
    """寫出 JSONL（完整欄位）與 CSV（精簡欄位，方便用 Excel 看）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 檔案層級的問題（例如回答檔有、選中檔沒有的題目）另存一份
    issues_path = out_path.with_name(out_path.stem + "_issues.jsonl")
    with open(issues_path, "w", encoding="utf-8") as f:
        for gi in global_issues:
            f.write(json.dumps({"key": list(gi["key"]), "type": gi["type"], "detail": gi["detail"]},
                               ensure_ascii=False) + "\n")

    # utf-8-sig：讓 Excel 正確顯示中文
    csv_path = out_path.with_suffix(".csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            flat = dict(r)
            flat["issues"] = "；".join(r["issues"])
            flat["sel_missing_message_ids"] = " ".join(r.get("sel_missing_message_ids") or [])
            w.writerow(flat)
    print(f"\n已輸出：{out_path}\n        {csv_path}\n        {issues_path}")


# ===========================================================================
# 6. 主流程
# ===========================================================================
def parse_args():
    p = argparse.ArgumentParser(description="F02 串聯：候選、選中材料、證據、評分")
    p.add_argument("--candidates", required=True, help="B 候選檔（JSONL）")
    p.add_argument("--selections", required=True, help="D 選中檔（JSONL）")
    p.add_argument("--scores", required=True, help="F 評分檔（JSONL，judge.py 的輸出）")
    p.add_argument("--turn-tokens", default=None, help="每輪 token 數（JSON，選填）")
    p.add_argument("--out", required=True, help="輸出 JSONL 路徑；同名 .csv 與 _issues.jsonl 會一併產生")
    p.add_argument("--a01-out", default=None, help="A01 輸出資料夾（預設使用 A02 內建的路徑）")
    return p.parse_args()


def main():
    args = parse_args()
    global_issues = []

    # ---- 6-1 載入 A02 的證據資料 ----
    evidence = Evidence(args.a01_out) if args.a01_out else Evidence()

    # ---- 6-2 讀三個檔案並建立對應表 ----
    selections = load_jsonl(args.selections)
    cand_table = index_records(load_jsonl(args.candidates), CANDIDATE_KEY, "candidates", global_issues)
    score_table = index_records(load_jsonl(args.scores), SELECTION_KEY, "scores", global_issues)
    sel_table = index_records(selections, SELECTION_KEY, "selections", global_issues)
    turn_tokens = None
    if args.turn_tokens:
        with open(args.turn_tokens, encoding="utf-8") as f:
            turn_tokens = json.load(f)
    print(f"候選 {len(cand_table)} 筆、選中 {len(sel_table)} 筆、評分 {len(score_table)} 筆"
          f"{'、含每輪 token 數' if turn_tokens else '（未提供每輪 token 數）'}")

    # ---- 6-3 以「選中材料」為主，逐筆串聯 ----
    rows = []
    for key, sel in sel_table.items():
        if sel["question_id"] not in evidence.eval:
            global_issues.append({"key": key, "type": "unknown_question",
                                  "detail": "題目不在 A01 評價檔中，無法計算證據"})
            continue
        cand = cand_table.get(make_key(sel, CANDIDATE_KEY))
        score = score_table.get(key)
        rows.append(build_row(sel, cand, score, evidence, turn_tokens))

    # ---- 6-4 反向檢查：評分檔中有、選中檔中沒有的紀錄 ----
    for key in score_table:
        if key not in sel_table:
            global_issues.append({"key": key, "type": "score_without_selection",
                                  "detail": "評分檔有這筆，但選中檔沒有對應紀錄"})

    # ---- 6-5 輸出與摘要 ----
    write_outputs(rows, global_issues, Path(args.out))
    summarize(rows, global_issues)


if __name__ == "__main__":
    main()
