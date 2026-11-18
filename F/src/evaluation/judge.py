"""
LongMemEval 評分程式（F01，v0.2：改用 A01 交接格式；評分設定 f03-v1，見 SCORING_CONFIG.md）

【這支程式做什麼】
讀入 E 線的回答檔，搭配 A01 的評價檔與問題檔，逐題組成評分 prompt，
呼叫 judge LLM（預設 gpt-4o-2024-08-06）判斷 yes / no，
把結果寫成 F 線的評分檔，最後印出準確率摘要。

【輸入與輸出（依 A01-开发题与交接格式.md 第 4 節，版本 a01-v2）】
  輸入 1  E 回答檔   answers/{stage}_{index}_{strategy}_{budget}.jsonl
          欄位：公共欄位 + prompt_tokens、output_tokens、raw_output、hypothesis、elapsed_s、status
  輸入 2  評價檔     A01/output/eval/dev_eval.jsonl（第 4.2 節，只給 A02 / F 線）
          用到的欄位：question_id、question_type、is_abstention、answer
  輸入 3  問題檔     A01/output/public/dev_questions.jsonl（第 4.1 節）
          用到的欄位：question_id、question
  輸出    F 評分檔   scores/{與回答檔相同的檔名}.jsonl
          欄位：公共欄位 + judge_model、label、judge_output、status（A01 規定）
                + 其他追蹤欄位（本程式新增，見 EVAL_NOTES.md）

  公共欄位：question_id、stage、index、strategy、budget_tokens、tokenizer、config_version

【與官方 evaluate_qa.py 相同的地方】
  - 評分 prompt：逐字沿用（見 prompts.py）
  - 呼叫參數：temperature=0、max_tokens=10、n=1
  - 判定規則：judge 回覆中含有 "yes"（不分大小寫）就算答對

【方法名稱隱藏】
  評分檔會保留 index、strategy 等欄位（A01 規定），但送給 judge 的 prompt
  只包含「問題、參考答案、回答」三樣，judge 看不到任何方法資訊。
  F05 人工判斷時的匿名處理，另外在 F05 進行。

【使用方式】（詳見 EVAL_NOTES.md）
  先不花錢，只看 prompt：
      .venv/bin/python src/evaluation/judge.py --answers tests/answers/dev_K0_R_2048.jsonl \
          --eval tests/fixtures/test_eval.jsonl --questions tests/fixtures/test_questions.jsonl --dry-run
"""

# ===========================================================================
# 0. 匯入需要的套件
# ===========================================================================
import argparse   # 解析命令列參數，例如 --answers xxx.jsonl
import json       # 讀寫 JSON 格式
import os         # 讀取環境變數（API key）
import re         # 正規表達式，用來找 "Final answer:"
import sys        # 印錯誤訊息、結束程式
import time       # 計時、重試時暫停
from collections import Counter, defaultdict  # 計數器；查不到就給預設值的字典
from datetime import datetime                 # 產生時間戳記
from pathlib import Path                      # 處理檔案路徑

# 匯入同資料夾的 prompts.py（先把本檔所在資料夾加入搜尋路徑）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompts import PROMPT_SOURCE, build_judge_prompt  # noqa: E402
from paths import CODE_ROOT, A01_OUTPUT  # noqa: E402  （路徑統一在 paths.py 設定）


# ===========================================================================
# 1. 預設設定
# ===========================================================================
# 程式根目錄（.env、scores/ 的位置）；組內專案與 A01 的位置見 paths.py
PROJECT_ROOT = CODE_ROOT

DEFAULT_EVAL_FILE = A01_OUTPUT / "eval" / "dev_eval.jsonl"
DEFAULT_QUESTIONS_FILE = A01_OUTPUT / "public" / "dev_questions.jsonl"
DEFAULT_SCORES_DIR = PROJECT_ROOT / "scores"

DEFAULT_JUDGE_MODEL = "gpt-4o-2024-08-06"   # 論文 p.6 §3.3；2027-01-14 停止服務

# A01 第 4.3 節規定每筆交接紀錄都要帶的公共欄位
COMMON_FIELDS = ["question_id", "stage", "index", "strategy",
                 "budget_tokens", "tokenizer", "config_version"]

# E02/E03 交接新增、用來區分紀錄的欄位（識別鍵用，也會原樣抄進評分檔）
#   E03 起：record_id（輸入紀錄雜湊）、reader_config_id（閱讀器設定雜湊）、
#   selection_config_id（選擇設定雜湊，含權重等參數）。依 E03 README，
#   同一方法不同權重的題號、策略、config_version 可能相同，必須靠這三個欄位區分。
#   舊資料（E02 以前）沒有這些欄位，記為 None，不影響續跑。
EXTRA_KEY_FIELDS = ["variant", "topk", "reader_config_version", "history_sha256",
                    "record_id", "reader_config_id", "selection_config_id"]
# 只需抄進評分檔的欄位：{回答檔欄位: 評分檔欄位}
#   E 的 parse_status（答案標記提取結果）改名 e_parse_status，
#   避免和評分檔自己的 parse_status（judge 回覆是否清楚）混淆
#   input_config_version：E03 起提供，串聯證據時用來核對選擇記錄的輸入版本
EXTRA_COPY_FIELDS = {"generation_status": "generation_status",
                     "needs_review": "needs_review",
                     "parse_status": "e_parse_status",
                     "input_config_version": "input_config_version"}

# 評分設定版本（見 SCORING_CONFIG.md），每筆評分都會記錄
SCORING_CONFIG_VERSION = "f03-v1"

# E 回答檔的 status（E02/E03 匯出：generated → ok；其餘原樣保留）
#   依 E 線 2026-11-18 確認（SCORING_CONFIG.md 第五節）：
#     ok / success   正常產生回答                 → 送評
#     truncated      輸出截斷，但有已產生的文字   → 照樣送評（選項 1A），另外統計
#     empty          空回答                       → 不送評，算錯（2A）
#     technical_failure 生成技術失敗              → 不送評，算錯（3A）；E 應先用 --resume 補跑（4A）
#     其他未知狀態（例如舊格式的 error）           → 比照技術失敗，摘要中警告
E_STATUS_OK = {"ok", "success"}
E_STATUS_SCORED = E_STATUS_OK | {"truncated"}
E_STATUS_KNOWN_FAILED = {"empty", "technical_failure"}

# 呼叫參數，與官方 evaluate_qa.py 相同
JUDGE_TEMPERATURE = 0
JUDGE_MAX_TOKENS = 10

# 重試設定：暫時性錯誤最多試 6 次，等待 2、4、8……秒（指數退避）
MAX_ATTEMPTS = 6
FIRST_WAIT_SECONDS = 2

# 答案提取用的標記（不分大小寫）
FINAL_ANSWER_PATTERN = re.compile(r"final\s*answer\s*:", re.IGNORECASE)

# F 評分檔的 status 取值（本程式提議，待寫入 A01）：
#   ok          成功評分，label 為 0 或 1
#   api_error   呼叫 judge 時發生技術失敗，label 為 null，下次執行會重評
#   no_answer   E 線沒有產生可評的回答（空回答、技術失敗等），不送去評分，label 為 0（算錯）
#               ——f03-v1 起；之前的版本 label 為 null、不計入分母，摘要讀取時一律視為 0
#   每筆另記 e_status（E 的原始 status），截斷的回答 status 為 ok、e_status 為 truncated


# ===========================================================================
# 2. 讀取 API key
# ===========================================================================
def load_env_file(env_path):
    """
    讀取 .env 檔，把 KEY=VALUE 設成環境變數。
    API key 不能寫在程式碼裡，所以放在 .env（已列入 .gitignore）。
    如果終端機已經 export 過，就以終端機為準，不會被覆蓋。
    """
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue                     # 空行、註解、格式不對的行都跳過
            key, value = line.split("=", 1)  # 只切第一個等號
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ===========================================================================
# 3. 讀取資料
# ===========================================================================
def load_jsonl(path):
    """
    讀取 JSONL 檔（每一行是一個獨立的 JSON 物件），回傳 list。
    某一行格式錯誤時，會指出是第幾行。
    """
    records = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"[錯誤] {path} 第 {line_no} 行不是合法的 JSON：{e}")
    return records


def load_by_question_id(path):
    """讀取 JSONL，回傳「用 question_id 查資料」的 dict。"""
    return {r["question_id"]: r for r in load_jsonl(path)}


def check_answer_fields(answers):
    """
    確認 E 回答檔每一筆都有評分需要的欄位。
    hypothesis 可以是空字串（代表 E 線提取失敗），但欄位本身要存在。
    """
    required = COMMON_FIELDS + ["raw_output", "hypothesis", "status"]
    for i, a in enumerate(answers, start=1):
        missing = [k for k in required if k not in a]
        if missing:
            sys.exit(f"[錯誤] 回答檔第 {i} 筆缺少欄位：{missing}")


# ===========================================================================
# 4. 決定送給 judge 的答案
# ===========================================================================
def extract_final_answer(raw_output):
    """
    F 線自己的答案提取（用來檢查 E 線的 hypothesis，也當作備用）。

    規則：找「最後一個」Final answer: 標記，取它之後到結尾的全部文字（可以多行）。
    找不到標記或後面是空的 → 回傳空字串。
    """
    matches = list(FINAL_ANSWER_PATTERN.finditer(raw_output or ""))
    if matches:
        return raw_output[matches[-1].end():].strip()
    return ""


def normalize(text):
    """比較兩段文字是否相同時使用：轉小寫、把連續空白壓成一個。"""
    return " ".join(text.lower().split())


def choose_response(answer):
    """
    決定要送給 judge 的回答，回傳 (回答文字, 來源, F 的提取結果是否與 E 一致)。

    優先順序：
      1. E 線的 hypothesis（不是空的）           → 來源 "hypothesis"
      2. F 線從 raw_output 提取的 Final answer   → 來源 "f_extracted"
      3. 整段 raw_output                          → 來源 "raw_output"

    「是否一致」只在 E 和 F 都有提取到答案時才比較；否則記為 None（無法比較）。
    不一致不影響評分，但會列在摘要中，用來確認雙方的提取規則是否相同。

    【E02 v2 的例外】（2026-11-17，依 E02 交接補丁）
      E02 v2 起由 E 線負責提取答案，F 不再用第二套規則提取，避免兩邊規則不一致：
        - E 有明確答案標記（parse_status = explicit_marker）→ 用 E 的 hypothesis
        - 否則 → 送整段 raw_output（與官方評分程式的做法相同）
    """
    if answer.get("reader_config_version") == "e02-v2":
        hypothesis = (answer.get("hypothesis") or "").strip()
        if hypothesis and answer.get("parse_status") == "explicit_marker":
            return hypothesis, "hypothesis", None
        return (answer.get("raw_output") or "").strip(), "raw_output", None

    hypothesis = (answer.get("hypothesis") or "").strip()
    f_extracted = extract_final_answer(answer.get("raw_output", ""))

    agrees = None
    if hypothesis and f_extracted:
        agrees = normalize(hypothesis) == normalize(f_extracted)

    if hypothesis:
        return hypothesis, "hypothesis", agrees
    if f_extracted:
        return f_extracted, "f_extracted", agrees
    return (answer.get("raw_output") or "").strip(), "raw_output", agrees


# ===========================================================================
# 5. 呼叫 judge
# ===========================================================================
def call_judge(client, model, prompt):
    """
    呼叫 OpenAI API，請 judge 回答 yes 或 no。

    錯誤處理分三類：
      A. 暫時性錯誤（流量限制、網路、逾時、伺服器錯誤）→ 等待後重試
      B. 設定錯誤（key 錯誤、沒有權限、模型不存在）  → 直接停止整支程式
      C. 其他錯誤                                    → 記為 api_error，繼續下一題
    """
    import openai  # 只在真的要呼叫 API 時才載入

    retryable = (openai.RateLimitError, openai.APIConnectionError,
                 openai.APITimeoutError, openai.InternalServerError)
    fatal = (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError)

    wait = FIRST_WAIT_SECONDS
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        start = time.time()
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                n=1,
                temperature=JUDGE_TEMPERATURE,
                max_tokens=JUDGE_MAX_TOKENS,
            )
            usage = completion.usage
            return {
                "status": "ok",
                "judge_output": (completion.choices[0].message.content or "").strip(),
                "judge_model_returned": completion.model,
                "judge_prompt_tokens": usage.prompt_tokens if usage else None,
                "judge_output_tokens": usage.completion_tokens if usage else None,
                "judge_elapsed_s": round(time.time() - start, 3),
                "judge_attempts": attempt,
            }
        except fatal:
            raise                                   # B 類
        except retryable as e:                      # A 類
            last_error = e
            print(f"  [重試 {attempt}/{MAX_ATTEMPTS}] {type(e).__name__}，{wait} 秒後再試",
                  file=sys.stderr)
            time.sleep(wait)
            wait *= 2
        except openai.APIError as e:                # C 類
            last_error = e
            break

    return {"status": "api_error",
            "error": f"{type(last_error).__name__}: {last_error}",
            "judge_attempts": attempt}


def parse_judge_label(judge_output):
    """
    把 judge 的回覆轉成分數（規則與官方相同）：含有 "yes" → 1，否則 → 0。
    parse_status："clean" 代表以 yes / no 開頭；"unclear" 代表格式不明確，建議人工確認。
    """
    text = judge_output.strip().lower()
    label = 1 if "yes" in text else 0
    parse_status = "clean" if text.startswith(("yes", "no")) else "unclear"
    return label, parse_status


# ===========================================================================
# 6. 斷點續跑
# ===========================================================================
def record_key(r):
    """
    用公共欄位組成一筆紀錄的唯一識別。
    同一題在不同索引、策略、預算、設定版本下，是不同的紀錄。
    E02 起另外加入 variant（budget / original_topk）、topk、閱讀器版本、歷史文字雜湊，
    避免預算版與參照版、或不同次生成的結果互相覆蓋。
    E03 起再加入 record_id、reader_config_id、selection_config_id，
    避免同一方法不同參數（例如權重）的回答被當成同一筆而跳過。
    舊資料沒有這些欄位時記為 None。
    """
    return json.dumps([r.get(k) for k in COMMON_FIELDS + EXTRA_KEY_FIELDS], ensure_ascii=False)


def load_finished_keys(scores_path):
    """
    找出評分檔中「已經處理完」的紀錄：status 為 ok 或 no_answer。
    api_error 不算完成，下次執行會重新評分。
    """
    finished = set()
    if scores_path.exists():
        for r in load_jsonl(scores_path):
            if r.get("status") in ("ok", "no_answer"):
                finished.add(record_key(r))
    return finished


# ===========================================================================
# 7. 摘要統計
# ===========================================================================
def config_label(r):
    """把一筆紀錄的設定組成易讀的名稱，例如 dev / K0 / R / 2048。"""
    return f"{r['stage']} / {r['index']} / {r['strategy']} / {r['budget_tokens']}"


def final_label(r):
    """計入準確率的分數：ok 用 judge 的 label；no_answer 一律為 0（舊檔的 null 也視為 0）。"""
    return r["label"] if r["status"] == "ok" else 0


def status_breakdown(rows):
    """一組紀錄的組成，例如「送評 78（其中截斷 2）；未送評 2：empty 1、technical_failure 1」。"""
    scored = [r for r in rows if r["status"] == "ok"]
    n_trunc = sum(r.get("e_status") == "truncated" for r in scored)
    failed = Counter(r.get("e_status") or "未記錄" for r in rows if r["status"] == "no_answer")
    text = f"送評 {len(scored)}" + (f"（其中截斷 {n_trunc}）" if n_trunc else "")
    if failed:
        text += f"；未送評 {sum(failed.values())}：" + "、".join(f"{k} {v}" for k, v in failed.items())
    return text


def summarize(scores_path, expected_path=None):
    """
    讀取評分檔並印出摘要。同一筆紀錄若出現多次（例如先失敗後成功），只取最後一次。
    拒答題歸類為 "abstention"（主實驗只用可回答題，拒答題在 H06 研究）。
    """
    latest = {}
    for r in load_jsonl(scores_path):
        latest[record_key(r)] = r
    records = list(latest.values())
    ok = [r for r in records if r["status"] == "ok"]
    # 計入準確率的紀錄：成功評分（ok）＋沒有可評回答（no_answer，算 0）
    #   api_error 是 F 端未完成，不計入，並在下方警告
    counted = [r for r in records if r["status"] in ("ok", "no_answer")]
    status_count = Counter(r["status"] for r in records)

    print("\n" + "=" * 64)
    print(f"評分檔：{scores_path}")
    print(f"總筆數 {len(records)}；各狀態：{dict(status_count)}")
    if not counted:
        print("沒有可計算準確率的資料。")
        return

    def acc(rows):
        n_correct = sum(final_label(r) for r in rows)
        return f"{n_correct / len(rows):.4f} ({n_correct}/{len(rows)})"

    # 依設定分組，再依題型分組
    by_config = defaultdict(list)
    for r in counted:
        by_config[config_label(r)].append(r)
    for label, rows in sorted(by_config.items()):
        print(f"\n[{label}] 整體準確率：{acc(rows)}")
        print(f"    {status_breakdown(rows)}")
        by_type = defaultdict(list)
        for r in rows:
            by_type["abstention" if r["is_abstention"] else r["question_type"]].append(r)
        for group, g_rows in sorted(by_type.items()):
            print(f"    {group:28s} {acc(g_rows)}")

    # 答案來源與提取一致性（用來和 E 線核對提取規則）
    print(f"\n送給 judge 的答案來源：{dict(Counter(r['response_source'] for r in ok))}")
    mismatches = [r for r in ok if r["extract_agrees"] is False]
    print(f"E 的 hypothesis 與 F 的提取不一致：{len(mismatches)} 筆")
    for r in mismatches:
        print(f"    {r['question_id']}：E={r['hypothesis']!r}")
        print(f"    {' ' * len(r['question_id'])}  F={r['f_extracted']!r}")
    print(f"judge 回覆格式不明確（建議人工確認）："
          f"{sum(r.get('parse_status') == 'unclear' for r in ok)} 筆")

    # 警告：結果是否完整、是否需要 E 補跑
    n_api_error = status_count.get("api_error", 0)
    if n_api_error:
        print(f"\n[警告] 有 {n_api_error} 筆 judge 呼叫失敗（api_error），結果未完成，"
              f"上面的準確率不能使用。請重新執行 judge.py（會自動只重評這些紀錄）。")
    failed = Counter(r.get("e_status") or "未記錄" for r in counted if r["status"] == "no_answer")
    if failed.get("technical_failure"):
        print(f"[警告] 有 {failed['technical_failure']} 筆生成技術失敗，已算錯。"
              f"請確認 E 已用 --resume 補跑，且這是重新匯出的最終版本（SCORING_CONFIG 第五節 4A）。")
    unknown = {k: v for k, v in failed.items() if k not in E_STATUS_KNOWN_FAILED}
    if unknown:
        print(f"[警告] 有不在約定範圍內的 E status，已比照技術失敗算錯：{unknown}")

    # 與預期答案比較（測試與 F03 校準用）；預期檔格式：{"question_id": 0 或 1}
    if expected_path:
        with open(expected_path, encoding="utf-8") as f:
            expected = json.load(f)
        compared = [r for r in counted if r["question_id"] in expected]
        if compared:
            agree = [r for r in compared if final_label(r) == expected[r["question_id"]]]
            print(f"\n與預期答案一致：{len(agree)}/{len(compared)} = {len(agree) / len(compared):.4f}")
            for r in compared:
                if final_label(r) != expected[r["question_id"]]:
                    group = "abstention" if r["is_abstention"] else r["question_type"]
                    print(f"    不一致：{r['question_id']}（{group}）預期 {expected[r['question_id']]}，"
                          f"評分 {final_label(r)}（{r['status']}），judge 原文：{r.get('judge_output')!r}")
    print("=" * 64)


# ===========================================================================
# 8. 主流程
# ===========================================================================
def parse_args():
    """定義命令列參數。執行時加上 --help 可以看到說明。"""
    p = argparse.ArgumentParser(description="LongMemEval judge 評分程式（F01 v0.2，A01 格式）")
    p.add_argument("--answers", required=True, help="E 回答檔（JSONL）")
    p.add_argument("--eval", default=str(DEFAULT_EVAL_FILE), help="A01 評價檔（JSONL）")
    p.add_argument("--questions", default=str(DEFAULT_QUESTIONS_FILE), help="A01 問題檔（JSONL）")
    p.add_argument("--out", default=None, help="評分檔路徑（預設 scores/<回答檔同名>.jsonl）")
    p.add_argument("--model", default=DEFAULT_JUDGE_MODEL, help="judge 模型 ID")
    p.add_argument("--expected", default=None, help="預期分數檔（JSON），用來檢查 judge 是否判對")
    p.add_argument("--limit", type=int, default=None, help="只處理前 N 筆（試跑用）")
    p.add_argument("--dry-run", action="store_true", help="只印出 prompt，不呼叫 API、不花錢")
    p.add_argument("--summary-only", action="store_true", help="不評分，只重新印出摘要")
    return p.parse_args()


def main():
    args = parse_args()

    # ---- 8-1 決定評分檔路徑：與回答檔同名，放在 scores/ 底下（A01 第 4.3 節） ----
    answers_path = Path(args.answers)
    scores_path = Path(args.out) if args.out else DEFAULT_SCORES_DIR / answers_path.name

    if args.summary_only:
        summarize(scores_path, args.expected)
        return

    # ---- 8-2 讀取三個輸入檔 ----
    answers = load_jsonl(answers_path)
    check_answer_fields(answers)
    if args.limit:
        answers = answers[: args.limit]
    eval_data = load_by_question_id(args.eval)
    questions = load_by_question_id(args.questions)
    print(f"回答檔：{answers_path}（{len(answers)} 筆）")
    print(f"評價檔：{args.eval}（{len(eval_data)} 題）")
    print(f"問題檔：{args.questions}（{len(questions)} 題）")

    # 每一題都必須同時出現在評價檔與問題檔中
    missing = sorted({a["question_id"] for a in answers
                      if a["question_id"] not in eval_data or a["question_id"] not in questions})
    if missing:
        sys.exit(f"[錯誤] 以下題目在評價檔或問題檔中找不到：{missing}")

    # ---- 8-3 dry-run：只組 prompt 給你看 ----
    if args.dry_run:
        for a in answers:
            if a["status"] not in E_STATUS_SCORED:
                print(f"\n[不送評] {a['question_id']}：E 的 status={a['status']!r}，正式執行時記為 no_answer、算錯")
                continue
            if a["status"] == "truncated":
                print(f"\n[截斷] {a['question_id']}：照樣送評已產生的文字")
            ev, q = eval_data[a["question_id"]], questions[a["question_id"]]
            response, source, agrees = choose_response(a)
            prompt = build_judge_prompt(ev["question_type"], q["question"], ev["answer"],
                                        response, ev["is_abstention"])
            print("\n" + "-" * 64)
            print(f"{a['question_id']}（{ev['question_type']}）答案來源={source}，E/F 提取一致={agrees}")
            print(prompt)
        print("\n（dry-run 模式：沒有呼叫 API，也沒有寫入評分檔）")
        return

    # ---- 8-4 準備 API 用戶端 ----
    load_env_file(PROJECT_ROOT / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("[錯誤] 找不到 OPENAI_API_KEY。請在專案根目錄建立 .env（參考 .env.example）。")
    from openai import OpenAI
    client = OpenAI()

    # ---- 8-5 斷點續跑：跳過已處理的紀錄 ----
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    finished = load_finished_keys(scores_path)
    todo = [a for a in answers if record_key(a) not in finished]
    print(f"已處理 {len(answers) - len(todo)} 筆，本次處理 {len(todo)} 筆 → {scores_path}")

    # ---- 8-6 逐題評分（"a" 附加模式，不會蓋掉舊結果） ----
    with open(scores_path, "a", encoding="utf-8") as out_f:
        for i, a in enumerate(todo, start=1):
            qid = a["question_id"]
            ev, q = eval_data[qid], questions[qid]

            # (1) 先放入 A01 公共欄位，再加上題目資訊
            record = {k: a[k] for k in COMMON_FIELDS}
            #     E02 起的額外欄位：回答檔有才抄（舊格式沒有也能跑）
            record.update({k: a[k] for k in EXTRA_KEY_FIELDS if k in a})
            record.update({new: a[old] for old, new in EXTRA_COPY_FIELDS.items() if old in a})
            record.update({
                "question_type": ev["question_type"],
                "is_abstention": ev["is_abstention"],
                "judge_model": args.model,
                "prompt_source": PROMPT_SOURCE,
                "scoring_config_version": SCORING_CONFIG_VERSION,
                "e_status": a["status"],
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            })

            # (2) E 線沒有可評的回答（空回答、技術失敗等）→ 不送評，記為 no_answer、算錯
            #     截斷（truncated）不在此列，照樣送評（SCORING_CONFIG 第五節）
            if a["status"] not in E_STATUS_SCORED:
                record.update({"status": "no_answer", "label": 0, "judge_output": None})
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_f.flush()
                print(f"  [{i}/{len(todo)}] {qid:22s} 不送評、算錯（E status={a['status']!r}）")
                continue

            # (3) 決定送給 judge 的回答，組 prompt（只含問題、參考答案、回答）
            response, source, agrees = choose_response(a)
            prompt = build_judge_prompt(ev["question_type"], q["question"], ev["answer"],
                                        response, ev["is_abstention"])
            record.update({
                "hypothesis": a["hypothesis"],
                "f_extracted": extract_final_answer(a["raw_output"]),
                "response_sent": response,
                "response_source": source,
                "extract_agrees": agrees,
            })

            # (4) 呼叫 judge；設定錯誤時直接停止
            try:
                call = call_judge(client, args.model, prompt)
            except Exception as e:
                sys.exit(f"[停止] 設定錯誤，無法繼續：{type(e).__name__}: {e}")
            record.update(call)
            if call["status"] == "ok":
                record["label"], record["parse_status"] = parse_judge_label(call["judge_output"])
            else:
                record["label"] = None
                record["judge_output"] = None

            # (5) 立刻寫入，程式中斷也不會遺失
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_f.flush()
            print(f"  [{i}/{len(todo)}] {qid:22s} {ev['question_type']:26s} → "
                  f"{record['label'] if call['status'] == 'ok' else call['status']}")

    # ---- 8-7 印出摘要 ----
    summarize(scores_path, args.expected)


if __name__ == "__main__":
    main()
