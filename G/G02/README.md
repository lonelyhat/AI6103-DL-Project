# G02 正式配置与执行清单

**2026-11-19，本地冻结 `g02-v1`，可交给 D08。** [冻结配置与八批题单](plan.json)固定了正式输入、参数与指纹，[核验回执](validation.json)记录放行证据。A03、C04 事实及 B04/B06 候选取自 `main@68b2462`；开发参数与证据诊断分别取自 `D06@e870a08`、`D07@c2574c1`。G01 已验收。

## 正式设置

| 项目 | 冻结设置 |
| --- | --- |
| 正式题 | `a03-v2` 的 80 道可回答题、78 个证据组。各题各跑 K0/K1 × R/MMR/C/Q/FL，共 800 个设置结果。 |
| 候选 | B04 K0 和 B06 K1 均为 v2，每题每个索引各 100 条。K1 用事实与用户原文检索，两套索引均把完整原始轮次交给选材器。 |
| 选材与预算 | 历史正文上限 2048 Token。R 按排名逐条检查并跳过放不下的完整轮次。MMR 的 λ=0.5，C 的 λ=1，Q 的 λ=0.5、γ=1，FL 用 D06 原配置。两种索引共用同一组方法参数。 |
| 阅读 | Llama 3.1 8B Instruct，revision `0e9e39f249a16976918f6564b8830bc894c89659`，采用 E02 的 CoN 提示和 E03 批量入口。BF16、greedy，输出上限 800 Token。历史正文与完整 prompt 分别核对。 |
| 评分 | `f03-v1`，Judge `gpt-4o-2024-08-06`。截断按产出的原文计分。技术失败先用同配置恢复，定案失败和空答计 0 并留在分母。缺评和 Judge API 错误须补齐后再发布。按 A03 旧用题排除规则，正式结论覆盖五种题型，偏好题不在本轮范围。 |
| 分析 | 主要比较为 Q−C、各策略的 K1−K0，以及 `(Q1−C1)−(Q0−C0)`。按题配对，95% 区间按 A03 证据组估计。D07 的 1024/4096 和覆盖消融用于开发集证据诊断。 |

## 放行依据和后续归档

v2 排除了 200 个旧测试题及其共享证据组，保留 43 道、替换 37 道。已核对两套候选各 8,000 条，18,841 个事实键与 19,539 个历史轮次位置对齐，评分输入与同一题单对应。真实分词的 D→E 预检和 E→F 离线交接均通过。

**C04 v2 的运行账本待补。** 请 C 线交付抽取配置、带来源的复用／补抽清单、失败与重试记录，以及 Token 和耗时原件。现有事实内容及其指纹已冻结，账本供后续 C05、F07、G03 核验。共有 7,949 个轮次按原文索引，缺少运行账本时不能将它们计作失败。账本缺失的字段记为未知。

C05 另查预检识别的 3 个非事实缓存键，它们均未进入当前两套前 100 候选。检索编码上限统一为 512 Token，K0 有 119 轮截断，K1 有 128 轮。D08 仍用完整原始轮次，检查 2048 Token 阅读预算。

[G01 验收记录](../G01/ACCEPTANCE.md)保留 C02 的 6 条失败、成本口径、未知项和换题后的核对条件，供后续问题检查及报告引用。

## 本地复核与正式运行入口

从工作树根目录执行。D08 可在 CPU 上运行；分词器目录需包含匹配 E03 的 tokenizer、聊天模板和模型配置。计划中的 `batch-01` 至 `batch-08` 各含 10 题、100 个设置，两套候选和预算须与冻结配置一致。

首批已生成并验证 100 个设置，交接包位于 [D08 交付目录](../../D/D08/delivery/README.md)，文件指纹见 [核验回执](validation.json)。E04 可使用解包后的原始 `reader_inputs.jsonl`，D 线可从 `batch-02` 继续生成。

```bash
python -m G.G02.prepare \
  --tokenizer /path/to/reader-snapshot \
  --batch-id batch-01 --output-dir runs/g02/d08-g02-v1-batch-01
```

每批交付 `selections.jsonl`、`reader_inputs.jsonl` 和 `receipt.json`。程序重放选择、重建选中原文，核对正文 Token、CoN prompt 容量和记录标识。选择耗时按同题共享的精确分词缓存条件实测。E04 接收字节不变的原始输入文件及回执；A04 接收选择文件。后续批次更换 `--batch-id` 和输出目录。

单独构建供 A04/F04 使用的正式评估文件。原始数据采用 [LongMemEval 官方清理版](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/main)。程序在读取前核对 A03 的 SHA-256，并逐题核对公开问题和轮次映射。

```bash
python -m G.G02.prepare_eval \
  --dataset /path/to/longmemeval_s_cleaned.json \
  --output runs/g02/a03-v2-formal-eval.jsonl
```

E04 在学校 Slurm GPU 上使用 E03 入口。首批先跑实际生成和评分，核对输出和错误状态后再扩大。技术失败用同一输入、配置及目录恢复。F04 从同批最终输出拿到答案后使用以下入口，首批为 100 个设置。

```bash
python E/E03/run_generation.py --stage formal --check-only \
  --input runs/g02/d08-g02-v1-batch-01/reader_inputs.jsonl
python E/E03/run_generation.py --stage formal \
  --input runs/g02/d08-g02-v1-batch-01/reader_inputs.jsonl --output runs/g02/batch-01/reader
python E/E03/export_for_f.py --run-dir runs/g02/batch-01/reader \
  --output runs/g02/batch-01/answers_for_f.jsonl
python F/src/evaluation/judge.py --expect-n 100 \
  --answers runs/g02/batch-01/answers_for_f.jsonl \
  --eval runs/g02/a03-v2-formal-eval.jsonl \
  --questions 'A-数据线/A03/output/public/formal_questions.jsonl' \
  --out runs/g02/batch-01/scores.jsonl
```

首批先核对题号、索引、方法、预算、选材配置、阅读配置和内容指纹。A04 使用 A02 的消息级指标。F05 对至少 20% 的去重正式回答做独立双判，F06 按正式题清单和证据组汇总。开发网格与接口样例的记录保存在各自目录。

E 线每批归档 `inputs.jsonl`、`config.json`、`attempts.jsonl`、`results.jsonl`、`summary.json`、`answers_for_f.jsonl` 及作业／运行日志。F 线保留最终逐条评分、评分日志和人工复核记录，供 G03 对齐输入与输出。

### 离线复算 D06/D07

按 [D06 交付说明](../../D/D06/delivery/README.md)解包归档并复算参数，选择一个新的汇总目录。随后运行：

```bash
python -m G.G02.verify_development \
  --returned D/D06/returned/dev34-grid-v1 \
  --d06-recomputed D/D06/output/dev34-parameter-selection-recheck
```

检查覆盖 D06 归档校验和、全部评分汇总和参数、D07 三张表以及 2048 下可从 D06 重新核对的证据指标。
