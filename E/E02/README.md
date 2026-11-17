# E02：五题阅读验证

2026-11-17：本地输入适配与离线接口检查已完成。真实 tokenizer 检查、GPU 生成、人工答案核对及真实 Judge 评分尚未执行，**E02 尚未完成**。

## 已准备的文件

- `inputs/dev5_budget.jsonl`：D02 的五题 K0/R、2048 Token 材料，历史文本逐字保留。
- `inputs/dev5_topk.jsonl`：相同五题，按 B02 排名取前50轮，采用官方 flat-turn JSON 排序/序列化，作为原排名参照。
- `inputs/dev5.jsonl`：以上合计10条；运行时建议两种版本分开提交，长参照输入失败不影响预算版。
- `inputs/topk_selections.jsonl`：参照版选中轮次，供 F 的证据汇总使用；实际 context_tokens 需从生成结果补充。
- `inputs/sources/`：固定版本的 D02、B02、五题 A01 公开轮次和来源指纹。只有开发题原文，不含参考答案或证据标签。
- `prepare_inputs.py`：从以上来源重建全部输入，不需要模型或 GPU。修改来源文件后会因哈希不匹配而拒绝运行。
- `export_for_f.py`：把真实生成结果转换为 F 的交接格式，保留原始结果，不调用评分 API。
- `handoff/f_evaluation.patch`：给 F 分支的最小兼容补丁；没有把 F 分支合入 E 分支。

预算版和参照版使用不同的历史文本格式。这是“项目预算材料 vs 原排名官方格式”的流程参照，不是仅控制 token 数的纯预算消融。正式两索引×五方法实验仍须统一使用项目材料格式。

## 固定配置与来源

模型沿用 E01：`meta-llama/Llama-3.1-8B-Instruct`，revision `0e9e39f249a16976918f6564b8830bc894c89659`，BF16、greedy、Transformers、输出上限800。

官方代码固定在 [LongMemEval 9e0b455](https://github.com/xiaowu0162/LongMemEval/tree/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/generation)。其中 shell 的 `con` 对应单次调用、`--cot true`；`con-separate` 才增加逐块笔记调用。top-k=50 来自官方 shell 默认值，不声称它就是论文所有实验的参数。

参照版遵循：按检索排名取top-k → 稳定按日期排序（同日期保留排名顺序）→ 用户及下一条消息 → 编号 Session、默认 JSON 格式，不对重叠消息去重。预算版继续使用 D02 的去重、原文顺序及紧凑 JSON 格式。两者都不在 E 端偷偷截断；超过容量就停止，因此不是逐字节复现整个官方后端。

输入来源 commit 和文件 SHA-256 在 `inputs/sources/manifest.json`。运行器校验 context 哈希，预算版同时核对 D02 的 token 数与 tokenizer 指纹；如果指纹不一致，先排查版本或 tokenizer 文件，不能直接删除检查。

## 本地离线检查

在项目根目录执行（本地 `python` 指向 Python 3.10 或以上）：

```bash
python E/E02/prepare_inputs.py
python E/E02/run_generation.py --input E/E02/inputs/dev5.jsonl --schema-only
python -B E/E02/test_e02.py
```

E 线有8项测试；存在并修补 F 分支时再执行3项 F 交接测试。隔离副本中11项均通过，包括真实 D02/B02 输入、模拟 Judge 到真实 A02 证据关联。模拟回答和评分只存在于临时测试目录，不是实验成果；未调用 GPU 或付费 API。

本地没有缓存对应 Llama tokenizer，`--schema-only` 不能代替服务器的 `--check-only`。

## 服务器运行

先同步本地代码和输入到服务器的 e01 分支，再在服务器终端执行：

```bash
cd /home/msai/chunjie001/projects/AI6103-DL-Project
git switch e01
git pull --ff-only origin e01
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01
mkdir -p logs

# CPU 分词、指纹、预算与容量检查；失败时不要提交生成。
python E/E02/run_generation.py --input E/E02/inputs/dev5_budget.jsonl --check-only
python E/E02/run_generation.py --input E/E02/inputs/dev5_topk.jsonl --check-only
```

检查通过后提交。可先提交预算版，再提交参照版，以控制并发额度：

```bash
sbatch --partition=MGPU-TC2 --qos=normal jobs/e02_tc2.sh E/E02/inputs/dev5_budget.jsonl
sbatch --partition=MGPU-TC2 --qos=normal jobs/e02_tc2.sh E/E02/inputs/dev5_topk.jsonl
squeue -u "$USER"
```

使用已有 `e01` 环境及缓存模型，不重新下载。参照版尚未实测显存；若OOM，记录失败再处理，不能静默减少top-k或换量化精度。每次作业输出到 `runs/e02/job-<JOBID>/`；SBATCH断线后仍可继续。

## E→F 交接

真实结果的 `raw_output` 保存全文；`hypothesis` 保存唯一明确 `Final answer:` / `最终答案：` 标记后的完整答案（可多行），否则为空，`parse_status=needs_review`。不猜测最后一句。生成成功为 `generated`；空输出、截断及技术失败分别标记。

将下面的 `JOBID` 替换为真实作业号：

```bash
python E/E02/export_for_f.py --input runs/e02/job-JOBID/results.jsonl --output runs/e02/job-JOBID/answers_for_f.jsonl
```

导出器仅把 `generated` 映射为 F 接受的 `ok`，同时保留 `generation_status`。其他失败状态不会伪装成功。F补丁使 E02 v2 的明确答案提取由 E 负责；没有明确答案标记时使用全文评分并保留需复核标记，不再重复用另一套规则提取。

给 F：`answers_for_f.jsonl`、`config.json`、原始 `results.jsonl`；同时给出本目录的 D02 selections、B02 candidates、topk selections 和 [补丁说明](handoff/README.md)。`config_version` 保留选择配置，阅读器单独记录 `reader_config_version=e02-v2`。

归档时还应保存实际作业终态 `slurm_final.txt`。五题两种版本的真实输出、提取核对和参照核对齐全后才验收 E02；正确率由 F02 实际评分确认。
