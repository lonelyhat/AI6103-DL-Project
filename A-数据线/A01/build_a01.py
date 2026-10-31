"""A01：生成开发题清单、首批5题、ID 映射与评价文件，并自检。

用法：python3 build_a01.py <longmemeval_s_cleaned.json> [输出目录]
ID 规则（详见 A01-开发题与交接格式.md）：
  会话  {qid}-s{会话位置:03d}
  消息  {qid}-s{会话位置:03d}-m{消息位置:03d}
  轮    {qid}-s{会话位置:03d}-t{第k条用户消息:03d}   = 该用户消息 + 紧随的下一条消息
位置均从 0 开始；会话位置即 haystack_sessions 中的下标（官方已按时间排序）。
"""
import json, sys, hashlib
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
CONFIG_VERSION = "a01-v1"

def sid(q, s): return f"{q}-s{s:03d}"
def mid(q, s, m): return f"{q}-s{s:03d}-m{m:03d}"
def tid(q, s, k): return f"{q}-s{s:03d}-t{k:03d}"

def official_corpus_id(sess_id, pos, has_answer):
    """官方检索日志里的 corpus_id（run_retrieval.py:217,224）。仅用于映射，严禁给选择器。"""
    cid = f"{sess_id}_{pos + 1}"
    if "answer" in sess_id and not has_answer:
        cid = cid.replace("answer", "noans")
    return cid

def build_question(q):
    qid = q["question_id"]
    msg_rows, turn_rows = [], []
    ev_msgs, ev_turns, unreachable = [], set(), []
    for si, (sess_id, date, sess) in enumerate(zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"])):
        pos2turn, k = {}, 0
        for p, m in enumerate(sess):
            if m["role"] == "user":
                t = tid(qid, si, k); k += 1
                members = [p] + ([p + 1] if p + 1 < len(sess) else [])
                for x in members: pos2turn.setdefault(x, t)
                turn_rows.append({"turn_id": t, "session_index": si, "session_date": date,
                                  "message_ids": [mid(qid, si, x) for x in members],
                                  "official_session_id": sess_id,
                                  "official_corpus_id": official_corpus_id(sess_id, p, bool(m.get("has_answer")))})
        for p, m in enumerate(sess):
            row = {"message_id": mid(qid, si, p), "turn_id": pos2turn.get(p), "session_index": si,
                   "position": p, "role": m["role"], "official_session_id": sess_id}
            msg_rows.append(row)
            if m.get("has_answer"):
                ev_msgs.append(row["message_id"])
                if row["turn_id"] is None: unreachable.append(row["message_id"])
                else: ev_turns.add(row["turn_id"])
    ev = {"question_id": qid, "question_type": q["question_type"], "is_abstention": qid.endswith("_abs"),
          "answer": q["answer"], "answer_session_ids": q["answer_session_ids"],
          "evidence_session_indices": sorted({i for i, s in enumerate(q["haystack_session_ids"]) if s in q["answer_session_ids"]}),
          "evidence_message_ids": ev_msgs, "evidence_turn_ids": sorted(ev_turns),
          "unreachable_evidence_message_ids": unreachable,
          "n_sessions": len(q["haystack_sessions"]), "n_turns": len(turn_rows), "n_messages": len(msg_rows)}
    pub = {"question_id": qid, "stage": "dev", "question": q["question"], "question_date": q["question_date"]}
    return pub, ev, msg_rows, turn_rows

def public_turns(q):
    """给检索/选择/回答使用的原文：只有本组 ID、日期和消息内容，无官方 ID、无 has_answer。"""
    qid, out = q["question_id"], []
    for si, (date, sess) in enumerate(zip(q["haystack_dates"], q["haystack_sessions"])):
        k = 0
        for p, m in enumerate(sess):
            if m["role"] != "user": continue
            members = [p] + ([p + 1] if p + 1 < len(sess) else [])
            out.append({"turn_id": tid(qid, si, k), "session_index": si, "session_date": date,
                        "messages": [{"message_id": mid(qid, si, x), "role": sess[x]["role"], "content": sess[x]["content"]} for x in members]})
            k += 1
    return out

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
        "first_batch": [{"question_id": a, "slot": b, "reason": c, "question_type": data[a]["question_type"]} for a, b, c in FIRST5],
    }
    (out / "dev_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 自检 ----------
    problems = []
    for qid in DEV_IDS:
        q = data[qid]
        msgs = [json.loads(l) for l in (out / "map" / f"{qid}.messages.jsonl").open()]
        turns = [json.loads(l) for l in (out / "map" / f"{qid}.turns.jsonl").open()]
        if len({m["message_id"] for m in msgs}) != len(msgs): problems.append((qid, "message_id 重复"))
        if len({t["turn_id"] for t in turns}) != len(turns): problems.append((qid, "turn_id 重复"))
        if len(msgs) != sum(len(s) for s in q["haystack_sessions"]): problems.append((qid, "消息数不符"))
        # 官方 corpus_id 与 has_answer 一致：证据轮应保留 answer 前缀
        ev = next(e for e in evs if e["question_id"] == qid)
        for t in turns:
            if t["turn_id"] in ev["evidence_turn_ids"] and "answer" in t["official_session_id"]:
                first_msg_has = any(m.get("has_answer") for m in [q["haystack_sessions"][t["session_index"]][int(t["message_ids"][0][-3:])]])
                if first_msg_has and "noans" in t["official_corpus_id"]: problems.append((qid, "corpus_id 前缀错误", t["turn_id"]))
        # ID 排序 = 时间顺序
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
    print("PROBLEMS:", problems or "none")

if __name__ == "__main__":
    main()
