"""A01：生成开发题清单、首批5题、ID 映射与评价文件，并自检。

用法：python3 build_a01.py <longmemeval_s_cleaned.json> [输出目录]
ID 规则（详见 A01-开发题与交接格式.md）：
  会话  {qid}-s{会话位置:03d}
  消息  {qid}-s{会话位置:03d}-m{消息位置:03d}
  轮    {qid}-s{会话位置:03d}-t{第k条用户消息:03d}   = 该用户消息 + 紧随的下一条消息
位置均从 0 开始；会话位置即 haystack_sessions 中的下标。
注意：haystack_sessions 并不总按时间排序（开发题 13/40、全量 211/500 有日期倒序），
ID 顺序 ≠ 时间顺序。按时间排列材料时用 sort_key = [ISO 日期时间, 会话位置, 用户消息位置]。
连续用户消息时一条消息可属于两个轮，消息映射保存全部所属轮（turn_ids）。
"""
import json, sys, hashlib, re
from datetime import datetime
from collections import Counter
from pathlib import Path

DEV_IDS = """982b5123_abs 1cea1afa 2318644b 4c36ccef 38146c39 dccbc061 gpt4_7a0daae1 19b5f2b3_abs 6a1eabeb 8e91e7d9
71a3fd6b afdc33df c960da58 b46e15ee 0862e8bf_abs b6019101 60036106 c4f10528 07b6f563 af8d2e46
gpt4_93159ced_abs 01493427 a3332713 c7cf7dfd d24813b1 4fd1909e 9a707b82 e5ba910e_abs 6071bd76 7024f17c
4388e9dd 505af2f5 gpt4_e072b769 88432d0a_abs 4b24c848 4adc0475 fea54f57 54026fce faba32e5 gpt4_4cd9eba1""".split()
FIRST5 = [
    ("2318644b", "多证据拼接", "两段会话分别给出两地住宿价格，需同时选中才能算差价；对应 Q 方法要解决的“漏掉另一半证据”"),
    ("1cea1afa", "知识更新", "新旧粉丝数各一条证据，需找到并以新值作答；E01 已在 TC2 上用此题跑通生成，可复用"),
    ("gpt4_7a0daae1", "时间推理", "两条证据加日期计算，可检查材料按时间排序与日期展示"),
    ("4c36ccef", "助手证据", "证据在助手回复中，K0 只索引用户发言，用于检验检索盲区及“候选未找齐”的统计"),
    ("c960da58", "简单对照", "单条用户证据、答案明确；若此题出错，优先怀疑流程本身"),
]
CONFIG_VERSION = "a01-v2"

def sid(q, s): return f"{q}-s{s:03d}"
def mid(q, s, m): return f"{q}-s{s:03d}-m{m:03d}"
def tid(q, s, k): return f"{q}-s{s:03d}-t{k:03d}"

def official_corpus_id(sess_id, pos, has_answer):
    """官方检索日志里的 corpus_id（run_retrieval.py:217,224）。仅用于映射，严禁给选择器。"""
    cid = f"{sess_id}_{pos + 1}"
    if "answer" in sess_id and not has_answer:
        cid = cid.replace("answer", "noans")
    return cid

def parse_date(s):
    """'2023/05/20 (Sat) 16:16' → '2023-05-20T16:16'（ISO，字符串可直接比较）"""
    d = datetime.strptime(re.sub(r" \(\w+\)", "", s), "%Y/%m/%d %H:%M")
    return d.strftime("%Y-%m-%dT%H:%M")

def session_turns(qid, si, sess):
    """一个会话内的轮：第 k 条用户消息 + 紧随的下一条消息（与官方一致）。
    连续用户消息时，后一条同时属于两个轮（重叠轮）。"""
    out, k = [], 0
    for p, m in enumerate(sess):
        if m["role"] == "user":
            members = [p] + ([p + 1] if p + 1 < len(sess) else [])
            out.append((tid(qid, si, k), p, members)); k += 1
    return out

def build_question(q):
    qid = q["question_id"]
    msg_rows, turn_rows = [], []
    ev_msgs, ev_turns, unreachable = [], set(), []
    for si, (sess_id, date, sess) in enumerate(zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"])):
        iso = parse_date(date)
        pos2turns = {}
        for t, p, members in session_turns(qid, si, sess):
            for x in members: pos2turns.setdefault(x, []).append(t)
            turn_rows.append({"turn_id": t, "session_index": si, "session_date": date, "session_datetime": iso,
                              "sort_key": [iso, si, p],
                              "message_ids": [mid(qid, si, x) for x in members],
                              "official_session_id": sess_id,
                              "official_corpus_id": official_corpus_id(sess_id, p, bool(m_has(sess, p)))})
        for p, m in enumerate(sess):
            row = {"message_id": mid(qid, si, p), "turn_ids": pos2turns.get(p, []), "session_index": si,
                   "position": p, "role": m["role"], "official_session_id": sess_id}
            msg_rows.append(row)
            if m.get("has_answer"):
                ev_msgs.append(row["message_id"])
                if not row["turn_ids"]: unreachable.append(row["message_id"])
                ev_turns.update(row["turn_ids"])
    ev = {"question_id": qid, "question_type": q["question_type"], "is_abstention": qid.endswith("_abs"),
          "answer": q["answer"], "answer_session_ids": q["answer_session_ids"],
          "evidence_session_indices": sorted({i for i, s in enumerate(q["haystack_session_ids"]) if s in q["answer_session_ids"]}),
          "evidence_message_ids": ev_msgs, "evidence_turn_ids": sorted(ev_turns),
          "unreachable_evidence_message_ids": unreachable,
          "n_sessions": len(q["haystack_sessions"]), "n_turns": len(turn_rows), "n_messages": len(msg_rows)}
    pub = {"question_id": qid, "stage": "dev", "question": q["question"], "question_date": q["question_date"]}
    return pub, ev, msg_rows, turn_rows

def m_has(sess, p): return sess[p].get("has_answer")

def public_turns(q):
    """给检索/选择/回答使用的原文：只有本组 ID、日期、排序键和消息内容，无官方 ID、无 has_answer。"""
    qid, out = q["question_id"], []
    for si, (date, sess) in enumerate(zip(q["haystack_dates"], q["haystack_sessions"])):
        iso = parse_date(date)
        for t, p, members in session_turns(qid, si, sess):
            out.append({"turn_id": t, "session_index": si, "session_date": date, "session_datetime": iso,
                        "sort_key": [iso, si, p],
                        "messages": [{"message_id": mid(qid, si, x), "role": sess[x]["role"], "content": sess[x]["content"]} for x in members]})
    return out

def _has_inversion(q):
    ds = [parse_date(x) for x in q["haystack_dates"]]
    return any(a > b for a, b in zip(ds, ds[1:]))

def dump_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")

def main():
    src = Path(sys.argv[1]); out = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / "output")
    raw = src.read_bytes(); data_sha = hashlib.sha256(raw).hexdigest()
    data = {q["question_id"]: q for q in json.loads(raw)}
    assert all(d in data for d in DEV_IDS) and len(set(DEV_IDS)) == 40
    answerable = [d for d in DEV_IDS if not d.endswith("_abs")]
    first5 = [x[0] for x in FIRST5]
    assert all(f in answerable for f in first5)

    pubs, evs = [], []
    for qid in DEV_IDS:
        pub, ev, msgs, turns = build_question(data[qid])
        pubs.append(pub); evs.append(ev)
        dump_jsonl(out / "map" / f"{qid}.messages.jsonl", msgs)
        dump_jsonl(out / "map" / f"{qid}.turns.jsonl", turns)
    for qid in first5:
        dump_jsonl(out / "public" / "turns" / f"{qid}.jsonl", public_turns(data[qid]))
    dump_jsonl(out / "public" / "dev_questions.jsonl", pubs)
    dump_jsonl(out / "eval" / "dev_eval.jsonl", evs)

    manifest = {
        "config_version": CONFIG_VERSION,
        "data_file": src.name, "data_sha256": data_sha,
        "dev_source": "e01 分支 e01/input_manifest.json 的 archived_dev_ids（源自 baseline_v1 存档 results/split.json）",
        "dev_ids": DEV_IDS, "dev_answerable_ids": answerable,
        "dev_abstention_ids": [d for d in DEV_IDS if d.endswith("_abs")],
        "dev_type_counts": dict(Counter(data[d]["question_type"] for d in answerable)),
        "dev_date_inversion_ids": [d for d in DEV_IDS if _has_inversion(data[d])],
        "first_batch": [{"question_id": a, "slot": b, "reason": c, "question_type": data[a]["question_type"]} for a, b, c in FIRST5],
    }
    (out / "dev_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 自检 ----------
    problems, n_overlap = [], 0
    for qid in DEV_IDS:
        q = data[qid]
        msgs = [json.loads(l) for l in (out / "map" / f"{qid}.messages.jsonl").open()]
        turns = [json.loads(l) for l in (out / "map" / f"{qid}.turns.jsonl").open()]
        if len({m["message_id"] for m in msgs}) != len(msgs): problems.append((qid, "message_id 重复"))
        if len({t["turn_id"] for t in turns}) != len(turns): problems.append((qid, "turn_id 重复"))
        if len(msgs) != sum(len(s) for s in q["haystack_sessions"]): problems.append((qid, "消息数不符"))
        # 消息→轮 与 轮→消息 双向一致
        t2m = {t["turn_id"]: set(t["message_ids"]) for t in turns}
        for m in msgs:
            if any(m["message_id"] not in t2m[t] for t in m["turn_ids"]): problems.append((qid, "映射不一致", m["message_id"]))
            n_overlap += len(m["turn_ids"]) > 1
        if sum(len(v) for v in t2m.values()) != sum(len(m["turn_ids"]) for m in msgs): problems.append((qid, "映射计数不一致"))
        # 证据轮 = 含任一证据消息的全部轮
        ev = next(e for e in evs if e["question_id"] == qid)
        exp = sorted({t for t, ms in t2m.items() if ms & set(ev["evidence_message_ids"])})
        if exp != ev["evidence_turn_ids"]: problems.append((qid, "证据轮不完整"))
        # sort_key 排序后时间单调不减
        st = sorted(turns, key=lambda t: t["sort_key"])
        if any(a["session_datetime"] > b["session_datetime"] for a, b in zip(st, st[1:])): problems.append((qid, "sort_key 排序后时间非单调"))
        ids = [t["turn_id"] for t in turns]
        if ids != sorted(ids): problems.append((qid, "turn_id 字符串排序不等于位置顺序"))
    # 公开文件不得含泄漏字段
    leak_words = ["answer_", "noans", "has_answer", "sharegpt", "ultrachat"]
    for p in (out / "public").rglob("*.jsonl"):
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            keys_and_ids = json.dumps({k: v for k, v in r.items() if k not in ("messages", "question")}) + \
                json.dumps([{k: v for k, v in m.items() if k != "content"} for m in r.get("messages", [])])
            if any(w in keys_and_ids for w in leak_words): problems.append((p.name, "公开文件含泄漏字段")); break
    print("dev", len(DEV_IDS), "answerable", len(answerable), "types", manifest["dev_type_counts"])
    for e in evs:
        if e["question_id"] in first5:
            print(f"  {e['question_id']:15} {e['question_type']:25} evidence msgs={len(e['evidence_message_ids'])} turns={e['evidence_turn_ids']} unreachable={e['unreachable_evidence_message_ids']}")
    print("unreachable evidence among dev:", [(e["question_id"], e["unreachable_evidence_message_ids"]) for e in evs if e["unreachable_evidence_message_ids"]])
    print("date inversion dev:", len(manifest["dev_date_inversion_ids"]), manifest["dev_date_inversion_ids"])
    print("first5 affected by inversion:", [x for x in first5 if x in manifest["dev_date_inversion_ids"]])
    print("dev messages belonging to 2 turns:", n_overlap)
    print("PROBLEMS:", problems or "none")

if __name__ == "__main__":
    main()
