"""A02：官方证据 ↔ 本组 ID 的映射与证据保留指标。

依赖 A01 输出（../A01/output）：
  eval/dev_eval.jsonl        每题证据消息 / 证据轮 / 不可达证据
  map/{qid}.turns.jsonl      turn_id ↔ official_corpus_id
  map/{qid}.messages.jsonl   message_id → turn_ids（连续用户消息时一条消息可属于两个轮）

指标口径（以消息级 has_answer 为准，见 A01 文档第 5 节第 2 条）：
  被保留的消息 = 给定各轮所含消息 ID 的并集（去重）
  一条证据消息“被保留” ⇔ 它在这个并集里（属于两个轮的消息，任一轮被选中即算保留）
  msg_retention   = 被保留的证据消息数 / 全部证据消息数（不可达证据计入分母）
  all_retained    = 全部证据消息都被保留
  any_retained    = 至少保留一条
无证据题返回 None 指标（has_evidence=False）；拒答题（is_abstention）即使带 has_answer 也不参与平均。

用法：
  python3 evidence_metrics.py --input selections.jsonl [--field selected_turn_ids] [--output metrics.jsonl]
  输入每行需有 question_id 和一个轮 ID 列表字段；候选文件可用 --field candidates（取每项 turn_id）。
"""
import argparse, json
from pathlib import Path

A01_OUT = Path(__file__).resolve().parent.parent / "A01" / "output"


class Evidence:
    def __init__(self, a01_out=A01_OUT):
        self.root = Path(a01_out)
        self.eval = {}
        for line in (self.root / "eval" / "dev_eval.jsonl").open(encoding="utf-8"):
            r = json.loads(line); self.eval[r["question_id"]] = r
        self._turn2msgs, self._official2turn = {}, {}

    def add_eval_rows(self, rows):
        """正式题等其他题目的评价行（格式同 dev_eval.jsonl）可在此加入。"""
        for r in rows: self.eval[r["question_id"]] = r

    # ---------- 映射 ----------
    def turn2msgs(self, qid):
        if qid not in self._turn2msgs:
            m = {}
            for l in (self.root / "map" / f"{qid}.turns.jsonl").open(encoding="utf-8"):
                t = json.loads(l); m[t["turn_id"]] = t["message_ids"]
            self._turn2msgs[qid] = m
        return self._turn2msgs[qid]

    def official_to_turn(self, qid, corpus_id):
        """官方检索日志 corpus_id → 本组 turn_id。answer_/noans_ 统一后再查，两种写法都能对上。"""
        if qid not in self._official2turn:
            m = {}
            for l in (self.root / "map" / f"{qid}.turns.jsonl").open(encoding="utf-8"):
                t = json.loads(l); m[_norm(t["official_corpus_id"])] = t["turn_id"]
            self._official2turn[qid] = m
        tid = self._official2turn[qid].get(_norm(corpus_id))
        if tid is None:
            raise KeyError(f"{qid}: 官方 corpus_id {corpus_id!r} 在映射中不存在")  # 不静默跳过（B01 第 7 节第 8 条）
        return tid

    # ---------- 指标 ----------
    def retention(self, qid, turn_ids):
        ev = self.eval[qid]
        turn_ids = list(turn_ids)
        bad = [t for t in turn_ids if not t.startswith(qid + "-")]
        if bad:
            raise ValueError(f"{qid}: 轮 ID 不属于本题: {bad[:3]}")
        kept = set(turn_ids)
        t2m = self.turn2msgs(qid)
        unknown = [t for t in kept if t not in t2m]
        if unknown:
            raise KeyError(f"{qid}: 未知轮 ID: {unknown[:3]}")
        kept_msgs = set().union(*(t2m[t] for t in kept)) if kept else set()
        ev_msgs = ev["evidence_message_ids"]
        res = {"question_id": qid, "question_type": ev["question_type"], "n_turns_given": len(kept), "n_messages_given": len(kept_msgs),
               "is_abstention": ev["is_abstention"], "has_evidence": bool(ev_msgs), "n_evidence_msgs": len(ev_msgs),
               "n_unreachable": len(ev["unreachable_evidence_message_ids"])}
        if not ev_msgs:
            return res | {"n_retained_msgs": None, "msg_retention": None, "all_retained": None,
                          "any_retained": None, "n_evidence_turns": 0, "n_retained_turns": None,
                          "missing_message_ids": []}
        retained = [m for m in ev_msgs if m in kept_msgs]
        ev_turns = ev["evidence_turn_ids"]
        return res | {
            "n_retained_msgs": len(retained),
            "msg_retention": len(retained) / len(ev_msgs),
            "all_retained": len(retained) == len(ev_msgs),
            "any_retained": len(retained) > 0,
            "n_evidence_turns": len(ev_turns),
            "n_retained_turns": sum(t in kept for t in ev_turns),
            "missing_message_ids": [m for m in ev_msgs if m not in retained],
        }

    def min_evidence_tokens(self, qid, candidate_turn_ids, turn_tokens):
        """在候选内覆盖全部证据消息所需的最少 token（重叠轮时可能少于证据轮总和）。"""
        t2m = self.turn2msgs(qid)
        need = set(self.eval[qid]["evidence_message_ids"])
        opts = [(t, set(t2m[t]), turn_tokens[t]) for t in set(candidate_turn_ids)]
        cost = _min_cover(need, opts)
        return float("inf") if cost is None else cost

    def diagnose(self, qid, candidate_turn_ids, selected_turn_ids, turn_tokens=None, budget=None):
        """错误环节归因（供 A04）：
        candidates_missing  候选没有找齐（含不可达证据）
        over_budget         证据都在候选里，但覆盖全部证据消息所需的最少轮长度之和仍超过预算（需传 turn_tokens 与 budget）
        selection_missed    证据放得下却没有选齐
        all_retained        证据全部留下（若仍答错，问题在阅读/提取/评分）
        """
        ev = self.eval[qid]
        if not ev["evidence_message_ids"]:
            return "no_evidence"
        if not self.retention(qid, candidate_turn_ids)["all_retained"]:
            return "candidates_missing"
        if self.retention(qid, selected_turn_ids)["all_retained"]:
            return "all_retained"
        if turn_tokens is not None and budget is not None:
            if self.min_evidence_tokens(qid, candidate_turn_ids, turn_tokens) > budget:
                return "over_budget"
        return "selection_missed"


def _min_cover(need, options):
    """need: 证据消息集合；options: [(turn_id, msgs, tokens)]。消息很少（≤几条），直接枚举子集求最小长度覆盖。"""
    from itertools import combinations
    opts = [o for o in options if o[1] & need]
    best = None
    for r in range(1, len(need) + 1):
        for combo in combinations(opts, r):
            if need <= set().union(*(c[1] for c in combo)):
                cost = sum(c[2] for c in combo)
                best = cost if best is None else min(best, cost)
    return best


def _norm(cid):
    return cid.replace("noans", "answer")


def summarize(rows):
    rows = [r for r in rows if r["has_evidence"] and not r["is_abstention"]]  # 拒答题不参与平均
    if not rows: return {}
    n = len(rows)
    return {"n_records": n,  # 按 (index, strategy, budget) 分组后再调用，n 即题数
            "mean_msg_retention": sum(r["msg_retention"] for r in rows) / n,
            "all_retained_rate": sum(r["all_retained"] for r in rows) / n,
            "any_retained_rate": sum(r["any_retained"] for r in rows) / n}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--field", default="selected_turn_ids")
    ap.add_argument("--output")
    ap.add_argument("--a01-out", default=str(A01_OUT))
    a = ap.parse_args()
    E = Evidence(a.a01_out)
    keep = ("question_id", "stage", "index", "strategy", "budget_tokens", "tokenizer", "config_version")
    out = []
    for line in open(a.input, encoding="utf-8"):
        r = json.loads(line)
        ids = r[a.field]
        if ids and isinstance(ids[0], dict): ids = [x["turn_id"] for x in ids]
        out.append({k: r.get(k) for k in keep} | E.retention(r["question_id"], ids))
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            for r in out: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(summarize(out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
