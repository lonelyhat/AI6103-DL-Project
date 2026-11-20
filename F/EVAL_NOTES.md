# 評分程式開發紀錄（F01）

負責任務：**F01 整理官方評分規則與初版評分程式**
交付項目：任務評分規則、評分模型初選、答案提取要求、可運行樣例
目前版本：**v0.2**（輸入輸出改用組內 A01 交接格式 `a01-v2`）

---

## 〇、在組內 repo 中使用（組員請先看這一節）

本文件以開發者本機的資料夾結構撰寫。在組內 repo（`F_Evaluation` 分支）中使用時，請依下表換算：

| 項目 | 本文件中的寫法（本機） | 在組內 repo 中 |
|---|---|---|
| 執行位置 | `DL Final Project/` | **先 `cd F`**，所有指令都在 `F/` 執行 |
| 程式 | `src/evaluation/*.py` | `F/src/evaluation/*.py`（相同） |
| 組內專案（A01、A02、E02…） | `AI6103-DL-Project/...` | `../...`，例如 `../E/E02/inputs/...` |
| 評分與串聯結果 | `scores/`、`f02/` | `F/scores/`、`F/f02/`（自動建立） |
| `data/`、`third_party/`、`results/` | 本機才有 | **不需要**，評分只用 A01 的評價檔與問題檔 |

- A01、A02 的位置由 `src/evaluation/paths.py` 自動判斷，在 repo 中**不需要修改任何路徑**。執行 `python src/evaluation/paths.py` 可確認抓到的位置。
- 第一次使用：在 `F/` 底下建立虛擬環境並安裝套件（`python3 -m venv .venv`、`.venv/bin/pip install -r requirements.txt`），再把 `.env.example` 複製成 `.env` 填入自己的 API key（見第二節）。`.env` 與 `.venv` 已被 repo 的 `.gitignore` 排除，**不會也不應上傳**。
- 例：在 repo 中評分 E02 預算版（F02 主結果，在 `F/` 執行）：

```bash
.venv/bin/python src/evaluation/judge.py --answers ../E/E02/results/job-55386/answers_for_f.jsonl --out scores/dev_K0_R_2048_e02.jsonl
```
```bash
.venv/bin/python src/evaluation/join_f02.py --candidates ../E/E02/inputs/sources/b02_candidates.jsonl --selections ../E/E02/results/job-55386/selections.jsonl --scores scores/dev_K0_R_2048_e02.jsonl --out f02/dev_K0_R_2048_e02.jsonl
```

- 例：評分 E02 top-50 參照版：

```bash
.venv/bin/python src/evaluation/judge.py --answers ../E/E02/results/job-55287/answers_for_f.jsonl --out scores/dev_K0_top50_e02.jsonl
```
```bash
.venv/bin/python src/evaluation/join_f02.py --candidates ../E/E02/inputs/sources/b02_candidates.jsonl --selections ../E/E02/inputs/topk_selections.jsonl --scores scores/dev_K0_top50_e02.jsonl --out f02/dev_K0_top50_e02.jsonl
```

- 不呼叫 API 的檢查：在 judge 指令後加 `--dry-run`，只印出評分 prompt。

---

## 一、資料夾結構

```
DL Final Project/
├── EVAL_NOTES.md                     ← 本檔：開發紀錄、使用方法、修改重點
├── SCORING_CONFIG.md                 ← F03 固定評分設定（f03-v1 定稿）
├── requirements.txt                  ← 需要安裝的 Python 套件
├── .env.example                      ← API key 設定範本（複製成 .env 後填入）
├── .env                              ← 你的 API key（自己建立，不上傳）
├── .gitignore
├── src/evaluation/
│   ├── judge.py                      ← 評分主程式
│   ├── prompts.py                    ← 評分 prompt（逐字複製自官方，勿改）
│   ├── paths.py                      ← 路徑設定：組內專案、A01、A02 的位置（換版本只改這裡）
│   ├── join_f02.py                   ← F02 串聯：候選、選中材料、證據、評分
│   ├── make_f03_sheet.py             ← F03 盲判表產生器（去重、打亂、隱藏策略；輸出盲判表、對照檔、成員檔）
│   ├── compare_f03.py                ← F03 比對：人工判斷 vs judge（逐一檢查每個成員的評分）
│   ├── f06_analysis.py               ← F06 主結果與差值區間（證據組 bootstrap）
│   ├── f07_cost.py                   ← F07 一次性／每次提問／複用成本與評分成本
│   └── f07_plot.py                   ← F07 散點圖（耗時 vs 正確率，輸出 SVG）
├── tests/
│   ├── f02/                          ← F02 串聯程式的測試資料（見第七節）
│   ├── answers/dev_K0_R_2048.jsonl   ← 22 筆測試回答（A01 的 E 回答格式）
│   ├── fixtures/
│   │   ├── test_eval.jsonl           ← 測試題的評價檔（A01 第 4.2 節格式）
│   │   └── test_questions.jsonl      ← 測試題的問題檔（A01 第 4.1 節格式）
│   ├── expected_labels.json          ← 每筆測試的預期分數（與回答分開存放）
│   └── build_test_fixtures.py        ← 從官方資料產生上面兩個 fixtures 檔
├── scores/                           ← 評分檔（程式自動建立）
├── f02/                              ← F02 串聯結果（程式自動建立）
├── f03/                              ← F03 盲判表、對照檔、判斷說明、比對結果（不上傳）
├── results/                          ← v0.1 的舊結果（僅保留紀錄）
├── data/                             ← 官方題目資料
│   ├── longmemeval_oracle.json       （15 MB，只含證據 session）
│   └── longmemeval_s_cleaned.json    （277 MB，專案使用的 LongMemEval-S）
├── third_party/LongMemEval/          ← 官方 repo（只讀取，不直接執行）
├── AI6103-DL-Project/                ← 組內專案（git clone，F_Evaluation 分支；程式讀這裡的 A01、A02、E02）
├── AI6103-DL-Project-main_V1/        ← 組內專案舊版下載（保留比對用，程式已不使用）
└── AI6103-DL-Project-main_V2/        ← 組內專案 2026-11-17 下載（保留比對用，程式已不使用）
```

---

## 二、使用方法

### 1. 第一次設定（只需做一次）

**(1) 建立 `.env`**：複製 `.env.example` 並改名為 `.env`，把 `sk-proj-REPLACE_ME` 換成你的 API key。

```bash
cp .env.example .env
```

```bash
open -e .env
```

注意：等號兩邊不要有空格；不要把 key 貼到聊天、截圖或程式碼裡。

**(2) 套件**：已經在 `.venv` 虛擬環境安裝好。若要重新安裝：

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

### 2. 執行

以下指令都在專案根目錄（`DL Final Project`）執行。

**(A) 正式使用：評 E 線交來的開發題回答**

評價檔和問題檔預設讀取 A01 的輸出（`<組內專案>/A-数据线/A01/output/`，組內專案的位置由 `paths.py` 決定），只要給回答檔：

```bash
.venv/bin/python src/evaluation/judge.py --answers answers/dev_K0_R_2048.jsonl
```

評分檔會寫到 `scores/dev_K0_R_2048.jsonl`（與回答檔同名，A01 第 4.3 節的規定）。

正式評分請加上 `--expect-n <預定筆數>`（題數 × 設定數，例如 40 題 × 1 個設定 = 40），摘要最後會印「可發布：是／否」。看到「否」代表評分未完成（缺評分、`api_error`、回答內容已變更、筆數不符或部分設定缺題），補齊前不可發布準確率（`SCORING_CONFIG.md` 第五節）。

**(B) 測試：不花錢，只看會送出什麼 prompt**

測試題不在 A01 的 40 道開發題裡，所以要另外指定評價檔和問題檔：

```bash
.venv/bin/python src/evaluation/judge.py --answers tests/answers/dev_K0_R_2048.jsonl --eval tests/fixtures/test_eval.jsonl --questions tests/fixtures/test_questions.jsonl --dry-run
```

**(C) 測試：跑 22 筆測試案例（會呼叫 API，約 0.01 美元）**

```bash
.venv/bin/python src/evaluation/judge.py --answers tests/answers/dev_K0_R_2048.jsonl --eval tests/fixtures/test_eval.jsonl --questions tests/fixtures/test_questions.jsonl --out scores/test_K0_R_2048.jsonl --expected tests/expected_labels.json
```

加上 `--out` 是為了讓測試結果和正式評分檔分開。

**(D) 只重新印出摘要（不呼叫 API）**：在 (A) 或 (C) 的指令後面加上 `--summary-only`。

### 3. 所有參數

| 參數 | 說明 | 預設值 |
|---|---|---|
| `--answers` | E 回答檔（必填） | — |
| `--eval` | A01 評價檔 | `<組內專案>/A-数据线/A01/output/eval/dev_eval.jsonl` |
| `--questions` | A01 問題檔 | `<組內專案>/A-数据线/A01/output/public/dev_questions.jsonl` |
| `--out` | 評分檔路徑 | `scores/<回答檔同名>.jsonl` |
| `--model` | judge 模型 | `gpt-4o-2024-08-06` |
| `--expected` | 預期分數檔，用來計算一致率 | 不使用 |
| `--expect-n N` | 這一批預定的筆數，用來判定能不能發布 | 不檢查 |
| `--limit N` | 只處理前 N 筆 | 全部 |
| `--dry-run` | 只印 prompt，不呼叫 API | 關閉 |
| `--summary-only` | 只印摘要 | 關閉 |

### 4. 中斷了怎麼辦

直接用同一行指令重新執行。程式會跳過已經處理完的紀錄（`ok` 與 `no_answer`），只處理剩下的和之前 `api_error` 的，不會重複花錢。

E 補跑後重新匯出回答檔時，也是同一行指令重新執行：識別鍵相同但內容改變的回答（比對 `answer_sha256`）會自動重評，畫面會顯示「回答內容與上次評分時不同」的筆數。

---

## 三、檔案格式（依 A01-开发题与交接格式.md 第 4 節，`a01-v2`）

### 0. 公共欄位（A01 第 4.3 節：每筆交接紀錄都要帶）

`question_id`、`stage`（`dev` / `formal`）、`index`（`K0` / `K1`）、`strategy`（`R` / `MMR` / `C` / `Q` / `FL` / `topk`）、`budget_tokens`、`tokenizer`、`config_version`

程式用 `question_id`、`stage`、`index`、`strategy`、`budget_tokens`、`config_version` 識別一筆紀錄（斷點續跑時使用）。

### 1. 輸入：E 回答檔 `answers/{stage}_{index}_{strategy}_{budget}.jsonl`

| 欄位 | 評分時的用途 |
|---|---|
| 公共欄位 | 原樣複製到評分檔 |
| `raw_output` | reader 完整輸出；F 線會從中提取 `Final answer:`，用來和 `hypothesis` 比對 |
| `hypothesis` | E 線提取好的答案；**有值就優先送給 judge** |
| `status` | 不是 `ok` / `success` 時不評分，記為 `no_answer`（E 線正式取值待確認） |
| `prompt_tokens`、`output_tokens`、`elapsed_s` | 評分用不到（F07 成本表會從 E 的檔案讀取） |

### 2. 輸入：評價檔與問題檔（A01 第 4.1、4.2 節）

| 檔案 | 用到的欄位 |
|---|---|
| `eval/dev_eval.jsonl` | `question_type`、`is_abstention`、`answer` |
| `public/dev_questions.jsonl` | `question` |

評價檔沒有問題原文，所以兩個檔案要用 `question_id` 對應。回答檔中的題目若在任一檔案中找不到，程式會停止並列出題號。

### 3. 輸出：F 評分檔 `scores/{與回答檔同名}.jsonl`

**A01 規定的欄位**：

| 欄位 | 說明 |
|---|---|
| 公共欄位 | 從回答檔複製 |
| `judge_model` | 指定的 judge 模型 |
| `label` | 1 答對、0 答錯；未評分時為 `null` |
| `judge_output` | judge 的原始回覆；未評分時為 `null` |
| `status` | `ok` 成功評分；`api_error` 技術失敗（下次執行會重評）；`no_answer` E 線沒有正常產生回答（**取值為本程式提議，待寫入 A01**） |

**本程式新增的追蹤欄位**：

| 欄位 | 說明 |
|---|---|
| `question_type`、`is_abstention` | 從評價檔複製，方便分組統計 |
| `hypothesis` | E 線的提取結果 |
| `f_extracted` | F 線的提取結果 |
| `response_sent` | 實際送給 judge 的回答 |
| `response_source` | 回答來源：`hypothesis` / `f_extracted` / `raw_output` |
| `extract_agrees` | E 與 F 的提取是否一致（忽略大小寫與空白）；有一方沒提取到時為 `null` |
| `parse_status` | `clean` 正常；`unclear` 代表 judge 回覆格式不明確，建議人工確認 |
| `judge_model_returned` | API 實際回報的模型版本 |
| `judge_prompt_tokens`、`judge_output_tokens` | judge 的 token 用量（F07 成本表使用） |
| `judge_elapsed_s`、`judge_attempts`、`timestamp` | 耗時、嘗試次數、時間 |
| `prompt_source` | prompt 版本（官方 repo 的 commit） |
| `e_status` | E 回答檔中的原始 status（f03-v1 起每筆都有） |
| `scoring_config_version` | 評分設定版本（目前 `f03-v1`） |
| `answer_sha256` | 回答指紋（E 的 status ＋ 實際送評文字），續評時用來發現 E 重新匯出後內容改變的回答 |

### 4. 預期分數檔（測試與 F03 校準用）

```json
{"e47becba": 1, "118b2229": 0}
```

鍵是 `question_id`。與回答檔分開存放，避免預期答案混進 judge 的輸入。

---

## 四、F01 交付內容

### 1. 任務評分規則

| 規則 | 出處 |
|---|---|
| 每題把「問題 + 參考答案 + 模型回答」交給 judge，judge 只回答 yes / no | 論文 p.20 Figure 10 圖說；官方 `evaluate_qa.py` |
| 回覆中含有 "yes"（不分大小寫）即判為答對 | 官方 `evaluate_qa.py` |
| 準確率 = 答對題數 / 總題數，並依題型分開報告 | 論文 p.6 §3.3；官方 `print_qa_metrics.py` |
| 一般題型（single-session-user、single-session-assistant、multi-session）：包含正確答案或完整中間步驟才算對；只答出部分算錯 | 論文 p.20 Figure 10 |
| temporal-reasoning：天數等差 1 不扣分 | 論文 p.20 Figure 10 |
| knowledge-update：可同時提到舊資訊，更新後的答案正確即可 | 論文 p.20 Figure 10 |
| single-session-preference：參考答案是 rubric；正確運用使用者資訊即可 | 論文 p.20 Figure 10；p.4 §3.1 |
| abstention（題號以 `_abs` 結尾）：模型能指出資訊不足即算對 | **僅見於官方程式**，論文 Figure 10 未列出 |
| judge 與人類專家一致率約 97%–98%；preference 與 abstention 約 90% | 論文 p.21 Table 6 |

**專案範圍提醒**：主實驗只用可回答題（大綱：目標 80 道），拒答題在 H06 另外研究。程式仍支援拒答題，方便 H06 使用。

**方法名稱隱藏**：評分檔依 A01 規定保留 `index`、`strategy` 等欄位，但送給 judge 的 prompt 只包含問題、參考答案、回答，judge 看不到方法資訊。F05 人工判斷的匿名處理另在 F05 進行。

**題目資料統計**（`longmemeval_s_cleaned.json`，共 500 題）：

| 題型 | 可回答題 | 拒答題 |
|---|---|---|
| temporal-reasoning | 127 | 6 |
| multi-session | 121 | 12 |
| knowledge-update | 72 | 6 |
| single-session-user | 64 | 6 |
| single-session-assistant | 56 | 0 |
| single-session-preference | 30 | 0 |

另外有 32 題的參考答案是整數（例如 `3`），程式會自動轉成字串。

### 2. 評分模型初選

| 項目 | 決定 |
|---|---|
| judge 模型 | `gpt-4o-2024-08-06`（與論文 p.6 §3.3 及官方程式一致） |
| 呼叫參數 | `temperature=0`、`max_tokens=10`、`n=1`（與官方相同） |
| 可用性 | OpenAI 公告：**2027-01-14 停止服務**，建議替代模型 `gpt-6-luna` |
| 呼叫測試 | 2026-10-28 實際呼叫成功；2026-11-15 跑完 21 筆測試案例 |

**風險與對策**：
- 停止服務後無法重新評分 → 所有評分（含 H 系列）須在 2027-01-14 前完成，評分檔須備份。
- 若 H 系列可能拖到之後 → F03 校準時可用 `gpt-6-luna` 評同一批樣本，計算一致率備用。

### 3. 答案提取要求（需與 E 線確認）

**送給 judge 的回答，依序取第一個有內容的：**

1. E 線的 `hypothesis`
2. F 線從 `raw_output` 提取的答案：最後一個 `Final answer:`（不分大小寫）之後到結尾的全部文字（可以多行，偏好題通常是一段建議）
3. 整段 `raw_output`

**一致性檢查**：E 和 F 都有提取到答案時，程式會比對兩者（忽略大小寫與空白），不一致的筆數與內容列在摘要中。不一致不影響評分，用途是確認雙方的提取規則相同。

**對 E 線的要求**：
1. reader 輸出的最後一行固定寫 `Final answer: ...`。
2. `hypothesis` 用上面第 2 點的規則提取；提取失敗時填空字串，不要刪除欄位。
3. 十種設置一律使用同一套規則。

**為什麼要提取**：reader 使用 Chain-of-Note（論文 p.25 Figure 13），筆記中可能同時出現舊值、新值或中間數字，整段送給 judge 容易誤判。
**與論文的差異**：論文與官方程式把整段回答直接送給 judge，沒有提取步驟。報告中需說明。

### 4. 可運行樣例：22 筆測試案例

從官方題目資料中，每種題型挑 3 題（使用真實的問題與參考答案），回答是手寫的模擬 Chain-of-Note 輸出。每種題型都涵蓋一種該題型特有的規則；另外加了 1 筆模擬 E 線回答失敗。

| 題型 | 題號 | 測試內容 | 預期 |
|---|---|---|---|
| single-session-user | e47becba | 答案正確 | 1 |
| | 118b2229 | 答案錯誤（30 分鐘 vs. 45 分鐘） | 0 |
| | 51a45a95 | **E 與 F 都沒提取到答案**（`hypothesis` 為空、沒有 `Final answer:`），改用整段輸出 | 1 |
| | 1e043500 | **E 的 status 為 `error`**，不評分，記為 `no_answer` | — |
| single-session-assistant | c4f10528 | 答案正確 | 1 |
| | 4c36ccef | 答案錯誤（編造餐廳名） | 0 |
| | 6ae235be | **只答出部分**（4 項製程只答 2 項） | 0 |
| single-session-preference | 8a2466db | 有運用使用者資訊（Premiere Pro） | 1 |
| | 06878be2 | 沒有運用使用者資訊（推薦其他品牌） | 0 |
| | 32260d93 | 有運用使用者資訊（Netflix 脫口秀） | 1 |
| multi-session | 0a995998 | 答案正確 | 1 |
| | 6d550036 | 答案錯誤（3 vs. 2） | 0 |
| | gpt4_d84a3211 | **含中間計算步驟**的正確答案 | 1 |
| temporal-reasoning | gpt4_76048e76 | 答案正確 | 1 |
| | 2c63a862 | **天數差 1**（13 vs. 14） | 1 |
| | gpt4_2312f94c | 順序答反 | 0 |
| knowledge-update | 852ce960 | 答案正確 | 1 |
| | 6a1eabeb | **E 與 F 提取結果不一致**（E 只取數值，F 取整句含新舊值），應列入摘要 | 1 |
| | 945e3d21 | **只答舊值** | 0 |
| abstention | 0862e8bf_abs | 正確指出沒提過倉鼠 | 1 |
| | 982b5123_abs | **編造答案** | 0 |
| | eeda8a6d_abs | 正確指出資訊不足 | 1 |

judge 與預期的一致率可以當作「評分程式與規則是否正確」的第一個檢查。若有不一致，先看 `judge_output`，再判斷是測試案例設計的問題，還是 judge 的判斷問題。

---

## 五、與官方程式的差異一覽

| 項目 | 官方 `evaluate_qa.py` | 本程式 |
|---|---|---|
| 評分 prompt | 原版 | **逐字相同**（已用程式比對 5 個模板） |
| 呼叫參數、判分規則 | temperature 0、max_tokens 10、含 yes 即對 | 相同 |
| 題目資料 | 官方 JSON | A01 的評價檔 + 問題檔（內容來自官方清洗版 S） |
| 送給 judge 的回答 | `hypothesis` 整段 | E 的 `hypothesis` → F 的提取 → 整段輸出，並檢查 E/F 一致性 |
| E 回答失敗 | 無此情況 | 不評分，記為 `no_answer` |
| 錯誤處理 | 暫時性錯誤無限重試；其他錯誤中斷 | 最多重試 6 次；設定錯誤立即停止；其他錯誤記錄後繼續 |
| 斷點續跑 | 無（每次重寫結果檔） | 有 |
| 逐題紀錄 | 只存 label | 另存 judge 原文、token、耗時、prompt 版本、提取來源 |
| 摘要 | 整體與各題型 | 另依設定（stage / index / strategy / budget）分組、拒答題獨立、E/F 提取一致性、預期一致率 |

**為什麼沒有直接執行官方程式**：官方程式需要額外套件（tqdm、backoff、numpy），也不支援組內的交接格式與續跑。只沿用其 prompt 與判分規則，可以確保數字與論文可比。

---

## 六、尚待確認

| 項目 | 對象 | 狀態 |
|---|---|---|
| E 回答檔 `status` 的正式取值 | E 線（E02） | **已確認**：E 的轉檔程式只把 `generated` 轉成 `ok`；`truncated`/`empty`/`technical_failure` 原樣保留，F 記為 `no_answer` |
| `hypothesis` 的提取規則 | E 線（E02） | **已確認**：E02 v2 起由 E 負責，只認唯一的 `Final answer:`／`最终答案：` 標記，否則為空 |
| reader 是否輸出 `Final answer:` | E 線（E02） | **否**：E02 用官方 CoN 原始 prompt，沒有要求標記，所以 hypothesis 全為空、整段送評（與官方評分程式相同）。`needs_review` 因此每筆都是 true；**已確認**（2026-11-18，5A）維持現狀，F 只抄進評分檔 |
| 截斷、空回答、技術失敗如何計分 | E 線 | **已確認**（2026-11-18，1A 2A 3A 4A）：截斷照評；空回答、技術失敗算錯並計入分母；E 補跑後重新匯出，F 只評最終版本。見 `SCORING_CONFIG.md` 第五節 |
| F 評分檔的 `status` 取值（`ok` / `api_error` / `no_answer`）與新增的追蹤欄位，是否寫入 A01 | Nathan（A01） | 待確認 |
| `judge_output` 是否就是 judge 的原始回覆 | Nathan（A01） | 待確認；目前依此實作 |
| 用真實開發回答（E01 的 `1cea1afa`、baseline_v1 存檔）核對規則 | E 線 | 待取得 |
| 評分程式最後是否要搬進組內專案 | 全組 | **已上傳**至 `F_Evaluation` 分支的 `F/src/evaluation/`；本次修改後需再同步（含新檔 `paths.py`） |
| API 帳號與預算上限 | 全組 | 待確認 |

---

## 七、F02 串聯程式（`join_f02.py`）

### 1. 做什麼

對每一題、每一種設定，把四件事接成一列：

| 問題 | 資料來源 | 計算方式 |
|---|---|---|
| 候選有沒有找齊證據 | B 候選檔 | A02 `Evidence.retention()` |
| 選中材料有沒有留下證據 | D 選中檔 | A02 `Evidence.retention()` |
| 證據在哪個環節丟掉 | 候選 + 選中 | A02 `Evidence.diagnose()` |
| 有沒有答對 | F 評分檔 | `judge.py` 的輸出 |

證據口徑完全沿用 A02（消息級 `has_answer`），本程式不另外計算。拒答題不參與證據平均（A02 規則）。

### 2. 結果分類（`outcome` 欄位）

| 值 | 意思 | 對應 A02 歸因 |
|---|---|---|
| 答對 | 答對，且選中材料證據齊全 | — |
| 答對但證據不齊 | 答對，但證據沒留齊（可能猜對或標註不完整，值得檢查） | — |
| 沒找到 | 答錯；候選裡就沒有找齊證據 | `candidates_missing` |
| 放不下 | 答錯；證據都在候選中，但覆蓋全部證據的最少長度超過預算 | `over_budget` |
| 沒選到 | 答錯；放得下卻沒選齊 | `selection_missed` |
| 選到仍答錯 | 答錯；證據全部留下，問題在閱讀、提取或評分 | `all_retained` |
| 未評分 | 評分檔沒有對應紀錄，或評分失敗 | — |

答錯的四類即任務表 A05 的分類。**注意**：沒有提供 `--turn-tokens` 時，A02 無法區分「放不下」和「沒選到」，一律歸為「沒選到」；輸出的 `diagnosis_has_tokens` 欄位會記錄這點。

### 3. 自動記錄的資料問題

| 問題 | 層級 |
|---|---|
| 找不到對應的候選或評分紀錄 | 逐題 |
| `config_version` 或 `tokenizer` 在不同檔案間不一致 | 逐題 |
| 選中的輪不在候選中 | 逐題 |
| A02 無法計算（輪 ID 不屬於本題、未知輪 ID） | 逐題 |
| 評分狀態不是 `ok`、E/F 提取不一致、judge 回覆格式不明確 | 逐題 |
| `turn-tokens` 檔缺少候選輪的 token 數 | 逐題 |
| 評分檔有、選中檔沒有的紀錄 | 檔案層級 |
| 題目不在 A01 評價檔中 | 檔案層級 |
| 同一檔案中重複的紀錄（評分檔除外，因為續跑會產生多筆） | 檔案層級 |

### 4. 使用方式

```bash
.venv/bin/python src/evaluation/join_f02.py --candidates candidates/dev_K0.jsonl --selections selections/dev_K0_R_2048.jsonl --scores scores/dev_K0_R_2048.jsonl --out f02/dev_K0_R_2048.jsonl
```

每輪 token 數（用來區分「放不下」和「沒選到」）的來源：
1. 有給 `--turn-tokens <檔案>`（格式 `{"turn_id": token 數}`）就用它；
2. 沒給的話，自動使用 D02 選中紀錄內建的 `candidate_trials[].standalone_context_tokens`（D02 用閱讀模型 tokenizer 實算）；
3. 兩者都沒有（例如 top-k 參照版）就不區分，一律記為「沒選到」。

注意 A02 的「放不下」定義：**連最省的證據組合都超過預算**才算。D02 紀錄裡的 `over_budget` 只是「依序挑選時當下剩餘空間不夠」，不等於 A02 的放不下。

**E02 首批 5 題的實際檔案**（本機在 `AI6103-DL-Project/E/E02/`；repo 中為 `../E/E02/`）：

| 用途 | 預算版（K0/R/2048） | top-50 參照版 |
|---|---|---|
| 候選 | `inputs/sources/b02_candidates.jsonl` | 同左 |
| 選中 | `results/job-55386/selections.jsonl`（E 用固定分詞器重建，選中輪次與 `inputs/sources/d02_selections.jsonl` 相同） | `inputs/topk_selections.jsonl` |
| 回答 | `results/job-55386/answers_for_f.jsonl` | `results/job-55287/answers_for_f.jsonl` |
| 結果 | `scores/`、`f02/dev_K0_R_2048_e02.*` | `scores/`、`f02/dev_K0_top50_e02.*` |

會產生三個檔案：

| 檔案 | 內容 |
|---|---|
| `f02/xxx.jsonl` | 每題每設定一列，完整欄位 |
| `f02/xxx.csv` | 精簡欄位，可用 Excel 開啟 |
| `f02/xxx_issues.jsonl` | 檔案層級的問題 |

### 5. 測試資料（`tests/f02/`）

由 `tests/f02/build_f02_fixtures.py` 產生：

| 題號 | 設定 | 來源 | 預期結果 |
|---|---|---|---|
| 2318644b | K0 / R | **A02 範例，原樣使用** | 沒選到（只留一條證據） |
| 2318644b | K0 / Q | **A02 範例，原樣使用** | 答對（兩條都留下） |
| 4c36ccef | K0 / R | 補充 | 沒找到（證據在助手回覆，候選中沒有） |
| c960da58 | K0 / R | 補充 | 答對 |
| 1cea1afa | K0 / R | 補充（只有評分） | 檔案層級問題：沒有選中材料 |

候選、評分、每輪 token 數都是模擬資料（token 數以字元數 ÷ 4 粗估）。刻意放入的問題：A02 範例是舊版 `a01-v1`（評分檔是 `a01-v2`）；`c960da58` 的 E/F 提取不一致。

執行測試：

```bash
.venv/bin/python tests/f02/build_f02_fixtures.py
```

```bash
.venv/bin/python src/evaluation/join_f02.py --candidates tests/f02/candidates_dev_K0.jsonl --selections tests/f02/selections_dev_K0.jsonl --scores tests/f02/scores_dev_K0.jsonl --out f02/test_dev_K0.jsonl
```

---

## 八、修改紀錄

### 2026-10-28　v0.1 初版

- 下載官方 repo（commit `9e0b455`）到 `third_party/LongMemEval/`。
- 下載官方題目資料 `longmemeval_oracle.json`、`longmemeval_s_cleaned.json` 到 `data/`。未下載 M 版（2.7 GB，專案不使用）。
- 新增 `src/evaluation/prompts.py`：逐字複製官方 5 個評分模板，並以程式比對確認一致。
- 新增 `src/evaluation/judge.py`：答案提取、匿名評分、重試、斷點續跑、逐題紀錄、摘要。
- 新增 21 筆測試案例與預期分數。
- 已驗證：dry-run 正常；用模擬的 judge 測試了寫檔、重試、續跑、摘要與一致率計算。
- **尚未驗證**：用真實 API 跑 21 筆測試案例。

### 2026-11-15　真實 API 測試（程式未修改）

- 以 `gpt-4o-2024-08-06` 跑完 21 筆測試案例：成功 21 筆、技術失敗 0、重試 0。
- **judge 與預期分數一致 21/21**；API 回報的模型版本與指定版本相同。
- judge 回覆只有 `Yes`、`Yes.`、`No`、`No.` 四種，`parse_status` 全為 `clean`。
- 用量：輸入 3,208 tokens、輸出 36 tokens（約 0.01 美元）。
- 結果檔：`results/judge_test_hypotheses.gpt-4o-2024-08-06.judged.jsonl`。
- 發現：組內 A01（`a01-v2`）已定義正式交接格式，與本程式的暫定格式不同，需要調整。

### 2026-11-15　v0.2 改用 A01 交接格式

**輸入輸出**
- 輸入改為三個檔案：E 回答檔（`--answers`）、A01 評價檔（`--eval`）、A01 問題檔（`--questions`）。評價檔與問題檔預設讀取組內專案中 A01 的輸出。
- 輸出改為 `scores/<回答檔同名>.jsonl`，帶 A01 公共欄位與 `judge_model`、`label`、`judge_output`、`status`。
- 欄位改名：`judge_raw` → `judge_output`；`prompt_tokens` / `completion_tokens` → `judge_prompt_tokens` / `judge_output_tokens`（避免與 E 線的 `prompt_tokens` 混淆）；`latency_sec` / `attempts` → `judge_elapsed_s` / `judge_attempts`。
- 移除匿名 `run_id`：改用 A01 公共欄位識別紀錄。judge 的 prompt 本來就不含方法資訊，盲評不受影響。

**評分邏輯**
- 送給 judge 的回答改為優先使用 E 線的 `hypothesis`，其次才用 F 線的提取，最後用整段輸出；並新增 E/F 提取一致性檢查。
- E 回答的 `status` 不是 `ok` 時不評分，記為 `no_answer`。
- 斷點續跑的識別改用公共欄位；`no_answer` 也視為已處理。
- 摘要改為依設定（stage / index / strategy / budget）分組，並列出答案來源統計與 E/F 不一致的內容。

**測試**
- 測試案例改為 A01 格式：`tests/answers/dev_K0_R_2048.jsonl`（22 筆，新增 1 筆 E 回答失敗）；預期分數改為 `tests/expected_labels.json`（鍵改為題號）。
- 新增 `tests/build_test_fixtures.py`，從官方資料產生測試題的評價檔與問題檔（`tests/fixtures/`）。
- 刪除 v0.1 的測試檔 `tests/judge_test_hypotheses.jsonl`、`tests/judge_test_expected.json`。
- `.gitignore` 新增 `scores/`。

**已驗證**（皆未呼叫真實 API）
- dry-run：22 筆的答案來源判斷正確；E 回答失敗的那筆被跳過。
- 用模擬的 judge 測試：寫檔、重試、續跑、`no_answer`、E/F 不一致提示、預期一致率 21/21 都正常。
- 用預設路徑讀取 A01 實際的評價檔與問題檔（以開發題 `1cea1afa` 試跑 dry-run），prompt 組成正確。

**尚未驗證**：用真實 API 跑 v0.2 的 22 筆測試案例（見第二節 (C)）。

### 2026-11-15　v0.2 真實 API 測試

- 使用者以真實 API 跑完 v0.2 的 22 筆測試案例，結果與預期一致。

### 2026-11-15　新增 F02 串聯程式

- 新增 `src/evaluation/join_f02.py`：串聯 B 候選、D 選中材料、A02 證據指標、F 評分，輸出每題一列的 JSONL 與 CSV，並記錄資料問題。說明見第七節。
- 證據計算直接 import 組內 A02 的 `evidence_metrics.py`（`Evidence` 類別），不重寫口徑。
- 新增 `tests/f02/build_f02_fixtures.py` 與測試資料（A02 範例 2 筆原樣使用 + 補充 3 筆）。
- `.gitignore` 新增 `f02/`。

**已驗證**
- 選中材料的證據指標與 A02 範例輸出 `sample_metrics.jsonl` 完全相同（2318644b：R 保留率 0.5、缺 `s020-m002`；Q 保留率 1.0）。
- 四種歸因都測試過：沒選到、沒找到、答對；「放不下」另以 30 token 的極小預算測試，結果正確。
- 刻意放入的 6 個資料問題（4 筆版本不一致、1 筆 E/F 提取不一致、1 筆缺選中材料）全部被記錄。

**限制**
- 尚未接上真實的 B02、D02、E02 檔案；欄位名稱若與 A01 第 4.3 節不同需要調整。
- 「放不下」的判斷需要 D 線提供每輪的實際 token 數。

### 2026-11-17　改用組內專案 V2、整合 E02 交接補丁

**背景**：組內專案更新為 V2（新增 E01、E02、A03、C03；A01、A02 未變）。E02 附上給 F 的補丁 `E/E02/handoff/f_evaluation.patch`（以 `F_Evaluation` 分支 commit 36dd0a8 為基礎）。因本機資料夾結構與分支不同，沒有直接 `git apply`，而是把邏輯逐項移植。

**修改**
- 新增 `src/evaluation/paths.py`：統一判斷組內專案位置。程式在組內 repo 裡時自動使用 repo 本身；在本機時使用 `AI6103-DL-Project-main_V2`；也可用環境變數 `TEAM_REPO` 指定。取代補丁中「改路徑」的部分，同一份程式在兩邊都能跑。
- `judge.py`
  - 路徑改由 `paths.py` 提供。
  - `choose_response`：`reader_config_version = e02-v2` 時，F 不再自行提取；E 有明確標記用 hypothesis，否則送整段 raw_output。
  - `record_key`（續跑識別）加入 `variant`、`topk`、`reader_config_version`、`history_sha256`，格式改為 JSON 字串。**舊評分檔無法沿用續跑**（目前只有測試檔，無影響）。
  - 評分檔多抄 `variant`、`topk`、`reader_config_version`、`history_sha256`、`generation_status`、`needs_review`，以及 E 的 `parse_status`（改名 `e_parse_status`，避免與 judge 的 `parse_status` 混淆）。
- `join_f02.py`
  - 路徑改由 `paths.py` 提供。
  - 選中與評分的對應鍵加入 `config_version`、`variant`、`topk`；沒有 `variant` 時視為 `budget`。
  - 候選的版本改與 D 記錄的 `input_config_version` 比對（B 與 D 版本號本來就不同，原本會誤報）。
  - 新增 `tokens_from_d02()`：沒給 `--turn-tokens` 時，自動用 D02 內建的每輪 token 數判斷「放不下」。
  - 輸出新增 `variant`、`topk` 欄位（CSV 也加入 `variant`）。
- `tests/f02/build_f02_fixtures.py`：路徑改由 `paths.py` 提供；A02 範例對應的評分紀錄改為 `a01-v1`（因版本已是對應鍵）。

**已驗證**（皆未呼叫真實 API）
- F02 測試資料：準確率、保留率、分類與先前相同（Q 1/1；R 1/3、候選 0.667、選中 0.500）。問題由 6 項變 4 項：原本 2 項「評分檔版本不一致」因版本已成為對應鍵而不再出現，屬預期。
- judge 舊格式 22 筆 dry-run：21 筆送評、1 筆不評分、1 筆 E/F 不一致，與先前相同。
- judge 讀 E02 top-50 參照版 5 筆 dry-run：答案來源都是 raw_output，prompt 正常。
- join 讀真實 B02/D02（5 題）：候選保留率皆 1.0；選中保留率 0.8。`2318644b`、`gpt4_7a0daae1` 各漏一條證據，歸因為「沒選到」（最少證據 token 分別為 1397、1355，預算放得下）；版本誤報消失。

**待辦**
- 用真實 API 評 top-50 參照版 5 題。
- 等 E 跑完預算版後評分並串聯，完成 F02。
- 把 `paths.py`、`judge.py`、`join_f02.py` 同步到 `F_Evaluation` 分支，並移除分支上的 `__pycache__/`。


### 2026-11-17　E02 top-50 參照版真實評分（程式未修改）

使用者以真實 API 評分 E02 top-50 參照版 5 題（job 55287），並執行 F02 串聯。

```bash
.venv/bin/python src/evaluation/judge.py --answers AI6103-DL-Project-main_V2/E/E02/results/job-55287/answers_for_f.jsonl --out scores/dev_K0_top50_e02.jsonl
```
```bash
.venv/bin/python src/evaluation/join_f02.py --candidates AI6103-DL-Project-main_V2/E/E02/inputs/sources/b02_candidates.jsonl --selections AI6103-DL-Project-main_V2/E/E02/inputs/topk_selections.jsonl --scores scores/dev_K0_top50_e02.jsonl --out f02/dev_K0_top50_e02.jsonl
```

**整體結果**
- 評分：5 筆皆 `ok`，judge 回覆皆清楚；答案來源皆為整段 raw_output。
- 準確率 0.800（4/5）。候選、選中保留率皆 1.000。
- 結果分類：答對 4、選到仍答錯 1。串聯問題 0 項。
- 用量：judge 輸入約 1,321 tokens、輸出 9 tokens（不到 0.01 美元）。

**逐題核對**

| 題目 | 題型 | 參考答案 | 模型回答（摘要） | judge | 核對 |
|---|---|---|---|---|---|
| 2318644b | multi-session | $270 | 找不到夏威夷住宿費，無法計算 | No | 正確；證據都在材料中卻沒讀出 → 選到仍答錯 |
| 1cea1afa | knowledge-update | 600 | 600 | Yes | 正確；答的是更新後的值 |
| gpt4_7a0daae1 | temporal-reasoning | 1 week | **自行假設**日期（今天與 7 天前）→ 1 week | Yes | 依規則正確，但屬**猜對** |
| 4c36ccef | single-session-assistant | Roscioli | Roscioli | Yes | 正確 |
| c960da58 | single-session-user | 20 | 20 | Yes | 正確 |

**F03 待處理案例：gpt4_7a0daae1（答案對、推理是編的）**
- 模型寫明 "the exact dates are not provided … I will assume …"，沒有從對話找到日期，卻碰巧答對。
- 論文評分 prompt（p.20 Figure 10）只看「回答是否包含正確答案」，所以 judge 判 Yes 符合規則。
- 需要在 F03 人工判斷準則中規定這類情況怎麼判。暫定：依論文規則算對（與 judge 一致），另外標記並在報告中討論。
- 這題在預算版中證據沒有選齊；預算版結果為答錯（沒選到），見下方「F02 預算版」紀錄。

**用途**：本次是流程驗證，也是之後預算版（K0/R/2048）的參照組。同一題若預算版錯、參照版對，問題多半在預算或選擇方法；兩版都錯則可能在閱讀模型。

### 同步 F_Evaluation 分支（2026-11-17 整理；已完成，見下一節）

**分支上目前的版本無法在 repo 裡執行**：舊程式用 `parents[2]` 加上 `AI6103-DL-Project-main_V1` 找 A01、A02，在 repo 中會變成 `F/AI6103-DL-Project-main_V1/...`，這個路徑不存在。
- `join_f02.py`：import A02 時直接出錯（`ModuleNotFoundError: evidence_metrics`）。
- `judge.py`：找不到預設的評價檔與問題檔，除非手動加 `--eval`、`--questions`。

新版改用 `paths.py` 自動判斷，已在本機模擬 repo 結構（`<repo>/F/src/evaluation/`）測試：路徑正確、judge dry-run 5 筆正常、串聯準確率 0.800 與本機相同。

| 檔案 | 動作 |
|---|---|
| `F/src/evaluation/paths.py` | **新增**（必要） |
| `F/src/evaluation/judge.py` | **更新**（必要） |
| `F/src/evaluation/join_f02.py` | **更新**（必要） |
| `F/src/evaluation/prompts.py` | 不變 |
| `F/src/evaluation/__pycache__/` | **刪除** |
| `F/EVAL_NOTES.md`、`F/requirements.txt`、`F/.env.example` | 建議新增（使用說明與環境） |
| `F/tests/`（88 KB） | 建議新增（測試資料，讓組員能自行驗證） |
| `.env`、`.venv/`、`data/`、`third_party/`、`results/` | **不要上傳** |
| `scores/`、`f02/` | 待全組決定是否把評分結果放進 repo |

### 2026-11-17　改讀 git clone 的組內專案、同步 F_Evaluation 分支

- 組內專案改用 `git clone` 放在 `AI6103-DL-Project/`，切換到 `F_Evaluation` 分支並合併 main（29 個 commit，無衝突）。
- 已 push 到 `origin/F_Evaluation`：新增 `paths.py`、`EVAL_NOTES.md`、`requirements.txt`、`.env.example`、`tests/`；更新 `judge.py`、`join_f02.py`；刪除 `__pycache__/` 與根目錄的空檔案 `F_Evaluation`。分支相對 main 為領先 4、落後 0。
- `EVAL_NOTES.md` 新增第〇節「在組內 repo 中使用」。
- `paths.py`：本機預設資料夾由 `AI6103-DL-Project-main_V2` 改為 `AI6103-DL-Project`。在 repo 中會自動判斷，不受這個設定影響。
- 比對：clone 的 A 線資料是 V2 的超集（A01 補齊其餘開發題的輪次檔，A03 多了 map 與 turns）；評價檔、問題檔、A02 程式、E02 完全相同，評分結果不受影響。

**已驗證**：本機改讀 clone 後，E02 參照版串聯（0.800、答對 4、選到仍答錯 1、問題 0 項）與 F02 測試資料（Q 1/1、R 1/3、問題 3+1 項）結果都和先前相同。

**注意**：本機程式讀的是 `AI6103-DL-Project/` **目前切換到的分支**。切到其他分支時，A01、E02 的內容可能不同。

### 2026-11-17　E02 預算版真實評分，完成 F02 前 5 題（程式未修改）

在 `AI6103-DL-Project/` 合併 main 後取得 E02 預算版（job 55386，K0/R/2048，`d02-v1`，`e02-v2`）。執行前檢查：作業 `COMPLETED 0:0`；5 筆皆 `generated`，無截斷或空輸出；輸入 2003–2037 tokens；E 重建的 D02 選中輪次與舊版完全相同；`needs_review` 皆為 true（無 `Final answer:` 標記），judge 改用 `raw_output`。

```bash
.venv/bin/python src/evaluation/judge.py --answers AI6103-DL-Project/E/E02/results/job-55386/answers_for_f.jsonl --out scores/dev_K0_R_2048_e02.jsonl
```
```bash
.venv/bin/python src/evaluation/join_f02.py --candidates AI6103-DL-Project/E/E02/inputs/sources/b02_candidates.jsonl --selections AI6103-DL-Project/E/E02/results/job-55386/selections.jsonl --scores scores/dev_K0_R_2048_e02.jsonl --out f02/dev_K0_R_2048_e02.jsonl
```

**整體結果**
- 評分：5 筆皆 `ok`，judge 回覆皆清楚；E/F 提取不一致 0 筆。
- 準確率 0.600（3/5）。候選保留率 1.000、齊全率 1.000；選中保留率 0.800、齊全率 0.600。
- 結果分類：答對 3、沒選到 2。串聯問題 0 項。

**逐題結果與兩版比較**

| 題目 | 題型 | 參考答案 | 預算版回答（摘要） | 預算版 | 缺少的證據 | top-50 參照版 |
|---|---|---|---|---|---|---|
| 2318644b | multi-session | $270 | 找不到夏威夷住宿費，無法計算 | 0，沒選到 | `s016-m000` | 0，選到仍答錯 |
| 1cea1afa | knowledge-update | 600 | 600 | 1，答對 | — | 1，答對 |
| gpt4_7a0daae1 | temporal-reasoning | 1 week | 稱缺日期，算出約 4 週 5 天 | 0，沒選到 | `s009-m006` | 1，答對（猜對） |
| 4c36ccef | single-session-assistant | Roscioli | Roscioli | 1，答對 | — | 1，答對 |
| c960da58 | single-session-user | 20 | 20 | 1，答對 | — | 1，答對 |

**對照論文 Figure 14（p.28）的分類**：預算版 CR-CG 3、WR-WG 2；top-50 版 CR-CG 4、CR-WG 1。

**初步觀察（只有 5 題，不做統計結論）**
- B02 候選階段 5 題證據全部保留，**損失都發生在 D02 選擇**：兩題各缺一則證據訊息，兩題都答錯。
- 兩題缺的證據最小覆蓋都在 2048 以內（例如 2318644b 為 1397 tokens），所以是「沒選到」而不是「放不下」，問題在選擇順序或方法，不在預算大小。
- `2318644b` 兩版都錯：即使證據齊全（top-50），模型也沒讀出夏威夷的費用。這題同時有選擇和閱讀兩個問題。
- `gpt4_7a0daae1` 只有 top-50 版答對，而那次是自行假設日期猜對的。所以兩版 0.6 與 0.8 的差距中，這一題不能算作證據帶來的提升，F03 需要一併標記。

**F02 前 5 題已完成。** 後續：
- F03：把 `gpt4_7a0daae1`（top-50 版猜對）列為第一個校準案例。
- 與 E 線約定 `needs_review` 的用途（目前每筆都是 true）。
- 結果檔 `scores/`、`f02/` 是否放進 repo，待全組決定。


### 2026-11-17　F03 準備：judge 識別鍵加入 E03 的設定雜湊

依 `E/E03/README.md`「产物与F交接」第 1–2 點：同一方法不同參數（例如權重）的回答，題號、策略、`config_version` 可能都相同，必須用 `record_id`、`reader_config_id` 區分，並保留 `selection_config_id`。

- `judge.py`：`EXTRA_KEY_FIELDS` 加入 `record_id`、`reader_config_id`、`selection_config_id`（識別鍵，也會抄進評分檔）；`EXTRA_COPY_FIELDS` 加入 `input_config_version`（串聯證據時核對用）。
- 舊資料沒有這些欄位時記為 None，舊評分檔續跑不受影響。

**已驗證**
- E03 的 25 筆（`results/dev5-k0-v1/`，5 題 × R/MMR/C/Q/FL）dry-run：讀到 25 筆，答案來源都是 `raw_output`，識別鍵 25 個都不同。
- 把其中一筆的 `selection_config_id` 改掉後，識別鍵不同（同方法不同權重可以區分）。
- `scores/dev_K0_R_2048_e02.jsonl`、`scores/dev_K0_top50_e02.jsonl` 的識別鍵與對應回答檔一致，續跑不會重評。
- 22 筆測試案例 dry-run：21 筆送評、1 筆（`status=error`）依規則跳過，與先前相同；F02 測試資料串聯結果不變（Q 1/1、R 1/3、問題 3+1 項）。

**發現**：E03 的 R 策略 5 筆，與 E02 預算版（job 55386）的歷史文字（`history_sha256`）和回答全文**完全相同**。F03 校準樣本中這 5 筆只算一次。

### 2026-11-17　F03 盲判表

新增 `src/evaluation/make_f03_sheet.py`：讀入多個回答檔，依 `history_sha256` 與回答全文去重，依題分組後打亂順序並改用編號，輸出盲判表（無 judge 結果、無策略名稱）與對照檔。

```bash
.venv/bin/python src/evaluation/make_f03_sheet.py --answers AI6103-DL-Project/E/E03/results/dev5-k0-v1/answers_for_f.jsonl AI6103-DL-Project/E/E02/results/job-55287/answers_for_f.jsonl AI6103-DL-Project/E/E02/results/job-55386/answers_for_f.jsonl --out-dir f03
```

- 輸出：`f03/dev5_blind_sheet.csv`（給判斷者）、`f03/dev5_key_DO_NOT_OPEN.csv`（判完才打開）、`f03/判斷說明.md`（判斷規則，初版 v0.1，判完後修訂為 v0.2）。
- 讀入 35 筆，去重後 **26 筆**（5 題）。除了 E03 R＝E02 預算版（5 筆），另外發現：`4c36ccef`、`1cea1afa` 的 MMR 與 R 相同、Q 與 C 相同（選出的材料一樣，回答也一樣）。
- 題型分布：temporal-reasoning 6、single-session-user 6、multi-session 6、single-session-assistant 4、knowledge-update 4。

### 2026-11-17　F03 首批校準：人工判斷與 judge 比對

**判斷**：使用者依 `f03/判斷說明.md` 判完 26 筆（判 1：11 筆；判 0：15 筆）。核對時發現 S06 的「猜測」誤勾（回答沒有給出答案），已由使用者修正。

**judge**：對 E03 的 25 筆執行真實評分（25 筆皆 `ok`、回覆皆清楚）。

```bash
.venv/bin/python src/evaluation/judge.py --answers AI6103-DL-Project/E/E03/results/dev5-k0-v1/answers_for_f.jsonl --out scores/dev_K0_e03_5methods.jsonl
```

| 策略 | R | MMR | C | Q | FL |
|---|---|---|---|---|---|
| 準確率（5 題） | 0.6 | 0.6 | 0.4 | 0.4 | 0.2 |

- E03 的 R 與 E02 預算版回答相同，兩次 judge 結果也相同（0、1、0、1、1）：**同樣的輸入，judge 結果可重現**。
- 權重為暫定開發值（MMR、C：λ=0.5；Q：λ=0.5、γ=0.5；FL：λ=γ=0），尚未經 D06 調參；只有 5 題，不作方法比較的結論。

**比對**：新增 `src/evaluation/compare_f03.py`。依對照檔把每個編號連回所有重複回答的評分，重複回答的 judge 結果必須相同，否則列為問題。

```bash
.venv/bin/python src/evaluation/compare_f03.py --sheet f03/dev5_blind_sheet.csv --key f03/dev5_key_DO_NOT_OPEN.csv --scores scores/dev_K0_e03_5methods.jsonl scores/dev_K0_top50_e02.jsonl scores/dev_K0_R_2048_e02.jsonl --out f03/dev5_compare.csv
```

| 項目 | 結果 |
|---|---|
| 不重複回答 | 26 筆（展開為 30 種設定），**一致 26 筆，一致率 1.000** |
| 人工 1／judge 1 | 11 |
| 人工 0／judge 0 | 15 |
| 分歧 | 0；各題型皆 100% |
| 勾猜測 | S02、S03、S05；其中 S02 判 1（猜對），judge 也判 1 |
| 勾不確定 | 無 |
| 比對問題 | 無 |

**解讀**
- 與論文 p.21 Table 6 一致（GPT-4o 在這些題型與人工一致率 97–98%）。
- ~~26/26 的 95% 信賴區間下限約 0.87~~（2026-11-18 撤回：同一題的多個回答彼此相關，不能當作 26 筆獨立樣本計算區間；只報告 26/26 並註明限制）。
- 猜對的情況 judge 依論文規則判對，無法由 judge 找出，需靠人工的「猜測」標記另外報告。

**本批校準未涵蓋（報告須註明）**
1. 偏好題、拒答題沒有樣本，而這兩類是 Table 6 中 judge 最容易判錯的（約 90%）。
2. 只有 5 題，同一題的回答相似，樣本獨立性有限。
3. 只有一位判斷者；`gpt4_7a0daae1` 與 E02 的部分回答判斷者事先看過結果。
4. 沒有出現 R7 的模糊情況（"at least 20" 這類）。

**判斷說明 v0.2**：收窄「猜測」定義（必須給出具體答案；原說明把常識推論也列為猜測，造成 S22 等標準不一致）、新增 R7（帶保留語的數字答案）、R4 補上「範圍」、說明勾選欄填法並附本批實例。

**待決定**
- 是否請一位組員獨立判同一份盲判表（可計算人工之間的一致率）。
- 偏好題、拒答題樣本：請 A 線或 E 線補，或在報告中列為限制。
- 起草 F03 的固定評分設定（judge 模型版本、參數、prompt 來源、判分與分歧處理規則）。

### 2026-11-17　F03 固定評分設定草案（`SCORING_CONFIG.md`）

新增 `SCORING_CONFIG.md`，版本 `f03-v1`（草案）。內容：judge 模型與參數、prompt 來源、送評內容、判分規則、技術失敗與缺漏回答的處理、人工判斷與分歧處理流程、重新校準條件、首批校準結果與保存位置、待確認事項。

**起草時發現：準確率的分母與 E03 交接要求不一致（須改程式，待確認）**
- 目前 `judge.py` 把 E 的 `status` 不是 `ok` 的回答記為 `no_answer`、不送評，摘要的準確率**只用 `ok` 的筆數當分母**；截斷的回答也被當成沒有回答。
- E03 README 要求技術失敗、截斷、空回答「不能删掉后计算分母」。
- 建議：截斷照樣送評；空回答與補跑後仍失敗的技術失敗算 0；摘要分母改為全部筆數；有 `api_error` 時警告結果未完成。
- 目前所有開發回答都是 `ok`，已記錄的準確率不受影響。等全組確認第五節後再修改程式。

### 2026-11-18　依 E 線確認修改缺漏回答的計分（`scoring_config_version = f03-v1`）

E 線回覆 SCORING_CONFIG 第五節的選項：**1A 2A 3A 4A 5A**。

**`judge.py`**
- 送評條件：`ok` → `ok` 加上 `truncated`（截斷照樣評已產生的文字）。
- `empty`、`technical_failure` 與不在約定內的狀態：記為 `status=no_answer`、**`label=0`**（原本是 null）。
- 摘要：準確率分母改為 `ok` + `no_answer`（全部筆數）；每個設定加印一行組成（送評、截斷、各類未送評）；有 `api_error` 時警告結果未完成；有技術失敗時提醒確認 E 已補跑；有不在約定內的狀態時警告。
- 每筆評分新增 `scoring_config_version`、`e_status`。
- 舊評分檔的 `no_answer`（`label` 為 null）讀取時一律視為 0。
- dry-run 會標示「不送評」與「截斷」的回答。

**`join_f02.py`**
- `no_answer` 的列：`label` 補為 0，結果分類為新的「**生成失敗**」，不依證據歸因。
- 截斷的列：照一般方式分類，問題欄註記「回答截斷」。
- 有列沒有分數（缺評分或 `api_error`）時警告結果未完成。
- CSV 新增 `e_status` 欄。

**已驗證**（judge 以假函式替代，未呼叫 API、未讀取 `.env`）
- 假資料 5 筆（ok、truncated、empty、technical_failure、error 各一）：只有 ok 與 truncated 送評（假 judge 被呼叫 2 次）；準確率 0.400（2/5），分母為 5；摘要組成與兩個警告正確；續跑時 5 筆都跳過。
- 串聯同一批假分數：生成失敗 3、答對 2，截斷註記正確。
- 舊格式（`no_answer` 的 label 為 null）加上一筆 `api_error`：分母 4、api_error 警告正確；串聯顯示「未評分」並警告。
- **舊結果完全不變**：E02 預算版 0.600、top-50 版 0.800、E03 五種方法（0.4／0.2／0.6／0.4／0.6）；兩個串聯結果與分類不變；F03 比對 26/26。
- 22 筆測試案例 dry-run：21 筆送評，1 筆（`1e043500`，`status=error`）標示為不送評、算錯。**這是預期中的變化**：原本這筆被排除在分母外，現在算 0。預期分數檔沒有這一題，所以預期比對不受影響。
- F02 測試資料：Q 1/1、R 1/3、問題 3+1 項，不變。

`SCORING_CONFIG.md`：第五節改為已定並寫入實作細節與補跑流程；第三節 `needs_review` 定為維持現狀；第八節移除已確認項目。其餘項目尚待全組確認，整份仍為草案。


### 2026-11-18　評分標準整理成可分享給組員的版本

- `判斷說明.md` 升為 v0.3 並放進 repo（`F/判斷說明.md`）：例子改為只描述情況、**不列盲判表編號**（原 v0.2 的例子寫了編號與判法，會讓之後的第二位判斷者事先知道答案）；判斷依據加入偏好題的論文規則（與 `prompts.py` 的官方模板一致）；註明拒答題由 H06 負責。規則內容未改變。
- `SCORING_CONFIG.md`：開頭加入相關文件表與快速查閱指引；適用範圍註明只含可回答題、拒答題由 H06 負責；判斷說明改指 repo 中的檔案；本機檔案（盲判表、對照檔、比對表、評分檔）註明未上傳；偏好題的待確認事項改為向 D、E 線索取 6 題回答。
- 盲判表與對照檔仍只放本機，不分享。

### 2026-11-18　依 E 線審閱回覆修正比對與分母（F03 定稿前）

E 線審閱《判斷說明》v0.3、`SCORING_CONFIG.md` 草案與 `671e619` 後的結論：F03 大致完成，首輪一般題校準完成，`f03-v1` 待定稿。定稿前須處理三件事，本次完成程式與文件部分（偏好題仍待 D、E 提供回答）。

**1. `compare_f03.py` 會漏掉沒評到的成員（E 線可重現的問題）**
- 原因：一個盲判編號代表多筆來源紀錄時，舊程式只要**任一個**成員找得到評分就通過；而且用 (題號, 策略, 變體, 歷史雜湊) 這組較粗的鍵取最後一筆，跨批重複的 R 會被合在一起，無法確認兩次評分都存在。
- `make_f03_sheet.py`：多輸出**成員檔** `*_members_DO_NOT_OPEN.csv`，每筆來源紀錄一列（含被去重的），記錄來源檔、行號、完整識別鍵（與 `judge.py` 的 `record_key` 相同）與回答指紋。dev5 的成員檔用相同輸入與 seed 重新產生，對照檔與原本**逐位元組相同**，編號不變。
- `compare_f03.py` 改寫：參數 `--key` 改為 `--members`。每個成員都必須 (1) 來源內容和產生盲判表時相同、(2) 找得到自己識別鍵的評分、(3) 評分對應目前內容且不是 `api_error`、(4) 多個評分檔中的分數一致；同一編號的成員分數也必須一致。任一項不符即列出問題，印「校準狀態：未完成」，退出碼 1。
- 輸出樣本數的三種算法：來源紀錄 → 設定紀錄 → 不重複回答。

```bash
.venv/bin/python src/evaluation/compare_f03.py --sheet f03/dev5_blind_sheet.csv --members f03/dev5_members_DO_NOT_OPEN.csv --scores scores/dev_K0_e03_5methods.jsonl scores/dev_K0_R_2048_e02.jsonl scores/dev_K0_top50_e02.jsonl --out f03/dev5_compare.csv
```

**2. 重新匯出後續評會跳過（`judge.py`）**
- 原因：續評只看識別鍵；E 補跑後重新匯出、鍵不變而內容改變時，舊分數會被沿用。
- 每筆評分新增 `answer_sha256`（E 的 status ＋ 實際送評文字）。續評時指紋不同就重評；舊評分檔沒有指紋，改用 `response_sent`（送評的）或「同樣不送評」（`no_answer`）比對。

**3. 分母與能否發布（`judge.py`）**
- 新參數 `--expect-n`。摘要會核對：回答檔每筆都有針對目前內容的完成評分、沒有 `api_error`、筆數等於預定筆數、各設定題目相同；最後印「可發布：是／否」與原因。評分檔中不屬於這份回答檔的紀錄不列入計算。
- `--summary-only` 也會讀回答檔做上述檢查。

**已驗證**（judge 以假函式替代，未呼叫 API、未讀取 `.env`）
- 現有資料：比對結果 35 → 30 → 26，**26/26，校準狀態完整**（與 E 線核對的樣本數相同）。
- E 線描述的情況：刪掉一個重複成員（4c36ccef Q/budget）的評分 → 列出「沒有評分」、未完成。不提供 E02 預算版評分檔 → 5 個跨批 R 成員都列出。`api_error` 與分數衝突也都列出。
- 假回答 5 筆（ok、truncated、empty、technical_failure、ok＋judge 失敗）：截斷照樣送評、空回答與技術失敗計 0、`api_error` → 「可發布：否」；續評只重評失敗那筆 → 0.600（3/5）、「可發布：是」。
- E 重新匯出（技術失敗補跑成功、另一筆內容改變，識別鍵不變）：只看摘要 → 「2 筆內容已變更、評分是舊的」、不可發布；續評 → 只重評這 2 筆。
- 回答檔多一筆沒評分、預定筆數不符 → 兩個原因都列出。
- **舊結果不變**：三份評分檔的 MD5 不變；摘要準確率 E03（R 0.6、MMR 0.6、C 0.4、Q 0.4、FL 0.2）、預算版 0.6、top-50 0.8，三份都「可發布：是」；E03 評分檔副本續評 0 筆、檔案逐位元組不變；22 筆測試案例與預期 21/21 一致。

**文件**
- `SCORING_CONFIG.md`：第三節 `needs_review` 改為「沒有可直接使用的提取答案，送評依 `status`／`parse_status`」；第五節加入分母與完整性、重新匯出後的重評；第六節加入校準完成的條件；第七節樣本數改寫為 35 → 30 → 26、**刪除信賴區間**、加入成員檔；第八節第二位判斷者改為優先複查偏好題。
- `判斷說明.md` v0.4：R7 的 "at least 20" 改為固定判 0（題目問確切數量時；問「至少多少」才接受下限）；「猜測」改為只標記回答中看得出來的猜測。首批勾猜測的 3 筆在回答中都明說了假設或替代日期，新定義下仍成立；首批沒有 R7 的情況，判斷結果不變。

**仍待處理**：偏好題 6 題的回答（D、E）→ 校準 → 全組確認 `f03-v1` 定稿。

### 2026-11-18　`f03-v1` 定稿

- 本輪不做偏好題校準。`SCORING_CONFIG.md` 改為定稿：版本標為 `f03-v1`（定稿）；第七節限制說明偏好題未校準，並引用論文 p.21 Table 6（judge 在這類題與人工一致率約 90%）；第六節偏好題改為「建議補做、judge 與 prompt 不變所以不升版」；第八節改名為「後續事項（不影響定稿）」。
- `判斷說明.md` 偏好題列的「待補充」改為「本輪未做」，規則不變，版本仍是 v0.4。
- 程式未修改。D06、F04 從此共用 `f03-v1`。

### 2026-11-20　F04 第 1 批：正式題 `g02-v1/batch-01` 評分（程式未修改）

**輸入**（E 線分支以壓縮檔下載到本機 `AI6103-DL-Project-e04-results/`，非 git clone，**commit 號碼待向 E 線確認**）
- 回答：`E/E04/results/g02-v1/batch-01/answers_for_f.jsonl`，100 筆 = 10 題 × K0/K1 × R/MMR/C/Q/FL，預算 2048；`input_config_version = a03-v2`；E status `ok` 95、`truncated` 5；E 的 `summary.json`：expected 100、missing 0。
- 評價檔：`A-数据线/A04/output/formal_eval.jsonl`（80 題）；問題檔：`A-数据线/A03/output/public/formal_questions.jsonl`（80 題）。
- 本批題型：multi-session 4、temporal-reasoning 3、knowledge-update 2、single-session-assistant 1；無拒答題。

```bash
.venv/bin/python src/evaluation/judge.py --answers "AI6103-DL-Project-e04-results/E/E04/results/g02-v1/batch-01/answers_for_f.jsonl" --eval "AI6103-DL-Project-e04-results/A-数据线/A04/output/formal_eval.jsonl" --questions "AI6103-DL-Project-e04-results/A-数据线/A03/output/public/formal_questions.jsonl" --out scores/formal_g02-v1_batch-01.jsonl --expect-n 100
```

**完整性**：100 筆皆 `ok`，「可發布：是」；`judge_model_returned` 全為 `gpt-4o-2024-08-06`；`scoring_config_version` 全為 `f03-v1`；judge 回覆格式全為 `clean`。截斷 5 筆照 1A 送評（`gpt4_8e165409` K0/K1 的 R、MMR 皆判 1；`7a87bd0c` K0 C 判 0）。

**準確率**（10 題，僅供進度核對，不作方法比較的結論）

| | R | MMR | C | Q | FL |
|---|---|---|---|---|---|
| K0 | 0.5 | 0.5 | 0.3 | 0.4 | 0.3 |
| K1 | 0.5 | 0.5 | 0.4 | 0.4 | 0.3 |

- 10 題中 3 題十種設定全對（`a4996e51`、`a40e080f`、`gpt4_8e165409`），5 題全錯（`10d9b85a`、`69fee5aa`、`gpt4_731e37d7`、`gpt4_15e38248`、`6e984301`）；方法間的差異只來自 `f0853d11`（R、MMR 對，C、Q、FL 錯）與 `7a87bd0c`。
- K0 與 K1 唯一不同的是 `7a87bd0c` 的 C（K0 錯、K1 對）。50 組 K0/K1 配對中 16 組選中材料與回答完全相同。
- 100 筆中不重複的回答 68 筆（F05 抽樣以去重後的回答計）。

**評分用量**（F07）：judge 輸入 42,115 token、輸出 198 token；依 gpt-4o-2024-08-06 的牌價估算約 0.11 美元（以帳單為準）。

**待辦**：向 E 線確認分支名稱與 commit；E 若補跑或重新匯出，重新下載後用同一行指令重評（內容改變的回答會依 `answer_sha256` 自動重評）。

### 2026-11-20　F04 第 2–5 批評分，前 5 批合計（程式未修改）

**輸入**：E 線分支重新下載到 `AI6103-DL-Project-e04-results/`（舊下載改名為 `..._V1`；兩者的 batch-01 回答、評價檔、問題檔 MD5 相同，第 1 批評分仍有效，以 `--summary-only` 確認「可發布：是」）。commit 號碼仍待向 E 線確認。指令同第 1 批，只改 `batch-0X` 與 `--out scores/formal_g02-v1_batch-0X.jsonl`。

**完整性**（逐批讀評分檔核對，不只看摘要）

| 批次 | 筆數 | 每筆都有對應目前內容的評分 | E 截斷 | 準確率（10 設定平均） |
|---|---|---|---|---|
| batch-01 | 100 | 是 | 5 | 0.41 |
| batch-02 | 100 | 是 | 1 | 0.48 |
| batch-03 | 100 | 是 | 2 | 0.36 |
| batch-04 | 100 | 是 | 0 | 0.33 |
| batch-05 | 100 | 是 | 1 | 0.34 |

- 合計 500 筆、50 題，批次間題目不重複；全部 `ok`、`judge_model_returned = gpt-4o-2024-08-06`、`f03-v1`、judge 回覆皆 `clean`。
- 截斷 9 筆照 1A 送評：判 1 的 4 筆（皆 `gpt4_8e165409`），判 0 的 5 筆。

**前 50 題準確率**（進度核對用；正式結論待 80 題完成後由 F06 計算區間）

| | R | MMR | C | Q | FL |
|---|---|---|---|---|---|
| K0 | 0.42（21/50） | 0.42（21/50） | 0.38（19/50） | 0.38（19/50） | 0.28（14/50） |
| K1 | 0.46（23/50） | 0.48（24/50） | 0.36（18/50） | 0.40（20/50） | 0.26（13/50） |

- 50 題中 8 題十種設定全對、16 題全錯、26 題結果因設定而異。
- 題型：temporal-reasoning 19、multi-session 18、knowledge-update 6、single-session-user 5、single-session-assistant 2。
- 不重複回答 370 筆（依題號、歷史、原始輸出去重；F05 抽樣以此為母體）。

**評分用量**（F07）：judge 輸入 194,369 token、輸出 940 token；依牌價估算約 0.50 美元（以帳單為準）。

**待辦**：剩 30 題（batch-06 起）；向 E 線確認 commit；F05 抽樣。

### 2026-11-20　F04 第 6–8 批評分，**F04 完成**（80 題 × 10 設定 = 800 筆）

**輸入**：E 線上傳 batch-06～08 後更新到 `AI6103-DL-Project-e04-results/`。更新後評價檔、問題檔 MD5 不變；batch-01～05 回答與已評內容相同，皆仍「可發布：是」。8 批合計 80 題＝全部正式題，批次間不重複。commit 號碼仍待向 E 線確認。

**完整性**（逐批讀評分檔核對）：8 批每筆都有對應目前內容的評分；全部 `ok`；`judge_model_returned` 全為 `gpt-4o-2024-08-06`；全為 `f03-v1`；judge 回覆全為 `clean`。E 截斷 14 筆照 1A 送評（判 1 的 6 筆）。

| 批次 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 |
|---|---|---|---|---|---|---|---|---|
| 截斷 | 5 | 1 | 2 | 0 | 1 | 1 | 1 | 3 |
| 平均準確率 | 0.41 | 0.48 | 0.36 | 0.33 | 0.34 | 0.32 | 0.49 | 0.66 |

**batch-05 意外重評**：評分檔有 195 行。13:45–13:50 第一次評完 100 筆；另一個同批程序（看起來是同時啟動、被暫停後於 15:23 才繼續）依開始時的進度重評了 95 筆。回答內容相同（`answer_sha256` 一致），多花約 0.09 美元。
- 重評一致率 **94/95**；不同的 1 筆：`58ef2f1c` K0 FL（single-session-user，參考答案 February 14th；回答先說找不到動物收容所的晚宴，又說在情人節晚宴當志工），第一次 No、第二次 Yes。屬 R2 類邊界案例。
- ~~原採選項 A：以最後一次為準（K0 FL 27/80）~~。**已改為以團隊歸檔版為準**（第一次評分，K0 FL 26/80），見下方「2026-11-20 改用團隊歸檔的 F04 評分」。
- 防範：`judge.py` 新增檔案鎖（見下一節）。

**80 題準確率**（點估計；配對差值與 95% 信賴區間由 F06 計算）

| | R | MMR | C | Q | FL |
|---|---|---|---|---|---|
| K0 | 0.475（38） | 0.463（37） | 0.400（32） | 0.388（31） | 0.325（26） |
| K1 | 0.525（42） | 0.512（41） | 0.400（32） | 0.438（35） | 0.312（25） |

- 題型：temporal-reasoning 27、multi-session 26、knowledge-update 11、single-session-user 9、single-session-assistant 7。
- 80 題中 12 題十種設定全對、24 題全錯、44 題因設定而異。
- 不重複回答 602 筆（F05 抽 20% 約 120 筆）。

**交付檔**（本機，不上傳 repo）
- 逐批評分檔：`scores/formal_g02-v1_batch-01.jsonl` ～ `batch-08.jsonl`（含 batch-05 的重評紀錄）。
- 合併檔：`scores/formal_g02-v1_all.jsonl`，800 筆，由團隊歸檔的 8 批直接串接（batch-05 為第一次評分），供 F06 使用。原 195 行檔改名為 `scores/formal_g02-v1_batch-05_含重評195行_備份.jsonl`。

**評分用量**（F07）：judge 輸入 310,877 token、輸出 1,518 token（以合併檔的 800 筆計，不含 batch-05 第一次被取代的 95 筆）；依牌價估算約 0.79 美元，實際帳單另含重評的約 0.09 美元。

### 2026-11-20　`judge.py`：同一評分檔只允許一個程序寫入

- 新增 `acquire_run_lock`：開始評分前在評分檔旁建立 `<評分檔>.lock`，以作業系統檔案鎖（flock）鎖住；已被鎖住就停止並說明如何處理。程序結束（含當機、Ctrl+C）會自動解鎖，殘留的 `.lock` 檔不影響下次執行；被 Ctrl+Z 暫停的程序仍持有鎖，也會擋下第二個程序。不支援 flock 的系統（Windows）只印提示。
- 只看摘要（`--summary-only`）與 dry-run 不需要鎖。
- **已驗證**（假 judge）：第一個程序評分中再開第二個 → 第二個立即停止、未呼叫 API；第一個正常完成 5 筆、評分檔 5 行；結束後再跑 → 續評 0 筆；暫停（SIGSTOP，等同 Ctrl+Z）的程序仍擋下第二個，恢復後正常完成。真實 batch-05 評分檔摘要不受影響。

### 2026-11-20　F06 分析程式（`f06_analysis.py`，初版）

**口徑**（任務表 F06、G02 README、《项目解释和大纲》第三、四節）
- 主結果：十種設定的正確率、證據齊全題數與平均消息級保留率（A04 `selection_metrics.jsonl`）、平均材料長度（A04 `context_tokens`）。選擇耗時需 D08 紀錄，尚未納入。
- 配對差值（按題配對）：覆蓋增量 Q − R／MMR／C／FL（各索引）；事實增量 K1 − K0（各策略）與 K1-R − K0-Q；交互 I = (Q1 − C1) − (Q0 − C0)。每項列出錯→對、對→錯題數。
- 95% 信賴區間：以 A03 的**證據組**（80 題、78 組）為單位 cluster bootstrap，10,000 次，seed 20261120，取 2.5%／97.5% 分位數。一題 = 1.25 個百分點。
- 證據與回答：A04 四類診斷（候選沒找齊、證據放不下、可放下但沒選齊、證據齊全）× 答對題數。
- F05：主要準確率用 judge 分數（SCORING_CONFIG 第六節），F05 完成後另補 judge 可靠度，本程式結果不變。

**輸入檢查**（不符即停止）：800 筆＝80 題 × 10 設定、無重複、無 `api_error`、與 A04 的 `history_sha256` 一致（同一份材料）、每題有證據組。

```bash
.venv/bin/python src/evaluation/f06_analysis.py --scores scores/formal_g02-v1_all.jsonl --out-dir f06
```

**已驗證**
- 主結果表的證據數字與 A04 README 相同（例如 K0-R 41 題、68.56%；K1-C 27 題、49.25%）；正確率與 F04 合併結果相同；I 的點估計手算 (35−32)−(31−32) = 4 題 = +5.0 個百分點，一致。
- K0 Q − R 的區間與常態近似（約 [−19.4, +1.7]）接近。
- 少一筆、重複一筆、`api_error`、材料雜湊不一致、直接用含重評的逐批檔 → 皆停止並列出原因。
- 同 seed 重跑輸出逐位元組相同；換 seed 區間變動約 0.3 個百分點。

**初步結果**（judge 分數；F05 完成前不對外發布逐題結果）

| 比較 | 差值（百分點） | 95% CI | 錯→對／對→錯 |
|---|---|---|---|
| K0: Q − C | −1.2 | [−11.0, +7.7] | 7／8 |
| K1: Q − C | +3.8 | [−2.5, +10.1] | 5／2 |
| K0: Q − R | −8.8 | [−19.8, +1.3] | 6／13 |
| K1: Q − R | −8.8 | [−19.5, +1.3] | 6／13 |
| Q: K1 − K0 | +5.0 | [−1.3, +12.3] | 6／2 |
| K1-R − K0-Q | +13.8 | [+3.8, +24.1] | 15／4 |
| I = (Q1 − C1) − (Q0 − C0) | +5.0 | [−3.8, +13.9] | I>0 9 題／I<0 5 題 |

- 區間不含 0 的只有 K1: Q − FL（+12.5）與 K1-R − K0-Q（+13.8）。
- 證據齊全時正確率 0.68–0.94；可放下但沒選齊時 0.17–0.32（原寫約 0.65–1.0／0.2–0.4，2026-11-20 依輸出更正）。

**輸出**（本機 `f06/`，**F05 完成前不上傳**：逐題表含各設定的 judge 分數，可能影響進行中的人工判斷）：`f06_main_table.csv`、`f06_paired_diffs.csv`、`f06_evidence_by_outcome.csv`、`f06_per_question.csv`。

**待辦**：~~F05 完成後補人工抽查一致率~~（已補，見下一節）；確認選擇耗時的來源（D08）；結果交 A05 選案例。

> 2026-11-20 更新：上表與輸出已依團隊歸檔評分重跑，只有 K0: Q − FL、FL: K1 − K0 兩項改變（見下一節）；表中各項不變。

### 2026-11-20　改用團隊歸檔的 F04 評分；F05 定稿

**起因**：從 main 取得 lonelyhat 的 commit `042c294`（Archive formal F04 scores and finalized F05 review）。repo 的 `F/scores/formal_g02-v1_batch-01～08.jsonl` 中，batch-05 是本機 195 行檔的**前 100 行**（第一次評分），其餘 7 批與本機逐位元組相同。兩版 800 筆只差 1 筆：`58ef2f1c` K0 FL（F05-016），第一次 0、第二次 1；F05 人工定案為 0。

**決定**：以 lonelyhat 上傳的版本為準（F05 由他分配題目並整理，主結果 README 寫明「正式主結果沿用 F04 的原始評分」）。本機 batch-05 改為 repo 版、原檔改名備份；合併檔重建；F06 重跑。

**影響**（只有這一筆）

| 項目 | 原（最後一次） | 現（歸檔版） |
|---|---|---|
| K0-FL 正確率 | 0.338（27） | 0.325（26） |
| K0: Q − FL | +5.0 [−5.1, +15.2] | +6.2 [−4.8, +16.7] |
| FL: K1 − K0 | −2.5 [−7.6, +2.5] | −1.2 [−5.1, +2.5] |

其餘差值與區間不變；評分用量 judge 輸出 1,517 token（原 1,518），輸入不變。

**F05 定稿**（`F/F05/g02-v1/README.md`，lonelyhat 整理）：121 個盲判編號（65 題、161 筆設定紀錄）。兩位人工討論前一致 117/121（96.69%）；人工定案 vs GPT-4o 一致 **120/121（99.17%）**。唯一人機分歧 F05-075（模型答 17 天，參考 18 天，人工依時間推理一天容差判 1，GPT-4o 判 0）。正式主結果沿用 F04 judge 分數。

### 2026-11-20　F06 交付：`F/F06/`

- `f06_analysis.py` 的 `--scores` 改為可給多個檔，可直接讀團隊歸檔的 8 批。合計仍須剛好 800 筆、無重複。
- 在 repo 的 `F/` 目錄用歸檔的 8 批重跑，輸出到 `F/F06/`，和本機 `f06/` 逐位元組相同。
- `F/F06/README.md` 寫明檔案說明、主結果、主要配對差值、方法、輸入連結、重現指令。
- F05 已定稿，逐題表不再有影響人工判斷的顧慮，因此一併上傳。
- 依任務表，F06 的交付物是主結果表、主要配對差值、95% 信賴區間，且數量核對一致，至此齊全。下一步：併入 main，通知 A05 從 `F/F06/f06_per_question.csv` 選案例。

### 2026-11-20　F07 成本程式（`f07_cost.py`）與交付 `F/F07/`

**口徑**（任務表 F07、《大纲》第 3 節）：一次性成本（K0／K1 建庫，五種策略共用）＋每次提問成本（檢索＋選材＋回答）；總成本＝建庫＋T × 每次提問，T = 1、10、80、100、1000；評分單列為實驗成本。一份歷史＝一題（B04／B06 每題各建一次索引）。

**輸入**
- C05 `formal_v2_summary.json`；B04／B06 `cost.json` 逐題檢索耗時，並核對指紋。
- D08 8 個壓縮檔的 `selection_elapsed_s`，並核對交付清單指紋。
- E04 `results.jsonl`，來自分支 `e04-results` 的 commit `95438df`。用 `git archive` 取得的檔案和下載資料夾逐位元組相同。
- F04 團隊歸檔的 8 批評分檔。

**設計決定**
- K1 已記錄建庫 2,053 秒是**下限**：C04 只記了 149 鍵，18,692 鍵沿用作者快取，成本未知。另列「全量抽取估計」作敏感度：每鍵 6.14 秒 × 18,841 鍵，約 116,764 秒。
- E04 設備：batch-01 的 runtime 記錄為 A40；其餘依 F05 README，batch-07 為 L40S，其他為 A40。同題十設定都在同一批，設定間的比較不受設備影響。另附只算 A40 批次的回答耗時。
- 回答模型載入 352 秒只有 batch-01 有紀錄，視為每次開跑的固定開銷，單列、不攤入每題。
- 原本想用每次提問差推算「回本次數」，但回答耗時主要隨輸出長度變化，與索引無關，結果不可靠，因此不用。改報「K1 多花的建庫 ≈ 幾次提問的耗時」，並把每次提問差拆成檢索、選材、回答三段。

**結果**
- 建庫：K0 每份 12.1 秒；K1 每份 25.7 秒（下限），全量估計約 1,460 秒。
- 每次提問 9.3–12.3 秒，其中回答佔 78–96%，檢索約 0.03 秒。選材 R 0.4–0.5 秒、Q 1.55 秒、C 1.85 秒、FL 2.3 秒。
- K1 多花的建庫：已記錄口徑 13.6 秒，約等於 1.2–1.4 次提問；全量估計口徑約等於 127–152 次。T = 100 時，已記錄口徑的建庫佔比 ≤ 3%。
- 評分：800 筆，輸入 310,877、輸出 1,517 token，API 689.5 秒，估算 0.79 美元。

**已驗證**
- 數字與 C05 交付文件相同：967.45／2,053.00 秒、每次檢索 37.13／33.70 毫秒。
- 獨立重算 K0-R 選材平均 0.516 秒，相同。
- 少一筆、重複、用含重評的 batch-05、竄改 E04 材料指紋 → 皆停止並列出原因。
- 重跑兩次，輸出逐位元組相同。

**待確認**
- 請 E 線確認 batch-02～08 的 GPU（目前依 F05 README）。
- 請 D 線確認選材耗時的機器規格。
- 請 C 線確認全量抽取估計的假設：作者快取的抽取若用不同模型或設備，估計值會不同。

### 2026-11-20　F07 散點圖（`f07_plot.py`）

- 讀 `f07_per_query.csv`，上下兩張圖共用 y 軸（正確率）：上圖 x 為每次提問合計耗時，下圖 x 為選材耗時；藍 K0、橘 K1，灰色箭頭連接同策略的 K0 → K1。
- 只用 Python 標準庫輸出 SVG（環境沒有 matplotlib，不另外安裝）。PNG 用 macOS `sips` 轉出。箭頭用三角形繪製，不用 SVG marker，因為 `sips` 不支援 marker，轉出的 PNG 會沒有箭頭。
- 顏色取預設調色盤類別色第 1、2 格（#2a78d6、#eb6834），已用色盲檢查腳本驗證通過。重疊的標籤個別調整：下圖的 K0-C／K1-C 幾乎重合，合併成一個標籤。
- 輸出：`F/F07/f07_cost_vs_accuracy.svg`、`.png`；README 開頭已嵌入 PNG。
