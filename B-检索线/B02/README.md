# B02：首批五题 K0 真实候选交付

2026-11-02 完成 GPU 检索与官方排名核对。作业 `50055` 在 TC2N01 / NVIDIA A40 上正常完成（退出码 `0:0`），共用时 4 分 36 秒。首批 5 题各有 100 条真实 Stella 候选；五题前 100 名的编号及顺序全部与官方程序一致。

## 给 D 线的输入

- **候选**：[`candidates/dev_K0.jsonl`](candidates/dev_K0.jsonl)，每题一行，包含 A01 公共字段及 `candidates: [{turn_id, rank, score}]`。
- **问题**：仓库根目录 `A-数据线/A01/output/public/dev_questions.jsonl`。
- **原文**：`A-数据线/A01/output/public/turns/{question_id}.jsonl`。
- 使用 A01-v2 无泄漏位置编号，不需要向选择器传入 `map/`、`eval/` 或官方检索日志。
- `budget_tokens=2048` 是后续历史阅读预算；本次检索仍输出完整前 100 条候选，不在检索阶段按 2048 截断候选集。
- D01 自行基于完整轮次原文计算 TF-IDF 相似度；本交付不包含用户发言向量。

本次已经将真实候选与公开问题关联，并通过 D01 `validate` 对五题输入、原文与跨字段关系的检查。尚未执行 D02 正式选择、E02 回答或 F02 评分。

D01 的调用方式如下；须将占位的分词器路径换成实际可用的 **Llama 3.1 8B Instruct 分词器目录**，此命令不属于本次已执行的验证：

```bash
python D/D01/run_selection.py \
  --input B-检索线/B02/candidates/dev_K0.jsonl \
  --questions A-数据线/A01/output/public/dev_questions.jsonl \
  --turns-dir A-数据线/A01/output/public/turns \
  --tokenizer /path/to/Llama-3.1-8B-Instruct \
  --strategy all \
  --output /path/to/dev_K0_selections.jsonl
```

## 实跑结果

| 题号 | 原始轮次 | 候选 | 本组检索耗时 | 官方前 100 顺序 |
| --- | ---: | ---: | ---: | --- |
| 2318644b | 260 | 100 | 24.6 秒 | 完全一致 |
| 1cea1afa | 241 | 100 | 12.0 秒 | 完全一致 |
| gpt4_7a0daae1 | 276 | 100 | 10.4 秒 | 完全一致 |
| 4c36ccef | 263 | 100 | 12.8 秒 | 完全一致 |
| c960da58 | 250 | 100 | 14.8 秒 | 完全一致 |

单题耗时包括问题和历史编码、相似度计算、排序及候选整理，不包括模型加载和官方对照。五题合计约 74.6 秒；整项作业 276 秒还包含环境读取、模型加载与官方程序的另一次运行。不得把整项作业时间当作单次查询延迟。

## 配置与证据

- 基于团队 main `1826385a78a89cf9793a3fbe084755541bf7e41a`，A01 `a01-v2`。
- 官方 `run_retrieval.py` 与 GitHub 提交 `9e0b455f4ef0e2ab8f2e582289761153549043fc` 的原文件逐字节核对一致。
- Stella V5 1.5B，float32，512 token 截断，batch size 64，平均池化、1024 维投影、L2 归一化、向量点积；问题不加额外前缀，与官方一致。
- 实际环境和依赖：[`results/environment.txt`](results/environment.txt)。本次使用 PyTorch 2.11.0+cu128 / transformers 4.43.3；没有声称完整复现论文原始软件环境。
- 五题格式与排名核对：[`results/validation.txt`](results/validation.txt)。官方日志没有数值分数，因此核对的是前 100 编号和顺序，未声称逐项比较官方分数。
- D01 输入核对：[`results/handoff_validation.json`](results/handoff_validation.json)。
- 运行配置和结果指纹：[`results/run_manifest.json`](results/run_manifest.json)。
- 模型文件指纹：[`model_sha256.json`](model_sha256.json)，集群上 12 个文件均校验通过。
- 本组脚本、公开输入与官方脚本指纹：[`results/source_sha256.json`](results/source_sha256.json)。
- 作业日志：`results/logs/b02-50055.out` 与 `.err`；err 中为官方进度条，无运行错误。

官方完整检索日志含答案和官方 ID，只保存在集群 `~/B02/results/official/` 及本地被忽略的同名目录，不作为 D 线输入，不提交到本 PR。

## 复跑与范围

见 [`运行步骤.md`](运行步骤.md)。当前脚本固定处理 A01 首批五题，不会自动处理全部 40 道开发题。B03 的题单扩展、其余公开轮次准备及断点恢复仍待后续实现。

本次确认的是五题检索实现及格式可交接，尚不构成问答准确率结论，也不代表完整 G01 流程已完成。
