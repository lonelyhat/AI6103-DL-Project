"""A02 自检：用开发样例验证映射与指标。用法：python3 test_a02.py <longmemeval_s_cleaned.json>"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "A01"))
from evidence_metrics import Evidence, summarize
import build_a01

E = Evidence()
FIRST5 = ["2318644b", "1cea1afa", "gpt4_7a0daae1", "4c36ccef", "c960da58"]
def turns(qid): return [json.loads(l) for l in (E.root / "map" / f"{qid}.turns.jsonl").open()]
ok = 0
def check(cond, msg):
    global ok
    assert cond, msg; ok += 1; print("  ✓", msg)

print("1 全部保留")
for q in FIRST5:
    r = E.retention(q, E.eval[q]["evidence_turn_ids"])
    check(r["all_retained"] and r["msg_retention"] == 1.0, f"{q}: 只给证据轮 → 全部保留")

print("2 部分保留（两条证据只留一条）")
q = "2318644b"; ev = E.eval[q]["evidence_turn_ids"]
r = E.retention(q, [ev[0]] + [t["turn_id"] for t in turns(q)[:30] if t["turn_id"] not in ev])
check(r["msg_retention"] == 0.5 and not r["all_retained"] and r["any_retained"], f"{q}: 保留率 0.5、未全部保留、至少保留一条")
check(r["missing_message_ids"] == [E.eval[q]["evidence_message_ids"][1]], f"{q}: 正确列出丢失的证据消息")

print("3 完全未保留")
non = [t["turn_id"] for t in turns(q) if t["turn_id"] not in ev][:50]
r = E.retention(q, non)
check(r["msg_retention"] == 0 and not r["any_retained"], f"{q}: 50 条非证据轮 → 保留率 0")

print("4 助手证据（官方轮级标记会漏掉）")
q = "4c36ccef"; t = E.eval[q]["evidence_turn_ids"][0]
tr = next(x for x in turns(q) if x["turn_id"] == t)
check("noans" in tr["official_corpus_id"], f"{q}: 官方 ID 把证据轮标为 noans（{tr['official_corpus_id']}）")
check(E.retention(q, [t])["all_retained"], f"{q}: 本组口径仍算作证据被保留")

print("5 拒答题")
r = E.retention("19b5f2b3_abs", [])
check(r["has_evidence"] is False and r["msg_retention"] is None, "无证据拒答题：指标为 None，不报错")
r = E.retention("982b5123_abs", E.eval["982b5123_abs"]["evidence_turn_ids"])
check(r["has_evidence"] and r["is_abstention"], "部分拒答题也带 has_answer 标注（982b5123_abs）")
check(summarize([r, E.retention("19b5f2b3_abs", [])]) == {}, "拒答题一律不进入平均")

print("6 官方 corpus_id → 本组 turn_id")
for q in FIRST5:
    for x in turns(q):
        cid = x["official_corpus_id"]
        assert E.official_to_turn(q, cid) == x["turn_id"]
        assert E.official_to_turn(q, cid.replace("noans", "answer")) == x["turn_id"]
check(True, "首批 5 题所有轮：官方 ID（含 answer_/noans_ 两种写法）都能映射回唯一 turn_id")
try: E.official_to_turn("2318644b", "nonexistent_99"); check(False, "")
except KeyError: check(True, "未知官方 ID 直接报错，不静默跳过")
try: E.retention("2318644b", ["c960da58-s000-t000"]); check(False, "")
except ValueError: check(True, "混入别题的轮 ID 直接报错")

print("7 不可达证据（非开发题 58470ed2，临时生成）")
data = {d["question_id"]: d for d in json.load(open(sys.argv[1])) if d["question_id"] == "58470ed2"}
pub, ev, msgs, trs = build_a01.build_question(data["58470ed2"])
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    build_a01.dump_jsonl(root / "map" / "58470ed2.messages.jsonl", msgs)
    build_a01.dump_jsonl(root / "map" / "58470ed2.turns.jsonl", trs)
    build_a01.dump_jsonl(root / "eval" / "dev_eval.jsonl", [ev])
    E2 = Evidence(root)
    all_turns = [t["turn_id"] for t in trs]
    r = E2.retention("58470ed2", all_turns)
    check(r["n_unreachable"] == 1 and not r["all_retained"], f"即使给出全部 {len(all_turns)} 轮，不可达证据仍算丢失（保留率 {r['msg_retention']:.2f}）")
    check(E2.diagnose("58470ed2", all_turns, all_turns) == "candidates_missing", "归因为“候选没有找齐”")

print("8 错误环节归因")
q = "2318644b"; ev = E.eval[q]["evidence_turn_ids"]; others = [t["turn_id"] for t in turns(q) if t["turn_id"] not in ev]
tok = {t["turn_id"]: 100 for t in turns(q)}
check(E.diagnose(q, others, others) == "candidates_missing", "候选缺证据 → candidates_missing")
check(E.diagnose(q, ev + others, ev) == "all_retained", "证据全选中 → all_retained")
check(E.diagnose(q, ev + others, others[:5], tok, budget=2048) == "selection_missed", "放得下没选 → selection_missed")
check(E.diagnose(q, ev + others, others[:5], tok, budget=150) == "over_budget", "证据轮总长超预算 → over_budget")

print("9 与官方轮级证据口径对比（开发可回答题）")
diff = []
for q, e in E.eval.items():
    if e["is_abstention"]: continue
    official = {t["turn_id"] for t in turns(q) if "answer" in t["official_corpus_id"]}
    if official != set(e["evidence_turn_ids"]): diff.append((q, e["question_type"], len(official), len(e["evidence_turn_ids"])))
print("  官方口径与本组口径不同的题:", diff)

print(f"\n全部通过：{ok} 项检查")
