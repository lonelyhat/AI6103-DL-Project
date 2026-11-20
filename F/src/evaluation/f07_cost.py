"""
F07 線上成本與多次複用成本

【做什麼】（任務表 F07；口徑依《项目解释和大纲》第 3 節「成本表說明收益是否值得」）
  合併 C05（建庫）、B04/B06（檢索）、D08（選材）、E04（回答）、F04（評分）的正式紀錄，輸出：
    1. 一次性成本：K0、K1 各建一次庫（由 R/MMR/C/Q/FL 共用），按階段 × 設備列出耗時與 Token
    2. 每次提問成本：十種設定的平均檢索、選材、回答耗時與 Token
    3. 複用成本：同一份歷史被提問 T 次時，總耗時 = 建庫 + T × 平均每次提問
       並算出 K1 比 K0 多花的建庫時間，要提問幾次才攤得回來（或攤不回來）
    4. E04 各批設備與生成速度
    5. 評分（實驗成本，單列）：judge Token、耗時、依牌價估算的費用

【「建庫」的單位】
  LongMemEval 每題有自己的一份對話歷史，B04/B06 也是每題各建一次索引。
  因此「一份歷史」= 一題：複用表用每份歷史的平均建庫成本（80 份的合計 ÷ 80），
  T 是同一份歷史被提問的次數。另附 80 份合計（＝本次實驗實際消耗，T = 1）。

【口徑與限制】（報告時照這個寫）
  - 各階段在不同設備上執行：建庫與檢索 A40（Stella）；C04 補抽本機 Ollama（Llama 3.1 8B Q3_K_M）；
    選材 CPU（D08）；回答 A40，batch-07 為 L40S（E04）。秒數相加只當參考，表中保留各階段原值。
  - C04 只記錄了 149 個補抽事實鍵的耗時；另 18,692 個鍵沿用作者快取，原始成本未知。
    所以 K1 的已記錄建庫成本是「下限」。另列一行「全量抽取估計」：
    以已記錄的每鍵平均耗時 × 全部事實鍵數推估，只作敏感度參考。
  - E04 模型載入時間只有 batch-01 有紀錄（A40，約 352 秒），屬每次開跑的固定開銷，單獨列出、不攤入每題。
  - E04 的每批題目固定、同一題的十種設定在同一批，所以設定之間的比較是同設備配對；
    另列只用 A40 批次（70 題）的回答耗時供參考。
  - 評分費用以 gpt-4o-2024-08-06 牌價估算（見 JUDGE_PRICE_PER_M），不是帳單金額。

【檢查】（任一項不符即停止）
  C05 記錄的 B04/B06 檔案指紋與實際檔案相同；B04/B06 逐題檢索耗時加總等於 C05；
  D08 壓縮檔指紋與交付清單相同；D08、E04、F04 各 800 筆、無重複、題目與設定完全相同；
  三者的 history_sha256 逐筆一致（同一份材料）；E04 沒有技術失敗；F04 全為 ok 或 no_answer。

【用法】（在程式根目錄執行；C05、B、D08 預設讀組內 repo，見 paths.py）
  .venv/bin/python src/evaluation/f07_cost.py \
      --e04-dir AI6103-DL-Project-e04-results/E/E04/results/g02-v1 \
      --scores scores/formal_g02-v1_batch-0{1,2,3,4,5,6,7,8}.jsonl --out-dir f07
  E04 結果在分支 e04-results（commit 95438df），不在 main。取得方式（在組內 repo 根目錄）：
      git fetch origin
      mkdir -p /tmp/e04 && git archive 95438df E/E04/results/g02-v1 | tar -x -C /tmp/e04
      → --e04-dir /tmp/e04/E/E04/results/g02-v1
"""

import argparse
import csv
import hashlib
import io
import json
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import TEAM_ROOT  # noqa: E402

INDICES = ["K0", "K1"]
STRATEGIES = ["R", "MMR", "C", "Q", "FL"]
SETTINGS = [(i, s) for i in INDICES for s in STRATEGIES]
REUSE_T = [1, 10, 80, 100, 1000]

# E04 各批 GPU：batch-01 的 runtime.jsonl 記錄 NVIDIA A40；其餘批次沒有設備欄位，
# 依 F/F05/g02-v1/README.md（lonelyhat，2026-11-20）：「batch-07 使用 L40S，其余七批使用 A40」。
E04_DEVICE = {f"batch-0{b}": "A40" for b in range(1, 9)}
E04_DEVICE["batch-07"] = "L40S"

# gpt-4o-2024-08-06 牌價（美元／百萬 token），用於估算評分費用
JUDGE_PRICE_PER_M = {"input": 2.50, "output": 10.00}


def load_jsonl_text(text):
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return load_jsonl_text(f.read())


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def key(r):
    return (r["question_id"], r["index"], r["strategy"])


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def r3(x):
    return round(x, 3)


def main():
    p = argparse.ArgumentParser(description="F07 線上成本與多次複用成本")
    p.add_argument("--c05", default=str(TEAM_ROOT / "C05/formal_v2_summary.json"))
    p.add_argument("--d08-dir", default=str(TEAM_ROOT / "D/D08/delivery"))
    p.add_argument("--e04-dir", required=True, help="E04 結果目錄（內含 batch-01 … batch-08）")
    p.add_argument("--scores", nargs="+", required=True, help="F04 正式評分檔（團隊歸檔的 8 批）")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    problems = []

    # ---------- C05 與 B04/B06 ----------
    c05 = json.loads(Path(args.c05).read_text(encoding="utf-8"))
    ext = c05["c04_extraction"]
    idx_cost, retrieval_q = {}, {}
    for i in INDICES:
        c = c05["index_cost"][i]
        src = TEAM_ROOT / c["source"]
        # C05 fingerprints the JSON after normalizing Git checkout line endings.
        cost_hash = hashlib.sha256(src.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if cost_hash != c["cost_sha256"]:
            problems.append(f"{i}：{c['source']} 的指紋與 C05 記錄不同")
        b = json.loads(src.read_text(encoding="utf-8"))
        retrieval_q[i] = {q: v["query_encode_s"] + v["rank_s"] for q, v in b["per_question"].items()}
        if abs(sum(retrieval_q[i].values()) - c["retrieval_s"]) > 1e-6:
            problems.append(f"{i}：逐題檢索耗時加總與 C05 不同")
        idx_cost[i] = c

    # ---------- D08 ----------
    d08_dir = Path(args.d08_dir)
    manifest = json.loads((d08_dir / "manifest.json").read_text(encoding="utf-8"))
    d08 = {}
    for bid, m in sorted(manifest["batches"].items()):
        zp = d08_dir / m["archive"]
        if sha256_file(zp) != m["archive_sha256"]:
            problems.append(f"D08 {bid}：壓縮檔指紋與交付清單不同")
        with zipfile.ZipFile(zp) as z:
            name = next(n for n in z.namelist() if n.endswith("selections.jsonl"))
            for r in load_jsonl_text(z.read(name).decode("utf-8")):
                if key(r) in d08:
                    problems.append(f"D08 重複紀錄 {key(r)}")
                d08[key(r)] = r

    # ---------- E04 ----------
    e04, e04_batch, batch_info = {}, {}, []
    e_dir = Path(args.e04_dir)
    for bdir in sorted(e_dir.glob("batch-0*")):
        bid = bdir.name
        rows = load_jsonl(bdir / "results.jsonl")
        for r in rows:
            if key(r) in e04:
                problems.append(f"E04 重複紀錄 {key(r)}")
            if r["status"] not in ("generated", "truncated", "empty"):
                problems.append(f"E04 {bid} {key(r)} 狀態 {r['status']}")
            if r.get("attempt", 1) != 1:
                problems.append(f"E04 {bid} {key(r)} 第 {r['attempt']} 次嘗試（需確認耗時口徑）")
            e04[key(r)] = r
            e04_batch[key(r)] = bid
        gen = sum(r["generation_seconds"] for r in rows)
        out_tok = sum(r["output_tokens_including_stop"] for r in rows)
        runtime = bdir / "runtime.jsonl"
        rt = load_jsonl(runtime)[0] if runtime.exists() else {}
        batch_info.append({
            "批次": bid,
            "GPU": E04_DEVICE.get(bid, "未知"),
            "設備來源": "runtime.jsonl" if rt.get("gpu") else "F05 README",
            "Slurm 作業": "、".join(sorted({str(r.get("slurm_job_id")) for r in rows})),
            "筆數": len(rows),
            "生成耗時合計(秒)": round(gen, 1),
            "平均每筆(秒)": round(gen / len(rows), 2),
            "平均輸出 token": round(out_tok / len(rows), 1),
            "輸出 token/秒": round(out_tok / gen, 1),
            "峰值顯存(GiB)": round(max(r["peak_allocated_gib"] for r in rows), 2),
            "模型載入(秒)": round(rt["model_load_seconds"], 1) if "model_load_seconds" in rt else "未記錄",
            "results.jsonl sha256": sha256_file(bdir / "results.jsonl"),
        })
        if rt.get("gpu") and E04_DEVICE.get(bid) not in rt["gpu"]:
            problems.append(f"E04 {bid}：runtime 記錄 {rt['gpu']}，與設定的 {E04_DEVICE.get(bid)} 不同")

    # ---------- F04 ----------
    f04 = {}
    for path in args.scores:
        for r in load_jsonl(path):
            if key(r) in f04:
                problems.append(f"F04 重複紀錄 {key(r)}（請用團隊歸檔的評分檔）")
            if r.get("status") not in ("ok", "no_answer"):
                problems.append(f"F04 {key(r)} 狀態 {r.get('status')}")
            f04[key(r)] = r

    # ---------- 一致性 ----------
    expected = {(q, i, s) for q in retrieval_q["K0"] for i, s in SETTINGS}
    for name, d in (("D08", d08), ("E04", e04), ("F04", f04)):
        if set(d) != expected:
            problems.append(f"{name}：{len(d)} 筆，缺 {len(expected - set(d))}、多 {len(set(d) - expected)}"
                            f"（應為 {len(expected)} 筆）")
    if set(retrieval_q["K0"]) != set(retrieval_q["K1"]):
        problems.append("B04 與 B06 的題目不同")
    for k in expected & set(d08) & set(e04) & set(f04):
        h = {d08[k]["history_sha256"], e04[k]["history_sha256"], f04[k]["history_sha256"]}
        if len(h) > 1:
            problems.append(f"{k}：D08／E04／F04 的 history_sha256 不一致")

    if problems:
        print("輸入檢查未通過：")
        for x in problems[:30]:
            print("  " + x)
        if len(problems) > 30:
            print(f"  … 另有 {len(problems) - 30} 項")
        sys.exit(1)

    n_q = len(retrieval_q["K0"])
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---------- 1. 一次性成本 ----------
    rate = ext["recorded_turn_seconds"] / ext["extracted_keys"]
    full_extract = rate * ext["unique_keys"]
    one_time = {}
    rows = []
    for i in INDICES:
        c = idx_cost[i]
        stages = []
        if i == "K1":
            stages.append(("C04 事實補抽（已記錄）", "本機 Ollama Llama 3.1 8B Q3_K_M",
                           c["recorded_fact_turn_seconds"],
                           f"{ext['extracted_keys']} 個鍵；輸入 {ext['recorded_input_tokens']:,}／"
                           f"輸出 {ext['recorded_output_tokens']:,} token（Llama 分詞）；"
                           f"另 {ext['reused_keys']:,} 個鍵沿用作者快取，成本未知"))
        stages.append(("Stella 模型載入", "A40", c["model_load_s"], "每次建庫一次"))
        stages.append(("Stella 歷史編碼", "A40", c["index_build_s"],
                       f"{c['indexed_turns']:,} 個輪次；{c['stella_tokens_after_truncation']:,} token"
                       f"（截斷後，Stella 分詞）"))
        for st, dev, sec, note in stages:
            rows.append({"索引": i, "階段": st, "設備": dev, "耗時(秒)": r3(sec),
                         "每份歷史平均(秒)": r3(sec / n_q), "說明": note})
        total = c["known_one_time_s"]
        rows.append({"索引": i, "階段": "已記錄一次性成本（合計）", "設備": "—", "耗時(秒)": r3(total),
                     "每份歷史平均(秒)": r3(total / n_q),
                     "說明": "K1 為下限（作者快取的抽取成本未計）" if i == "K1" else ""})
        one_time[i] = total
    one_time["K1 全量估計"] = idx_cost["K1"]["known_one_time_s"] - idx_cost["K1"]["recorded_fact_turn_seconds"] + full_extract
    rows.append({"索引": "K1", "階段": "全量抽取估計（敏感度）", "設備": "本機 Ollama（推估）",
                 "耗時(秒)": r3(one_time["K1 全量估計"]), "每份歷史平均(秒)": r3(one_time["K1 全量估計"] / n_q),
                 "說明": f"每鍵 {rate:.2f} 秒 × {ext['unique_keys']:,} 鍵 = {full_extract:,.0f} 秒抽取，再加 Stella 載入與編碼；"
                         f"推估值，非實測"})
    e04_load = next((b["模型載入(秒)"] for b in batch_info if b["模型載入(秒)"] != "未記錄"), None)
    rows.append({"索引": "共用", "階段": "回答模型載入（每次開跑）", "設備": "A40", "耗時(秒)": e04_load,
                 "每份歷史平均(秒)": "", "說明": "只有 E04 batch-01 有紀錄；屬每次開跑的固定開銷，不攤入每題"})
    write_csv(out / "f07_one_time.csv", rows)

    # ---------- 2. 每次提問成本 ----------
    per_q = {}
    rows = []
    for i, s in SETTINGS:
        ks = [(q, i, s) for q in sorted(retrieval_q[i])]
        ret = mean(retrieval_q[i][q] for q, _, _ in ks)
        sel = mean(d08[k]["selection_elapsed_s"] for k in ks)
        gen = mean(e04[k]["generation_seconds"] for k in ks)
        gen_a40 = mean(e04[k]["generation_seconds"] for k in ks if E04_DEVICE[e04_batch[k]] == "A40")
        total = ret + sel + gen
        per_q[(i, s)] = total
        rows.append({
            "索引": i, "策略": s, "題數": len(ks),
            "檢索(秒，A40)": round(ret, 4),
            "選材(秒，CPU)": round(sel, 4),
            "回答(秒，A40/L40S)": round(gen, 3),
            "回答(秒，只算 A40 批次)": round(gen_a40, 3),
            "每次提問合計(秒)": round(total, 3),
            "材料 token": round(mean(e04[k]["context_tokens"] for k in ks), 1),
            "回答輸入 token": round(mean(e04[k]["input_tokens"] for k in ks), 1),
            "回答輸出 token": round(mean(e04[k]["output_tokens_including_stop"] for k in ks), 1),
            "截斷筆數": sum(e04[k]["hit_output_limit"] for k in ks),
            "正確率(F04)": round(mean(f04[k]["label"] or 0 for k in ks), 4),
        })
    write_csv(out / "f07_per_query.csv", rows)
    per_query_rows = rows

    # ---------- 3. 複用成本 ----------
    rows = []
    for i, s in SETTINGS:
        b = one_time[i] / n_q
        row = {"索引": i, "策略": s, "每份歷史建庫(秒)": r3(b), "每次提問(秒)": r3(per_q[(i, s)])}
        for t in REUSE_T:
            row[f"T={t} 總耗時(秒)"] = round(b + t * per_q[(i, s)], 1)
        for t in REUSE_T:
            row[f"T={t} 建庫佔比"] = round(b / (b + t * per_q[(i, s)]), 3)
        rows.append(row)
    write_csv(out / "f07_reuse.csv", rows)

    # K1 − K0：每次提問的差拆成三段。回答耗時主要隨模型寫多長而變，與索引無直接關係、
    # 差值又小（< 1.5 秒），因此不用它推「回本次數」，改報「K1 多花的建庫 ≈ 幾次提問的耗時」。
    pq = {(r["索引"], r["策略"]): r for r in per_query_rows}
    rows = []
    for s in STRATEGIES:
        a, b = pq[("K0", s)], pq[("K1", s)]
        for label, b1 in (("已記錄（下限）", one_time["K1"]), ("全量抽取估計", one_time["K1 全量估計"])):
            db = (b1 - one_time["K0"]) / n_q
            dq = per_q[("K1", s)] - per_q[("K0", s)]
            rows.append({
                "策略": s, "K1 建庫口徑": label,
                "K1 每份歷史多花的建庫(秒)": r3(db),
                "≈ K0 幾次提問的耗時": round(db / per_q[("K0", s)], 1),
                "每次提問差：檢索(秒)": round(b["檢索(秒，A40)"] - a["檢索(秒，A40)"], 4),
                "每次提問差：選材(秒)": round(b["選材(秒，CPU)"] - a["選材(秒，CPU)"], 4),
                "每次提問差：回答(秒)": round(b["回答(秒，A40/L40S)"] - a["回答(秒，A40/L40S)"], 3),
                "T=1 時 K1 多花(秒)": round(db + dq, 1),
                "T=100 時 K1 多花(秒)": round(db + 100 * dq, 1),
                "正確率 K0": a["正確率(F04)"], "正確率 K1": b["正確率(F04)"],
                "正確率差(百分點)": round((b["正確率(F04)"] - a["正確率(F04)"]) * 100, 1),
            })
    write_csv(out / "f07_k1_vs_k0.csv", rows)

    # ---------- 4. E04 設備 ----------
    write_csv(out / "f07_e04_by_batch.csv", batch_info)

    # ---------- 5. 評分（實驗成本） ----------
    sc = list(f04.values())
    p_tok = sum(r.get("judge_prompt_tokens") or 0 for r in sc)
    o_tok = sum(r.get("judge_output_tokens") or 0 for r in sc)
    usd = p_tok / 1e6 * JUDGE_PRICE_PER_M["input"] + o_tok / 1e6 * JUDGE_PRICE_PER_M["output"]
    judge_rows = [{
        "項目": "F04 正式評分", "評分模型": "、".join(sorted({r.get("judge_model_returned") or "" for r in sc})),
        "筆數": len(sc), "送評筆數": sum(1 for r in sc if r.get("judge_prompt_tokens")),
        "輸入 token": p_tok, "輸出 token": o_tok,
        "API 耗時合計(秒)": round(sum(r.get("judge_elapsed_s") or 0 for r in sc), 1),
        "估算費用(美元)": round(usd, 3),
        "說明": f"依牌價 輸入 ${JUDGE_PRICE_PER_M['input']}/M、輸出 ${JUDGE_PRICE_PER_M['output']}/M 估算；"
                "不含 batch-05 意外重評的 95 筆（約 0.09 美元，見 EVAL_NOTES）",
    }]
    write_csv(out / "f07_judge.csv", judge_rows)

    # ---------- 畫面摘要 ----------
    print(f"輸入檢查通過：{n_q} 題 × 10 種設定 = {len(expected)} 筆（D08、E04、F04 逐筆對應，材料指紋一致）")
    print("\n[一次性成本]（80 份歷史合計；每份平均）")
    for i in INDICES:
        print(f"  {i:4s} {one_time[i]:9.1f} 秒　每份 {one_time[i] / n_q:6.2f} 秒")
    print(f"  K1 全量抽取估計 {one_time['K1 全量估計']:,.0f} 秒　每份 {one_time['K1 全量估計'] / n_q:,.1f} 秒"
          f"（推估：每鍵 {rate:.2f} 秒 × {ext['unique_keys']:,} 鍵）")
    if e04_load:
        print(f"  回答模型載入 {e04_load} 秒／每次開跑（A40，只有 batch-01 有紀錄）")
    print("\n[每次提問]（秒）      檢索      選材      回答      合計   正確率")
    for r in per_query_rows:
        print(f"  {r['索引']}-{r['策略']:4s}          {r['檢索(秒，A40)']:7.4f}  {r['選材(秒，CPU)']:7.4f}  "
              f"{r['回答(秒，A40/L40S)']:7.3f}  {r['每次提問合計(秒)']:7.3f}   {r['正確率(F04)']:.3f}")
    print("\n[E04 設備]")
    for b in batch_info:
        print(f"  {b['批次']} {b['GPU']:5s} 平均 {b['平均每筆(秒)']:5.2f} 秒／筆　{b['輸出 token/秒']:5.1f} token/秒")
    print(f"\n[評分（實驗成本）] {judge_rows[0]['筆數']} 筆；輸入 {p_tok:,}、輸出 {o_tok:,} token；估算 ${usd:.2f}")
    print(f"\n輸出：{out}/f07_one_time.csv、f07_per_query.csv、f07_reuse.csv、f07_k1_vs_k0.csv、"
          f"f07_e04_by_batch.csv、f07_judge.csv")


if __name__ == "__main__":
    main()
