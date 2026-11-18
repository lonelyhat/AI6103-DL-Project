# G02 正式配置与执行清单

**2026-11-19，配置与接口核验完成，G01 已验收，正式冻结仅待 A03 定稿。** [机器可读配置](plan.json)固定了拟采用的输入、参数、运行入口和哈希。[核验回执](validation.json)记录离线检查结果。工作树以 `main@c97d0b8`、`g01-audit@37ea928`、`d06-dev34-results@e870a08` 和包含 D06 的 `d07-budget-diagnostics@c2574c1` 为基础。

## 拟冻结设置

| 项目 | 候选设置 |
| --- | --- |
| 正式题 | 暂用 `a03-v1` 的 80 道可回答题、79 个证据组。各题各跑 K0/K1 × R/MMR/C/Q/FL，共 800 个设置结果。 |
| 候选 | B04 K0、B06 K1，每题各 100 条。K1 用事实与用户原文检索，两套索引均把完整原始轮次交给选材器。 |
| 选材与预算 | 历史正文上限 2048 Token。R 按排名逐条检查并跳过放不下的完整轮次。MMR 的 λ=0.5，C 的 λ=1，Q 的 λ=0.5、γ=1，FL 用 D06 原配置。两种索引共用同一组方法参数。 |
| 阅读 | Llama 3.1 8B Instruct，revision `0e9e39f249a16976918f6564b8830bc894c89659`，采用 E02 的 CoN 提示和 E03 批量入口。BF16、greedy，输出上限 800 Token。历史正文与完整 prompt 分别核对。 |
| 评分 | `f03-v1`，Judge `gpt-4o-2024-08-06`。截断按产出的原文计分。技术失败先用同配置恢复，定案失败和空答计 0 并留在分母。缺评和 Judge API 错误须补齐后再发布。正式题单当前含 5 道偏好题，F03 未对该题型专项校准。 |
| 分析 | 主要比较为 Q−C、各策略的 K1−K0，以及 `(Q1−C1)−(Q0−C0)`。按题配对，95% 区间按 A03 证据组估计。D07 的 1024/4096 和覆盖消融用于开发集证据诊断。 |

## 冻结前确认

**A03 定稿。** 80 题与本次 D06 开发题无题号重叠。历史审计记录了 32 题曾进入旧检索或选材实验，其中 12 题也进入过旧阅读实验，具体题号已附入计划。由 A 线确认旧结果是否影响本次方案、候选或参数，交付最终题单和依据。若替换题目，按正式清单重新对齐 C04、B04、B06 和评估文件，再复跑接口检查。

收到 A03 最终题单后，更新计划中的 `approvals.a03_final`、题单及对应指纹，将状态设为 `frozen`。当前计划只允许 1–2 题做接口检查，回执标记为 `interface_check_only`。正式安排 GPU/Judge 时，首批先核对真实回答、续跑和 F 评分回执，再扩大批次。

[G01 验收记录](../G01/ACCEPTANCE.md)保留 C02 的 6 条失败、成本口径、未知项和换题后的核对条件，供后续问题检查及报告引用。

## 本地复核与正式运行入口

从工作树根目录运行。分词器目录需包含匹配 E03 的 tokenizer、聊天模板和模型配置，脚本会核对归档指纹。示例使用当前候选题单的前两题。

```bash
python -m G.G02.prepare \
  --tokenizer /path/to/reader-snapshot \
  --question-ids 10d9b85a 69fee5aa \
  --output-dir runs/g02/interface-2048
```

输出 `selections.jsonl`、`reader_inputs.jsonl` 和 `receipt.json`。对每份材料重放选择，重建选中原文，核对正文 Token、CoN prompt 容量和记录标识。接口诊断可显式使用 `--preview-budget 1024`，候选文件原有预算元数据随输入哈希保留。

单独构建供 A04/F04 使用的正式评估文件。原始数据采用 [LongMemEval 官方清理版](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/main)。程序在读取前核对 A03 的 SHA-256，并逐题核对公开问题和轮次映射。

```bash
python -m G.G02.prepare_eval \
  --dataset /path/to/longmemeval_s_cleaned.json \
  --output runs/g02/formal_eval.jsonl
```

正式执行时，D08 按清单分批出阅读材料，E04 在学校 Slurm GPU 上使用 E03 入口，每个正式批次保留自己的输出目录和回执。技术失败用同一输入、配置及目录恢复。F04 从同批最终输出拿到答案后使用以下入口。批次示例为两题 × 十种设置。

```bash
python E/E03/run_generation.py --stage formal \
  --input runs/g02/batch-01/reader_inputs.jsonl --output runs/g02/batch-01/reader
python E/E03/export_for_f.py --run-dir runs/g02/batch-01/reader \
  --output runs/g02/batch-01/answers_for_f.jsonl
python F/src/evaluation/judge.py --expect-n 20 \
  --answers runs/g02/batch-01/answers_for_f.jsonl \
  --eval runs/g02/formal_eval.jsonl \
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
