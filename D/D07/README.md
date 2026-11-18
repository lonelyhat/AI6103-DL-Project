# D07：预算变化与覆盖奖励诊断

## 当前状态

全量34题已完成并验收：1224份记录、408项2048预算D06基线核对、204组覆盖奖励配对、36组汇总，空材料为0。实跑1933.10秒（约32.2分钟）。审计重新核验全部源文件/材料哈希、原文及实际token，重算A02指标与三张CSV，并核对每份原始决策重放凭据，未重复运行贪心选择。见`output/dev34-budgets-v1/audit.json`与`REPORT.md`。

2048预算下，Q开启覆盖奖励相对关闭的平均消息证据保留率增量：K0为+8.82个百分点，K1为+7.84个百分点；两索引各有1题退步，已保留在配对结果中。这是开发证据诊断，不是回答准确率结论。D07完成不等于G02或D08完成。

## 范围

默认处理D06的全部34道可回答开发题、K0/K1、1024/2048/4096历史token预算。每个预算运行R/MMR/C/Q/FL及一项Q关闭覆盖奖励，共34×2×3×6＝1224条选择与证据诊断记录；生成204组Q开/关的同题配对。

固定D06选定参数：MMR lambda=0.5；C lambda=1；Q lambda=0.5、gamma=1；Q消融只将gamma改为0，其余不变。C与Q保留各自开发选定的lambda，不能把Q关闭奖励当作重新调参的C。R、FL没有扫描权重。

不运行阅读模型，不调用评分API，不重新调参，也不改变D06文件。A02的证据消息标签只用于诊断，选择函数只接受公开问题、候选、原始轮次、分词器与固定配置，不接受证据或参考答案。

## 本机完整运行

在WSL执行；使用已建立的d06环境，不需要API Key：

```bash
cd /home/cyr2526/DL_project/AI6103-DL-Project

/home/cyr2526/DL_project/.conda/d06/bin/python -m D.D07.run --check-only

/home/cyr2526/DL_project/.conda/d06/bin/python -u -m D.D07.run \
  --output-dir D/D07/output/dev34-budgets-v1
```

如果中断，在完全相同的命令后加`--resume`：

```bash
/home/cyr2526/DL_project/.conda/d06/bin/python -u -m D.D07.run \
  --output-dir D/D07/output/dev34-budgets-v1 --resume
```

恢复会校验计划、源码、输入和已写材料，并重新执行决策重放；已完成记录不重新选择。源码、数据、参数、问题范围、预算或分词器改变时拒绝续跑。正常中断会清理写锁；异常断电留下锁时，确认原进程已结束后再处理，程序不自动抢锁。

运行成功最后应显示`status: complete`、`questions: 34`、`records: 1224`、`baseline_2048_checks: 408`、`coverage_pairs: 204`。这只代表D07开发证据诊断完成，不包含正式配置冻结或D08。

本机单题36条流程实测75.45秒；线性推算全量约43分钟，建议预留40–90分钟。题目长度和选中轮次数会影响时间，该估计不等于全量实测。

单题检查（选新目录）：

```bash
/home/cyr2526/DL_project/.conda/d06/bin/python -u -m D.D07.run \
  --question-ids 2318644b --output-dir D/D07/output/one-question-v1
```

可显式使用`--budgets 1024 2048 4096`、`--tokenizer /path/to/cache`；默认值已经设好。变更范围必须选择新的目录。

## 数据与预算校验

- D06参数JSON与原始冻结计划的身份必须一致，候选与公开原文的哈希必须与D06一致。
- B03/B05原候选元数据的2048代表原条件。D07只在内存中显式改变选择预算，并把原预算、实验预算写进每份材料的清单，不改候选文件或静默伪造输入来源。
- 使用E/D06一致的Llama分词器指纹，按完整原始轮次、时间顺序和消息去重后计算实际长度。缓存保存精确计数，不使用长度估计。
- R用D02排名跳过策略并检查排名选择；其他方法用既有核心和独立逐步重放。所有保存文本与实际token预算均检查。
- 2048预算的全部六种条件逐条核对D06对应配置，检查选中轮次、原文、token、配置身份与历史哈希；不允许主预算实现漂移。
- 小预算可能产生空材料，保留记录与分母，证据保留率按A02实际计数。指标按消息ID并集去重，包括助手证据；不使用官方仅用户消息的轮级召回替代。
- 不调用A02的加和token归因器，不把独立轮token之和冒充实际拼接的最低覆盖预算。

## 输出

| 文件 | 内容 |
| --- | --- |
| `plan.json` | 固定参数、预算、题目与源码/数据/证据映射指纹 |
| `shards/` | 逐条件选择轨迹、完整材料、精确预算、重放凭据 |
| `evidence_metrics.jsonl` | 1224条证据指标、缺失证据消息ID、候选证据上限及配置身份 |
| `budget_evidence.csv` | 36组平均消息证据保留率、证据齐全率、token与空材料统计 |
| `coverage_ablation_pairs.csv` | 204组同题Q开/关比较及保留率差值 |
| `coverage_ablation_summary.csv` | 按索引和预算汇总消融增量、改善/退步/持平数 |
| `REPORT.md` | 可读证据诊断表 |
| `summary.json` | 首次完整运行状态、耗时和基线检查数量 |
| `resume_summary.json` | 恢复运行单独记账，不覆盖首次汇总 |

平均消息证据保留率为逐题比例的平均；证据齐全率为全部证据都保留的题目占比。两者不能混用。Q消融差值始终为gamma开启减关闭，保留正、负与零变化。贪心预算选择的集合不保证嵌套，因此不能假定预算更大时逐题证据一定更高。正式预算仍由G02确定。

## 测试

```bash
/home/cyr2526/DL_project/.conda/d06/bin/python -m unittest \
  D.D07.test_d07 D.D01.test_selection D.D02.test_materials D.test_selection_batch -v
```

覆盖显式预算干预不改原输入、固定lambda的Q消融、gamma=0与相同lambda的C一致、空材料分母、实际预算、决策重放、D06基线漂移及配对缺失/重复拒绝。真实单题完整流程及恢复验证见VALIDATION.md。
