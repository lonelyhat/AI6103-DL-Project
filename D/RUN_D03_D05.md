# D03 / D04 / D05 本机运行

本批次复用 D01 算法核心，接入真实 B 候选并沿用 D02 的完整材料预算与输出。
默认只处理 B02 首批五题、K0、dev、2048 历史 Token。不会读取 eval/map，不调用 LLM。

## 环境与全部方法

在 WSL 的仓库根目录执行：

```bash
cd /home/cyr2526/DL_project/AI6103-DL-Project
export PATH="/home/cyr2526/DL_project/.conda/longmemeval/bin:$PATH"
TOKENIZER="/home/cyr2526/DL_project/model_cache/Llama-3.1-8B-Instruct-tokenizer"

python -m unittest D.D01.test_selection D.D02.test_materials D.test_selection_batch -v

OUTPUT="D/results/d03-d05-$(date +%Y%m%d-%H%M%S)"
time python -m D.selection_batch \
  --candidates "B-检索线/B02/candidates/dev_K0.jsonl" \
  --tokenizer "$TOKENIZER" \
  --tokenizer-label "meta-llama/Llama-3.1-8B-Instruct" \
  --strategies MMR C Q FL \
  --redundancy-weight 0.5 \
  --coverage-weight 0.5 \
  --output-dir "$OUTPUT"

python -m D.verify_selection --output-dir "$OUTPUT" --tokenizer "$TOKENIZER"
```

分词器沿用 E01 revision `0e9e39f249a16976918f6564b8830bc894c89659`。
本地文件须与 E01 对齐；tokenizer-label 是身份标签，不能将其他模型文件改名冒充。
来源路径与实际分词器指纹一起记录，验证时检查内容指纹。无需模型权重或 GPU。

## 单独运行与关闭覆盖奖励

沿用以上入口，只替换 strategies 和 output-dir：

| 任务 | strategies |
| --- | --- |
| D03 | MMR |
| D04 | C Q |
| D05 | FL |

每次使用新的输出目录，不覆盖历史结果。gamma=0 消融：

```bash
ABLATION="D/results/d04-gamma0-$(date +%Y%m%d-%H%M%S)"
python -m D.selection_batch \
  --tokenizer "$TOKENIZER" \
  --tokenizer-label "meta-llama/Llama-3.1-8B-Instruct" \
  --strategies C Q --coverage-weight 0 \
  --output-dir "$ABLATION"

python - "$ABLATION" <<'PY'
import json
import sys
from pathlib import Path
rows = [json.loads(s) for s in (Path(sys.argv[1])/"selections.jsonl").read_text().splitlines()]
by_key = {(r["question_id"], r["strategy"]): r for r in rows}
for qid in sorted({r["question_id"] for r in rows}):
    c, q = by_key[qid, "C"], by_key[qid, "Q"]
    for field in ("selection_order", "steps", "selected_message_ids", "history_text", "context_tokens"):
        if c[field] != q[field]:
            raise RuntimeError(f"{qid}: gamma=0 mismatch in {field}")
    print(qid, "C == Q: PASS")
PY
```

## 输出和验证范围

四种办法共 20 条 selections.jsonl 记录；materials/ 内每个 strategy-question_id 一份可读 txt。
batch_manifest.json 保存候选、公开问题、原文、配置、源码和分词器的指纹及选择耗时。
verification.json 保存自动重放验证结论；命令成功应打印 Replay PASS。
若产生空材料，保存输出供排查但命令以失败状态退出，不能作为已完成的读者交付。

验证器不调用 select()，重新评估每一步所有可行候选的分数及最佳选择，
复核原始分数、相关性、冗余、线索、真实新增 Token、FL 直接目标差值、
停止/跳过原因、原始消息、时间顺序、消息去重、实际文本、哈希和最终预算。
共享 A01 数据验证、序列化和词面特征规则，属于独立决策重放而非独立团队验收。
移动仓库或分词器后可用 --tokenizer 指定相同内容的新分词器路径；
来源文件必须与原批次一致，源码变化后旧批次重放会明确报错。

lambda/gamma 默认值仅用于实现验证，不是 D06 选出的最优参数。
K1 可用 --index K1 配合对应候选；改变题目范围需显式指定 --question-ids。
输入候选文件必须恰好覆盖所请求题目；不会静默丢弃额外题目或重复记录。
当前入口仅处理 dev，候选声明的预算必须与实验一致，不静默覆盖不一致条件。
D03/D04/D05 公式与适配分别见各任务目录 README.md。
回答正确率、证据保留、两种索引上的公平调参属于 E/F/D06，未在本批次执行。

## Git

代码与结果当前只写入本地，不自动 commit、push 或合并 main。
后续如需提交，建议在独立功能分支操作并明确指定推送目标。
