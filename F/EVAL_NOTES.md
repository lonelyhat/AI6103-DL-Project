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
| 組內專案（A01、A02、E02…） | `AI6103-DL-Project-main_V2/...` | `../...`，例如 `../E/E02/inputs/...` |
| 評分與串聯結果 | `scores/`、`f02/` | `F/scores/`、`F/f02/`（自動建立） |
| `data/`、`third_party/`、`results/` | 本機才有 | **不需要**，評分只用 A01 的評價檔與問題檔 |

- A01、A02 的位置由 `src/evaluation/paths.py` 自動判斷，在 repo 中**不需要修改任何路徑**。執行 `python src/evaluation/paths.py` 可確認抓到的位置。
- 第一次使用：在 `F/` 底下建立虛擬環境並安裝套件（`python3 -m venv .venv`、`.venv/bin/pip install -r requirements.txt`），再把 `.env.example` 複製成 `.env` 填入自己的 API key（見第二節）。`.env` 與 `.venv` 已被 repo 的 `.gitignore` 排除，**不會也不應上傳**。
- 例：在 repo 中評分 E02 top-50 參照版（在 `F/` 執行）：

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
├── requirements.txt                  ← 需要安裝的 Python 套件
├── .env.example                      ← API key 設定範本（複製成 .env 後填入）
├── .env                              ← 你的 API key（自己建立，不上傳）
├── .gitignore
├── src/evaluation/
│   ├── judge.py                      ← 評分主程式
│   ├── prompts.py                    ← 評分 prompt（逐字複製自官方，勿改）
│   ├── paths.py                      ← 路徑設定：組內專案、A01、A02 的位置（換版本只改這裡）
│   └── join_f02.py                   ← F02 串聯：候選、選中材料、證據、評分
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
├── results/                          ← v0.1 的舊結果（僅保留紀錄）
├── data/                             ← 官方題目資料
│   ├── longmemeval_oracle.json       （15 MB，只含證據 session）
│   └── longmemeval_s_cleaned.json    （277 MB，專案使用的 LongMemEval-S）
├── third_party/LongMemEval/          ← 官方 repo（只讀取，不直接執行）
├── AI6103-DL-Project-main_V1/        ← 組內專案舊版（保留比對用，程式已不使用）
└── AI6103-DL-Project-main_V2/        ← 組內專案（2026-11-17 下載；A01、A02、E02 在這裡）
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
| `--limit N` | 只處理前 N 筆 | 全部 |
| `--dry-run` | 只印 prompt，不呼叫 API | 關閉 |
| `--summary-only` | 只印摘要 | 關閉 |

### 4. 中斷了怎麼辦

直接用同一行指令重新執行。程式會跳過已經處理完的紀錄（`ok` 與 `no_answer`），只處理剩下的和之前 `api_error` 的，不會重複花錢。

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
| `e_status` | 僅 `no_answer` 時出現：E 回答檔中的原始 status |

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
| reader 是否輸出 `Final answer:` | E 線（E02） | **否**：E02 用官方 CoN 原始 prompt，沒有要求標記，所以 hypothesis 全為空、整段送評（與官方評分程式相同）。`needs_review` 因此每筆都是 true，**需與 E 線約定這個標記的用途** |
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

**E02 首批 5 題的實際檔案**（都在 `AI6103-DL-Project-main_V2/E/E02/`）：

| 用途 | 預算版（K0/R/2048） | top-50 參照版 |
|---|---|---|
| 候選 | `inputs/sources/b02_candidates.jsonl` | 同左 |
| 選中 | `inputs/sources/d02_selections.jsonl` | `inputs/topk_selections.jsonl` |
| 回答 | 尚未生成 | `results/job-55287/answers_for_f.jsonl` |

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
- 這題在預算版中證據沒有選齊；若預算版也答對，會歸為「答對但證據不齊」。

**用途**：本次是流程驗證，也是之後預算版（K0/R/2048）的參照組。同一題若預算版錯、參照版對，問題多半在預算或選擇方法；兩版都錯則可能在閱讀模型。

### 待辦：同步 F_Evaluation 分支（2026-11-17 整理）

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
