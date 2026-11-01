# E02：首批五题阅读验证

状态：接口、运行脚本和 CPU 检查已准备；等待 D02 真实材料，尚未运行 GPU 实验，也未完成 E02。

## 阅读方式与范围

已核对[成员2的 B01 报告](https://github.com/lonelyhat/AI6103-DL-Project/tree/f9e9e65310d3e30bd823daafaae6e8878c147837/B-%E6%A3%80%E7%B4%A2%E7%BA%BF)和[固定版本官方代码](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/generation/run_generation.py)。

- 官方 `con` 是一次调用中先整理相关信息、再回答；逐块提取笔记的是 `con-separate`。此前 E01 说明将两者混淆，在此更正，原始实验记录不改写。
- 本脚本预备采用官方 `con` 提示词，使用 E01 的 Llama-3.1-8B-Instruct 及相同 revision、BF16、greedy，输出上限 800。主实验配置尚未冻结。
- 后端沿用已验证的 Transformers；属于后端适配，不声称与官方 vLLM 完全相同。
- 脚本读取准备好的历史文本，不重新检索、选择、排序或截断。一次加载模型，顺序生成五题。

## 输入接口（待与 D02 对接）

这是回答脚本内部的最小 JSONL 接口，每行一题一个版本。组员不必更改已有交付格式；拿到 A01/D02 文件后再映射这些字段。

| 字段 | 内容 |
| --- | --- |
| `stage` | `dev` |
| `question_id`, `question`, `question_date` | A01/D02 对应题号、问题、日期 |
| `context` | 最终历史文本，保留标题、日期、JSON 外壳和原始对话 |
| `variant` | `budget` 或 `original_topk` |
| `budget_tokens` | budget 版本必需；首轮计划为 2048 |
| `topk` | original_topk 版本必需；记录上游实际采用值 |
| `context_tokens` | 可选，D02 提供时核对实际 Llama 计数 |
| `index`, `strategy`, `source` | 可选，用于记录 K0/R 及交付来源 |

同一题的两个版本可放进同一个文件；此首轮接口只覆盖单个索引/策略，不是 E03 的通用批量接口。每版本五题是交付要求，程序会打印实际题数。
参考答案和证据标签不进入 prompt。未知顶层字段不会加入模型输入；交接时仍需确认 context 本身只含历史原文。

预算以 context 的 Llama Token 数计算，完整聊天模板输入另计。超过预算或模型容量时停止，不静默裁剪材料。
若 D02 尚未按官方历史格式计数，应先对齐渲染方式，不能在回答时换格式后继续声称预算不变。

原排名版还需要 B02 排名及原文映射：按排名取 top-k，再按官方规则排序与拼接。脚本仅检查已提供的文本，不能凭 `topk` 字段证明上游选择正确；接入后须核对。k=50 是官方脚本默认值，不等于已核实论文实验参数。预算版与排名版分别记录。

## 服务器 VS Code Terminal 操作

以下命令等待真实五题文件准备好再执行。约定适配后的输入放在 `e02/inputs/dev5.jsonl`，目前该文件不存在。
本地新增代码需先 commit/push，再在服务器拉取；不重新安装环境或下载模型。

```bash
cd /home/msai/chunjie001/projects/AI6103-DL-Project
git switch e01
git pull --ff-only origin e01
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01

# 仅 CPU 分词与输入检查，不加载模型，不申请 GPU。
python e02/run_generation.py --input e02/inputs/dev5.jsonl --check-only

# 上一步通过后才提交。沿用学校的分区及额度。
mkdir -p logs
sbatch --partition=MGPU-TC2 --qos=normal jobs/e02_tc2.sh e02/inputs/dev5.jsonl
```

实际输入、渲染后的 prompt、原始回答与逐题指标集中写入 `runs/e02/job-<JOBID>/results.jsonl`。
共同模型、环境和运行配置写入同目录 `config.json`。模型加载与预热单列，生成耗时包含 prefill。
原排名版输入可能明显较长：本脚本检查模型容量，但未实测显存是否足够，不承诺 top-50 一定可运行。

## 答案与交付

`hypothesis` 保留完整回答，便于 F01/F02 使用；`extracted_answer` 目前只提取明确的 `Final answer:` 或 `最终答案：` 行，否则为 null，`parse_status=needs_review`。这是临时保守解析，不是已与 F01 校准的结构化答案协议。
空输出或达到输出上限也标记复核；技术异常记录后停止，已完成行保留。恢复运行属于 E03，当前不自动续跑或重试。

提交结果时保留本说明（补充实际结论）、`config.json`、`results.jsonl`、`slurm_final.txt` 即可。不重复提交 Token ID、环境快照和多份报告。
只有取得五题真实输出、完成答案提取复核和原排名版本核对后，才能标记 E02 完成；回答正确性另交 F02。

## 当前验证

已通过 Python 语法、官方提示词逐字匹配、输入字段隔离、预算/计数/容量检查、重复记录检查和答案提取的合成 CPU 检查。
这些检查没有调用模型，也不是五题实验结果。真实 tokenizer 和 GPU 检查等待服务器材料交付。
