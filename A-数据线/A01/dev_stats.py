"""统计开发题：题型、会话数、证据会话数、证据消息数（只用于评价，不进模型输入）"""
import json, sys
from collections import Counter
DEV = """982b5123_abs 1cea1afa 2318644b 4c36ccef 38146c39 dccbc061 gpt4_7a0daae1 19b5f2b3_abs 6a1eabeb 8e91e7d9
71a3fd6b afdc33df c960da58 b46e15ee 0862e8bf_abs b6019101 60036106 c4f10528 07b6f563 af8d2e46
gpt4_93159ced_abs 01493427 a3332713 c7cf7dfd d24813b1 4fd1909e 9a707b82 e5ba910e_abs 6071bd76 7024f17c
4388e9dd 505af2f5 gpt4_e072b769 88432d0a_abs 4b24c848 4adc0475 fea54f57 54026fce faba32e5 gpt4_4cd9eba1""".split()
data = {q['question_id']: q for q in json.load(open(sys.argv[1]))}
print('total questions', len(data), 'dev', len(DEV), 'missing', [d for d in DEV if d not in data])
rows=[]
for qid in DEV:
    q=data[qid]
    ev_msgs=[(si,mi,m['role']) for si,s in enumerate(q['haystack_sessions']) for mi,m in enumerate(s) if m.get('has_answer')]
    n_turn_msgs=sum(len(s) for s in q['haystack_sessions'])
    rows.append(dict(qid=qid,type=q['question_type'],abs=qid.endswith('_abs'),n_sess=len(q['haystack_sessions']),
        n_ans_sess=len(q['answer_session_ids']),n_ev_msgs=len(ev_msgs),ev_roles=''.join(sorted({r[0] for *_,r in ev_msgs})),
        n_msgs=n_turn_msgs,q=q['question'][:70],a=str(q['answer'])[:40]))
print(Counter(r['type'] for r in rows if not r['abs']))
for r in rows:
    print(f"{r['qid']:20} {r['type']:26} abs={int(r['abs'])} sess={r['n_sess']:3} ansSess={r['n_ans_sess']} evMsg={r['n_ev_msgs']:2}({r['ev_roles']:2}) | {r['q']} -> {r['a']}")
# 全量题型分布供参考
print('FULL', Counter(q['question_type'] for q in data.values() if not q['question_id'].endswith('_abs')))
# 检查 has_answer 覆盖：证据会话里是否都有 has_answer 消息
bad=[q['question_id'] for q in data.values() if not q['question_id'].endswith('_abs') and not any(m.get('has_answer') for s in q['haystack_sessions'] for m in s)]
print('answerable without any has_answer:', len(bad), bad[:10])
