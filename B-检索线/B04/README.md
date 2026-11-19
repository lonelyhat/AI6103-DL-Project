# B04：正式题的 K0 候选

处理 A03 正式题清单（`a03-v2`）的 80 道可回答题。检索方法与 B02/B03 相同：用 Stella V5 1.5B 编码历史中每一轮的用户发言，与当前问题比较相似度，每题取前 100 轮。K0 不加入抽取事实。候选编号对应完整原始轮次。本步只准备候选，不做材料选择、回答或评分。

2026-11-19 按 `a03-v2` 重跑完成：作业 `56001` 在 A40 上正常退出（`0:0`），总用时 **35 分 53 秒**（含官方对照）。80 题、8,000 条候选的前 100 顺序与官方程序**全部一致（80/80）**；完成后续跑会跳过全部 80 题，文件不变。

`a03-v2` 排除了 baseline_v1 旧实验用题及其共享证据组，相对 v1 换了 37 题（见 A03 文档）。v1 的结果（作业 `55289`，同样 80/80，两次独立运行逐字节相同）已被本版取代，日志保留在 `results/logs/` 供对照。

## 给下游的文件

| 文件（本目录下） | 内容 |
| --- | --- |
| `candidates/formal_K0.jsonl` | 80 道正式题，每题 100 条候选，顺序与 A03 `formal_ids` 一致 |
| `results/cost.json` | 编码、建索引、检索耗时与 token 数，逐题明细在 `per_question` |

每题一行，字段与 B02/B03 相同：A01 公共字段（`stage` 为 `formal`，`config_version` 为 `a03-v2`）加 `candidates: [{turn_id, rank, score}]`。`score` 是相似度，不是正确概率。

问题从 `A-数据线/A03/output/public/formal_questions.jsonl` 读取，完整原始轮次在 `A-数据线/A03/output/public/turns/{question_id}.jsonl`，格式与 A01 开发题相同。选择、回答程序不需要读取 `map/` 和 `eval/`。

`A-数据线/A03/output/map/` 是消息、轮次与官方编号的对应表（与 A01 的 `map/` 格式相同），供 A04 证据统计和官方对照使用，不能作为选择输入。

## 数据说明：重复会话

有 1 道正式题（`1d4da289`；v1 另有 3 道，已随换题移出）的历史里，同一个会话出现了两次：会话编号相同，内容逐字相同。这是原始数据本身的情况，开发题里没有。两份副本在本组编号下是不同的轮次（例如 `1d4da289-s000-t000` 和 `1d4da289-s045-t000`），相似度相同，所以会在候选里相邻出现。

对下游的影响：按相关性直接选择（R）时，两份相同内容可能同时被选中，占用预算。去重类方法（MMR 等）会自然处理。官方程序同样把两份副本都放进索引，本组没有删除或合并它们。

## 实现与复跑

- `prepare_inputs.py`：校验原始数据 SHA-256 与 A03 一致，调用 A01 原有的 `build_question()` 和 `public_turns()` 生成正式题的公开轮次与映射表；已有文件若内容不同则停止，不覆盖。同时生成只供官方对照使用的私有原始子集。
- `../shared/kretrieve.py`：B04 与 B05 共用的检索程序，编码方式直接复用 B02 的 `load_model()` / `embed()`。逐题原子保存 checkpoint，完整后才导出；checkpoint 绑定公开输入、模型校验值、检索配置、软件/GPU 和源码指纹，任一不同则拒绝续跑。`validate` 子命令检查候选结构和 D01 输入，并与官方检索日志逐题比较前 100 顺序。
- `../shared/test_kretrieve.py`：中断续跑、指纹不一致拒绝、不完整结果不能替换交付三项测试。

本机准备输入（在仓库根目录）：

```bash
python3 B-检索线/B04/prepare_inputs.py /path/to/longmemeval_s_cleaned.json \
  --official-subset B-检索线/B04/.private/formal80_longmemeval_s.json \
  --report B-检索线/B04/results/input_preparation.json
python3 B-检索线/shared/test_kretrieve.py
python3 B-检索线/shared/kretrieve.py run --stage formal --index K0 --validate-inputs
```

集群复用 `~/B02/venv`、`~/B02/stella/` 和 `~/B02/official/`。将仓库同步到 `~/B45/repo`，私有子集上传到 `~/B45/B04/formal80_longmemeval_s.json`，再提交：

```bash
cd ~/B45/repo
sbatch --account=stud --partition=MGPU-TC2 --qos=normal \
  --output="$HOME/B45/B04/logs/%x-%j.out" --error="$HOME/B45/B04/logs/%x-%j.err" \
  B-检索线/B04/job_b04.sh
```

作业依次完成：检索 80 题，完成后续跑检查（应全部跳过且文件逐字节不变），运行官方程序，最后验证。

## 验证记录

| 检查 | 结果 |
| --- | --- |
| 候选结构与 D01 输入校验 | 80 题全部通过，每题 100 条、排名连续、分数递减 |
| 与官方程序前 100 顺序比较 | 80/80 完全一致（按官方编号逐位比较，重复会话的两份副本编号相同） |
| 两次独立运行（v1） | 候选文件逐字节相同；v2 单次运行，候选 SHA-256 `45e70889…` |
| 完成后续跑 | 跳过全部 80 题，文件校验不变 |
| 故障恢复单元测试 | 中断后只补跑未完成题、指纹不一致拒绝续跑、不完整结果不能替换交付，三项通过 |

**一次性建库与检索消耗**（A40，Stella 分词器计数）：

| 项目 | 数值 |
| --- | --- |
| 模型加载（一次） | 14.4 秒 |
| 建索引：编码 80 题全部历史轮次 | 953.1 秒（平均每题 11.9 秒） |
| 检索：问题编码 + 相似度 + 前 100 排序 | 合计 3.0 秒（平均每题 0.04 秒） |
| 编码轮次数 | 19,539 |
| 编码 token 数（截断后 / 截断前） | 969,872 / 1,113,534 |
| 超过 512 token 被截断的用户发言 | 119 条（0.6%），截掉的是发言尾部，与官方设置相同 |

耗时不含模型校验和官方对照。

记录：[全部验证](results/validation.json)、[耗时与成本](results/cost.json)、[运行指纹](results/provenance.json)、[输入准备](results/input_preparation.json)、[依赖环境](results/environment.txt)、[续跑检查](results/resume_check.txt)、[续跑文件校验](results/resume_hash_check.txt)。作业日志在 `results/logs/`。这些检查只说明检索与官方一致，不构成问答正确率或证据齐全的结论。
