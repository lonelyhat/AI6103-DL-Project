# D06：开发参数扫描与 E 交接

## 当前完成状态

2026-11-18：D06已完成。34题、两种索引、17个方法/参数配置共1156份材料、回答与评分齐全，7条截断原样评分，API错误及不明确判分均为0。

按原计划预先记录的建议规则，以K0/K1平均开发正确率为每种方法选择共同参数，并列先取较小lambda、再取较小gamma：MMR lambda=0.5；C lambda=1；Q lambda=0.5、gamma=1。R与FL无扫描参数。C与Q分别独立调参。

报告：`output/dev34-parameter-selection-v1/REPORT.md`；参数：同目录`selected_parameters.json`；完整34个“索引×方法/参数”成绩在`parameter_grid.csv`，1156条逐记录成绩在`scored_records.csv`。这些是开发集选参结果，不是正式实验结论。

离线复现汇总（用新的输出目录，避免覆盖）：

```bash
python -m D.D06.summarize --output-dir D/D06/output/dev34-parameter-selection-v2
```

该命令只读已有评分，不加载密钥或调用API。会检查每条评分的模型版本、f03-v1、回答指纹、完整题目/参数网格及并列规则。D07、G02、D08仍需后续执行。

## 已完成选择、但导出报 JSONDecodeError 的恢复

原始对话中有合法的 Unicode 分隔字符（U+0085/U+2028/U+2029）。旧 E03 导出器和输入加载器使用 `str.splitlines()`，误把这些字符当成 JSONL 的记录边界。修复为按文件实际行读取；没有修改对话内容或选择算法。

如果已看到 `1156/1156` 后才报错，现有 shards 可以保留。使用专门恢复入口，**不重新运行 prepare 或 --resume**：

```bash
cd /home/cyr2526/DL_project/AI6103-DL-Project
source /home/cyr2526/DL_project/.conda/d06/bin/activate
python -m D.D06.finalize \
  --output-dir D/D06/output/dev34-grid-v1 \
  --tokenizer /home/cyr2526/DL_project/model_cache/Llama-3.1-8B-Instruct-tokenizer
python -m D.D06.preflight \
  --input D/D06/output/dev34-grid-v1/reader_inputs.jsonl \
  --tokenizer /home/cyr2526/DL_project/model_cache/Llama-3.1-8B-Instruct-tokenizer
```

恢复器检查冻结计划里的输入/源码指纹、1156份材料的原始决策重放凭据与文件哈希、原文重建及实际 token。仅允许上述两个 E03 文件从已知旧哈希变为精确的修复版本；任何数据或选择源码变化仍拒绝。原 plan.json 不改，修复前后哈希单列在 recovery_manifest.json。该恢复入口针对本项目默认 B03/B05 候选路径；自定义候选实验不应直接套用。

给 E 除了阅读输入、plan.json、handoff.json，还须附 recovery_manifest.json，并同步修复后的 `E/E03/batch.py`、`E/E03/prepare_inputs.py`。新 E 作业配置将记录修复后的 batch.py 哈希，D06 接收器已显式支持这个版本；不能在旧 E 作业目录中以修改后的源码继续生成，应使用本轮的新目录。

下文保留材料生成、E交接及恢复流程，用于复现；其评分及选参结果已完成，以上方当前状态为准。D07 仍依赖 D06，D08 仍依赖 G02。

## 范围与固定规则

- 默认使用 A01 首批五道可回答开发题，B03 的 K0 与 B05 的 K1 配对，历史预算固定 2048 token。
- R、FL 各一个配置；MMR 和 C 各扫描 lambda={0,0.5,1}；Q 独立扫描同样的 lambda 和 gamma={0,0.5,1} 的笛卡尔积。每个索引17个配置，五题共170份，全部34道可回答开发题共1156份。
- C 与 Q 分别调参，不要求两者采用相同的最优 lambda。零权重合法。不同配置即使得到相同文本也保留独立身份，不能默默丢弃后改变计分范围。
- 完整遍历冻结网格，不按中间结果提前停止。建议最终按 K0/K1 配对平均正确率分别为每种方法选一个配置，并列时先选较小 lambda、再选较小 gamma。该建议须与 F03 的失败处理、判分范围一起固定后才用于选参。
- 不读取参考答案、证据标签或正式题；材料生成不能代替答题效果比较。

## 本机运行（WSL）

项目已有独立环境 `/home/cyr2526/DL_project/.conda/d06`。本机原 longmemeval 环境的 transformers=4.43.3/tokenizers=0.19.1 与 E 验收版本不同，不能用于这次交接。新环境匹配 transformers=4.51.3、tokenizers=0.21.4、huggingface-hub=0.30.2，不改原环境。

```bash
cd /home/cyr2526/DL_project/AI6103-DL-Project
source /home/cyr2526/DL_project/.conda/d06/bin/activate
export HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
python -m D.D06.prepare \
  --tokenizer /home/cyr2526/DL_project/model_cache/Llama-3.1-8B-Instruct-tokenizer \
  --output-dir D/D06/output/dev5-grid-v1
```

中断后在完全相同的命令末尾加 `--resume`。已写完的材料会校验指纹并重放，不重新选择；输入、源码、问题范围、网格或分词器改变时拒绝续跑。新实验用新目录。每份材料验证完成才落盘；空材料失败退出，不能交给 E。

全部34题：增加 `--all-questions`，并换新输出目录。单题测时：增加 `--question-ids 2318644b`。`--lambdas`、`--gammas` 可显式指定其他网格，均写入 plan.json。

本机一道真实题、K0/K1全网格34份实测131.44秒（含生成、决策重放及导出）。线性估算五题170份约11分钟，全部34题1156份约75分钟。由于题目长度和选中轮次数不同，分别建议预留10–20分钟和1–2小时。只测了一道题，不能当作完整题集的实际总耗时；不含环境安装、E模型推理、F评分和GPU排队。首次测时保存在 `output/benchmark-one-question/initial_timing.json`，续跑耗时只代表重放，不能用来估算首次生成。

输出：

| 文件 | 用途 |
| --- | --- |
| `plan.json` | 问题、配对索引、网格、预算、源文件和输入指纹、停止规则 |
| `shards/` | 每题每索引每配置的选择轨迹、原始阅读文本和重放验证记录 |
| `reader_inputs.jsonl` | 使用 E03 现有转换器生成的完整阅读输入，含配置身份 |
| `handoff.json` | E 输入数量、文件哈希和来源 |
| `summary.json` | 总耗时、线性规模估计及等待 E/F03 的状态 |

R 使用 D02 的排名跳过算法并重新检查排名决策；其余四方法使用 D03–D05 实现与逐步独立决策重放。每份材料检查实际序列化 token 预算、配置和文本指纹。分词器指纹必须与 E03 已验收批次一致；不把本地指纹改写成服务器指纹。

本机也可使用 E 的原函数检查完整提示词与容量，不加载权重：

```bash
python -m D.D06.preflight \
  --input D/D06/output/dev5-grid-v1/reader_inputs.jsonl \
  --tokenizer /home/cyr2526/DL_project/model_cache/Llama-3.1-8B-Instruct-tokenizer
```

## 交给 E 的输入与命令

把完整的 `reader_inputs.jsonl` 原样交给 E，附上 `plan.json`、`handoff.json`，并保留 D 的 shards 供证据关联。不要通过改路径重建 reader_inputs 后继续旧批次，因为这会改变输入身份指纹。

E 在其已经验收的服务器 e01 环境、仓库根目录运行，假设文件保存到 `runs/d06/dev5-grid-v1/reader_inputs.jsonl`：

```bash
python E/E03/run_generation.py \
  --input runs/d06/dev5-grid-v1/reader_inputs.jsonl --check-only
mkdir -p logs
sbatch jobs/e03_tc2.sh \
  runs/d06/dev5-grid-v1/reader_inputs.jsonl runs/e03/d06-dev5-grid-v1
```

先通过严格预算、分词器和容量检查，才运行 GPU。保持已验收的 Llama-3.1-8B-Instruct 固定 revision、con 提示词、确定性生成及800输出 token 上限。中断后向同一作业命令追加 `--resume`，不能换输出目录当作续跑；输出截断、空回答和技术失败均保留并报告。1156份可能超过脚本默认1小时限制，应事先延长合法的作业时限或使用同一输出目录分段恢复。

生成后导出给 F：

```bash
python E/E03/export_for_f.py --run-dir runs/e03/d06-dev5-grid-v1 \
  --output runs/e03/d06-dev5-grid-v1/answers_for_f.jsonl
```

## 需要 E 返回什么

请交回完整 E 运行目录，至少包含：

1. `inputs.jsonl`：实际使用的170条输入快照。
2. `config.json`：模型/revision、提示词与源码哈希、分词器、生成参数、环境和输入哈希。
3. `attempts.jsonl` 与 `results.jsonl`：全部尝试和最终唯一结果，包含原始回答、提取答案、解析状态、失败状态、输入输出 token、生成耗时。
4. `summary.json`：预期170、已记录170、缺失0；失败、空回答、截断需列明。
5. `answers_for_f.jsonl`：给 F03/后续评分的导出，保留完整 raw_output 和 needs_review。
6. `runtime.jsonl`、`invocations.jsonl`、作业状态/日志：用于恢复核对和耗时/成本追溯。

逐条保留 `record_id`、`input_record_sha256`、`reader_config_id`、`selection_config_id`、`history_sha256`，以及 question_id/index/strategy。不能仅按题号+策略去重，否则会吞掉不同权重和索引的实验。

已有 E03 的25条 K0 单配置回答用于程序验收和 F03 校准，不能作为170条双索引参数扫描的完整结果。`needs_review` 应送 F 按固定规则处理，不能把解析失败当作模型未作答。

接收后验证（E目录不应仍有写锁）：

```bash
python -m D.D06.check_reader \
  --handoff-dir D/D06/output/dev5-grid-v1 \
  --run-dirs path/to/returned-e-run \
  --output D/D06/output/dev5-grid-v1/e_receipt.json
```

支持多个不重叠批次目录，但阅读配置必须相同。检查输入和配置哈希、逐条关联、最终结果与全部尝试的一致性、缺失和重复；不会自动判分或选参。F03 仍须交付校准样例、统一 judge 模型/版本/提示词、计分分母、失败与分歧处理规则，以及保留配置身份的逐条评分，之后才能冻结最优参数。

## 验证

```bash
python -m unittest D.D06.test_d06 D.D01.test_selection D.D02.test_materials D.test_selection_batch -v
```

包含真实 B03/B05 配对检查、网格公平性与零权重、已有25条 E 返回验收、重复和哈希损坏拒绝。另以一道真实题的两种索引全网格测量材料生成与重放耗时；实测见 output/benchmark-one-question/summary.json。估计不包括模型推理、GPU排队或评分。
