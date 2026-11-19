# G02 正式配置与执行清单

**2026-11-19，A03 v2 已定稿，B04 K0 和正式评分输入已核验，冻结待 C04/B06 更新到 v2。** [机器可读配置](plan.json)记录正式输入、参数、待交付项和指纹。[核验回执](validation.json)记录本地复核。题单和 B04 来自 `main@923af68`，开发参数与诊断来自 `D06@e870a08`、`D07@c2574c1`。G01 已验收。

## 拟冻结设置

| 项目 | 候选设置 |
| --- | --- |
| 正式题 | `a03-v2` 的 80 道可回答题、78 个证据组。各题各跑 K0/K1 × R/MMR/C/Q/FL，共 800 个设置结果。 |
| 候选 | B04 K0 已交付 v2 的每题 100 条。B06 K1 需按同版题单重新交付。K1 用事实与用户原文检索，两套索引均把完整原始轮次交给选材器。 |
| 选材与预算 | 历史正文上限 2048 Token。R 按排名逐条检查并跳过放不下的完整轮次。MMR 的 λ=0.5，C 的 λ=1，Q 的 λ=0.5、γ=1，FL 用 D06 原配置。两种索引共用同一组方法参数。 |
| 阅读 | Llama 3.1 8B Instruct，revision `0e9e39f249a16976918f6564b8830bc894c89659`，采用 E02 的 CoN 提示和 E03 批量入口。BF16、greedy，输出上限 800 Token。历史正文与完整 prompt 分别核对。 |
| 评分 | `f03-v1`，Judge `gpt-4o-2024-08-06`。截断按产出的原文计分。技术失败先用同配置恢复，定案失败和空答计 0 并留在分母。缺评和 Judge API 错误须补齐后再发布。按 A03 旧用题排除规则，正式结论覆盖五种题型，偏好题不在本轮范围。 |
| 分析 | 主要比较为 Q−C、各策略的 K1−K0，以及 `(Q1−C1)−(Q0−C0)`。按题配对，95% 区间按 A03 证据组估计。D07 的 1024/4096 和覆盖消融用于开发集证据诊断。 |

## 冻结前确认

**A03 已定稿。** v2 排除了旧 baseline 的 200 个测试题及共享证据组。原 80 题保留 43 道、替换 37 道，其中 32 道直接出现在旧实验中，5 道与旧实验题共享证据。B04 重新生成了 8,000 条 K0 候选，已复核题号顺序、原文映射和文件指纹。

1. **C04 交付 v2 事实及来源清单。** 新题单需要 18,841 个事实键。核对用户原文后，10,629 个键可在旧 C04 定位，额外 248 个键在 C03 有同文记录，需由 C 线核对复用口径。另有 7,964 个键尚未被这两份本地缓存覆盖，先查作者缓存再决定补抽量。G01 已记录的 6 个失败键与 v2 所需键无交集。
2. **B06 交付 v2 的完整 K1 候选。** 当前 K1 归档仍是 v1，只有 43 个题号和 v2 重叠。B06 接收新版 C04 后，对齐全部 80 题的候选顺序、事实哈希和 B04 共用的检索配置。

两项到齐后，在同一提交上复跑 `G/G01/audit_formal.py` 核对 A03/C04/B04/B06，更新计划的 K1 文件及指纹，运行每题十种设置的 CPU 接口检查，再将状态设为 `frozen`。冻结后首批的 GPU 生成、续跑和 Judge 回执用于确认可以扩大批次。

[G01 验收记录](../G01/ACCEPTANCE.md)保留 C02 的 6 条失败、成本口径、未知项和换题后的核对条件，供后续问题检查及报告引用。

## 本地复核与正式运行入口

从工作树根目录运行。分词器目录需包含匹配 E03 的 tokenizer、聊天模板和模型配置，脚本会核对归档指纹。示例选一题保留题和一题 v2 新题，当前只检查 K0 的五种策略。

```bash
python -m G.G02.prepare \
  --tokenizer /path/to/reader-snapshot \
  --question-ids 10d9b85a ed4ddc30 --preview-index K0 \
  --output-dir runs/g02/a03-v2-k0-preflight
```

输出 `selections.jsonl`、`reader_inputs.jsonl` 和 `receipt.json`。对每份材料重放选择，重建选中原文，核对正文 Token、CoN prompt 容量和记录标识。K1 交付后移除 `--preview-index K0` 即检查全部十种设置。另可用 `--preview-budget 1024` 做接口诊断。

单独构建供 A04/F04 使用的正式评估文件。原始数据采用 [LongMemEval 官方清理版](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/main)。程序在读取前核对 A03 的 SHA-256，并逐题核对公开问题和轮次映射。

```bash
python -m G.G02.prepare_eval \
  --dataset /path/to/longmemeval_s_cleaned.json \
  --output runs/g02/a03-v2-formal-eval.jsonl
```

正式执行时，D08 按清单分批出阅读材料，E04 在学校 Slurm GPU 上使用 E03 入口，每个正式批次保留自己的输出目录和回执。技术失败用同一输入、配置及目录恢复。F04 从同批最终输出拿到答案后使用以下入口。批次示例为两题 × 十种设置。

```bash
python E/E03/run_generation.py --stage formal \
  --input runs/g02/batch-01/reader_inputs.jsonl --output runs/g02/batch-01/reader
python E/E03/export_for_f.py --run-dir runs/g02/batch-01/reader \
  --output runs/g02/batch-01/answers_for_f.jsonl
python F/src/evaluation/judge.py --expect-n 20 \
  --answers runs/g02/batch-01/answers_for_f.jsonl \
  --eval runs/g02/a03-v2-formal-eval.jsonl \
  --questions 'A-数据线/A03/output/public/formal_questions.jsonl' \
  --out runs/g02/batch-01/scores.jsonl
```

首批先核对题号、索引、方法、预算、选材配置、阅读配置和内容指纹。A04 使用 A02 的消息级指标。F05 对至少 20% 的去重正式回答做独立双判，F06 按正式题清单和证据组汇总。开发网格与接口样例的记录保存在各自目录。

### 离线复算 D06/D07

按 [D06 交付说明](../../D/D06/delivery/README.md)解包归档并复算参数，选择一个新的汇总目录。随后运行：

```bash
python -m G.G02.verify_development \
  --returned D/D06/returned/dev34-grid-v1 \
  --d06-recomputed D/D06/output/dev34-parameter-selection-recheck
```

检查覆盖 D06 归档校验和、全部评分汇总和参数、D07 三张表以及 2048 下可从 D06 重新核对的证据指标。
