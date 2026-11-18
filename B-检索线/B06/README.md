# B06：正式题的事实增强（K1）候选

处理 A03 正式题清单（`a03-v1`）的 80 道可回答题，题目与 B04 相同。检索程序、模型和配置与 B04 的 K0 相同，K1 索引文本的构建方式与 B05 相同：

| | 索引文本 | 返回给下游的内容 |
| --- | --- | --- |
| K0（B04） | 用户发言原文 | 完整原始轮次 |
| K1（B06） | `该轮事实用空格连接 + " " + 用户发言原文`；没有事实的轮次只用原文 | 完整原始轮次，定义与 K0 相同 |

事实只参与检索，不进入阅读材料。K1 与 K0 的候选排名可以不同，但每个 `turn_id` 指向的内容完全一样。

2026-11-18 实跑完成：检索作业 `55732`（22 分 55 秒）和官方对照作业 `55733`（19 分 44 秒）都在 A40 上正常退出（`0:0`）。80 题、8,000 条候选的前 100 顺序与官方 K1 程序**全部一致（80/80）**；完成后续跑会跳过全部 80 题，文件不变。

与 B04 的 K0 相比，每题前 100 候选平均有 82.6 条重合（最少 71，最多 93），80 题的排序都有变化。这只说明事实改变了检索结果，K1 是否更好要到正式回答和评分后才能判断。

## 给下游的文件

| 文件（本目录下） | 内容 |
| --- | --- |
| `candidates/formal_K1.jsonl` | 80 道正式题，每题 100 条候选，顺序与 A03 `formal_ids` 一致；与 B04 的 `formal_K0.jsonl` 配对使用 |
| `inputs/formal_fact_sources.jsonl` | 每一轮的事实来源：对应的 C04 记录键、来源用户消息编号、事实条数 |
| `results/cost.json` | 编码、建索引、检索耗时与 token 数（含截断统计） |

字段与 B04 完全相同，只是 `index` 为 `K1`。问题和原文的读取位置与 B04 相同。

## 事实来源

事实来自 C04 交付的 `C04/c04_facts_80q.json`（SHA-256 见 `results/facts_preparation.json`），格式与 C03 相同。`B05/prepare_facts.py --stage formal` 把它转换成本组 `turn_id` → 事实列表（`inputs/formal_facts_by_turn.jsonl`），检索步骤只读这个文件和公开轮次。

| 项目 | 数量 |
| --- | --- |
| 80 题全部轮次 | 19,606 |
| 有事实的轮次 | 11,608 |
| 没有事实的轮次（只用原文索引） | 7,998 |
| C04 键被使用 / 未使用 | 18,892 / 0 |

每一轮都必须找到 C04 记录，缺一条程序就停止。C04 中有 5 条值是字符串、3 条列表里含字典，按官方读取方式处理，影响可忽略。

## 与官方程序的差异

本组 K1 的定义是“每一轮用户发言前拼一次该轮事实，没有事实就用原文”，对所有轮次一视同仁。官方 LongMemEval 的 K1 代码在三种边界情况下与这个定义不一致，本组交付的候选按上述定义构建；与官方对照时，官方程序也按同样的定义做了对应的最小调整（`B05/prepare_official.py`，各一两行），其余编码、截断、拼接和排序完全沿用官方：

| 情况 | 官方原代码的行为 | 本组做法 |
| --- | --- | --- |
| 某轮没有抽出事实（C 线记为空列表） | 该轮被整轮移出索引，永远检索不到 | 保留该轮，用原文索引（与 K0 相同） |
| 证据会话中的非证据轮 | 因内部编号前缀不同，拿不到事实；是否加事实取决于证据标注 | 所有轮同样加事实，不依赖标注 |
| 历史中同一会话重复出现（4 道正式题） | 每份副本都被拼两遍事实（“事实 事实 原文”） | 每份副本拼一次 |

第三种只出现在正式题，开发题（B05）没有重复会话，不受影响。

**B04 的对照方式也有一处相应调整**：重复会话的两份副本在本组是两个不同的 `turn_id`，在官方日志里却是同一个编号。B04 因此按官方编号逐位比较前 100 顺序（两份副本相似度相同，在候选中相邻出现），B06 沿用同一方式。

## 实现与复跑

- `../B05/prepare_facts.py --stage formal`：C04 事实转换与来源记录。
- `../B05/check_k1_text.py --stage formal`：不用 GPU，按官方 K1 流程逐题构建索引文本，与本组 K1 文本逐条比较。
- `../shared/kretrieve.py`：B04/B05/B06 共用的检索程序，以 `--stage formal --index K1 --facts ...` 运行。
- `job_b06_retrieve.sh`：集群检索与完成后续跑检查；`job_b06_official.sh`：官方对照与验证（以 `--dependency=afterok` 接在检索之后）。

本机准备（在仓库根目录）：

```bash
python3 B-检索线/B05/prepare_facts.py C04/c04_facts_80q.json --stage formal \
  --out B-检索线/B06/inputs/formal_facts_by_turn.jsonl \
  --sources B-检索线/B06/inputs/formal_fact_sources.jsonl \
  --report B-检索线/B06/results/facts_preparation.json
python3 B-检索线/shared/kretrieve.py run --stage formal --index K1 \
  --facts B-检索线/B06/inputs/formal_facts_by_turn.jsonl --validate-inputs
```

集群复用 `~/B02/venv`、`~/B02/stella/`、`~/B02/official/` 和 B04 的私有正式题子集 `~/B45/B04/formal80_longmemeval_s.json`。仓库同步到 `~/B45/repo` 后提交：

```bash
cd ~/B45/repo
J=$(sbatch --parsable --account=stud --partition=MGPU-TC2 --qos=normal \
  --output="$HOME/B45/B06/logs/%x-%j.out" --error="$HOME/B45/B06/logs/%x-%j.err" \
  B-检索线/B06/job_b06_retrieve.sh)
sbatch --dependency=afterok:$J --account=stud --partition=MGPU-TC2 --qos=normal \
  --output="$HOME/B45/B06/logs/%x-%j.out" --error="$HOME/B45/B06/logs/%x-%j.err" \
  B-检索线/B06/job_b06_official.sh
```

## 验证记录

| 检查 | 结果 |
| --- | --- |
| 候选结构与 D01 输入校验 | 80 题全部通过 |
| K1 索引文本与官方 K1 流程逐条比较 | 19,606 轮全部相同 |
| 没有事实的轮次 K1 与 K0 文本比较 | 7,998 轮全部逐字相同 |
| 与官方 K1 程序前 100 顺序比较 | 80/80 完全一致（按官方编号逐位比较） |
| 完成后续跑 | 跳过全部 80 题，文件校验不变 |

**一次性建库与检索消耗**（A40，Stella 分词器计数）：

| 项目 | 数值 |
| --- | --- |
| 模型加载（一次） | 13.3 秒 |
| 建索引：编码 80 题全部“事实 + 原文” | 1,167.5 秒（平均每题 14.6 秒） |
| 检索：问题编码 + 相似度 + 前 100 排序 | 合计 2.9 秒 |
| 编码轮次数 | 19,606 |
| 编码 token 数（截断后 / 截断前） | 1,567,998 / 1,734,274 |
| 超过 512 token 被截断的索引文本 | 133 条（0.7%），事实在前，截掉的是原文尾部，与官方设置相同 |

与 B04 的 K0 相比，K1 的编码 token 数多约 61%，建索引时间多约 19%。耗时不含模型校验、事实抽取（属于 C 线成本）和官方对照。

记录：[全部验证](results/validation.json)、[索引文本核对](results/k1_text_check.json)、[事实转换](results/facts_preparation.json)、[耗时与成本](results/cost.json)、[运行指纹](results/provenance.json)、[依赖环境](results/environment.txt)、[续跑检查](results/resume_check.txt)、[续跑文件校验](results/resume_hash_check.txt)。作业日志在 `results/logs/`。这些检查只说明检索正确，不构成问答正确率或 K1 是否优于 K0 的结论。
