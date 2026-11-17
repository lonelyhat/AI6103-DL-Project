# B05：开发题的事实增强（K1）候选

处理 A01-v2 的 40 道开发题（34 道可回答题，6 道拒答题单独保存），题目与 B03 相同。检索程序、模型和配置都与 B03 的 K0 相同，唯一的区别是每一轮的**索引文本**：

| | 索引文本 | 返回给下游的内容 |
| --- | --- | --- |
| K0（B03） | 用户发言原文 | 完整原始轮次 |
| K1（B05） | `该轮事实用空格连接 + " " + 用户发言原文`；没有事实的轮次只用原文 | 完整原始轮次，定义与 K0 相同 |

拼接方式与官方 `turn-userfact` + `merge` 相同。事实只参与检索，不进入阅读材料，所以 K1 与 K0 的候选排名可以不同，但每个 `turn_id` 指向的内容完全一样。

2026-11-17 实跑完成：作业 `55290` 在 A40 上正常退出（`0:0`），总用时 **19 分 21 秒**（含官方对照）。40 题、4,000 条候选的前 100 顺序与官方 K1 程序**全部一致（40/40）**；完成后续跑会跳过全部 40 题，三个导出文件逐字节不变。

与 B03 的 K0 相比，每题前 100 候选平均有 81.4 条重合（最少 69，最多 93），40 题的排序都有变化。这只说明事实改变了检索结果，K1 是否更好要到 D06 和评分后才能判断。

## 给下游的文件

| 文件（本目录下） | 内容 |
| --- | --- |
| `candidates/dev_K1.jsonl` | 34 道主线可回答题，每题 100 条候选；D06 与 B03 的 `dev_K0.jsonl` 配对使用 |
| `candidates/dev_abstention_K1.jsonl` | 6 道拒答题，单独保存 |
| `candidates/dev_all_K1.jsonl` | 完整 40 题存档 |
| `results/cost.json` | 编码、建索引、检索耗时与 token 数（含截断统计） |

字段与 B03 完全相同，只是 `index` 为 `K1`。问题和原文仍从 `A-数据线/A01/output/public/` 读取，下游读取方式不用改。

## 事实来源

事实来自 C03 交付的 `C03/dev_facts_all40q.json`（SHA-256 见 `results/facts_preparation.json`）。C03 按官方事实缓存格式，以“会话编号_用户消息位置”为键。`prepare_facts.py` 借助 A01 映射表把它转换成本组 `turn_id` → 事实列表，输出 `inputs/dev_facts_by_turn.jsonl`；检索步骤只读这个文件和公开轮次，不接触官方编号。

| 项目 | 数量 |
| --- | --- |
| 40 题全部轮次 | 9,957 |
| 有事实的轮次 | 5,879 |
| 没有事实的轮次（只用原文索引） | 4,078 |
| C03 键被使用 / 未使用 | 9,770 / 0 |

每一轮都必须找到 C03 记录，缺一条程序就停止。C03 中有 2 条值是字符串、2 条列表里含字典，按官方读取方式分别作为单条事实和 `str()` 文本处理，共 4 轮，影响可忽略。

## 实现与复跑

- `prepare_facts.py`：C03 事实转换为 `turn_id` 键，记录覆盖情况。
- `check_k1_text.py`：不用 GPU，从原始数据和 C03 按官方 K1 流程逐题构建索引文本，与本组 K1 文本逐条比较；并检查没有事实的轮次 K1 文本与 K0 逐字相同。
- `../shared/kretrieve.py`：与 B04 共用的检索程序（说明见 B04 README），以 `--index K1 --facts ...` 运行。
- `prepare_official.py`：准备官方 K1 对照所用的程序副本。
- `job_b05.sh`：集群作业，检索 → 续跑检查 → 官方对照 → 验证。

本机准备（在仓库根目录）：

```bash
python3 B-检索线/B05/prepare_facts.py C03/dev_facts_all40q.json \
  --out B-检索线/B05/inputs/dev_facts_by_turn.jsonl \
  --report B-检索线/B05/results/facts_preparation.json
python3 B-检索线/shared/kretrieve.py run --stage dev --index K1 \
  --facts B-检索线/B05/inputs/dev_facts_by_turn.jsonl --validate-inputs
```

集群复用 `~/B02/venv`、`~/B02/stella/`、`~/B02/official/` 和 B03 的私有开发题子集 `~/B03/dev40_longmemeval_s.json`。仓库同步到 `~/B45/repo` 后提交：

```bash
cd ~/B45/repo
sbatch --account=stud --partition=MGPU-TC2 --qos=normal \
  --output="$HOME/B45/B05/logs/%x-%j.out" --error="$HOME/B45/B05/logs/%x-%j.err" \
  B-检索线/B05/job_b05.sh
```

## 验证记录

| 检查 | 结果 |
| --- | --- |
| 候选结构、34/6 拆分与 D01 输入校验 | 40 题全部通过 |
| K1 索引文本与官方 K1 流程逐条比较 | 9,957 轮全部相同 |
| 没有事实的轮次 K1 与 K0 文本比较 | 4,078 轮全部逐字相同 |
| 与官方 K1 程序前 100 顺序比较 | 40/40 完全一致 |
| 完成后续跑 | 跳过全部 40 题，三个文件校验不变 |

**检索消耗**（A40，Stella 分词器计数）：

| 项目 | 数值 |
| --- | --- |
| 模型加载（一次） | 7.6 秒 |
| 建索引：编码 40 题全部“事实 + 原文” | 534.7 秒（平均每题 13.4 秒） |
| 检索：问题编码 + 相似度 + 前 100 排序 | 合计 1.3 秒 |
| 编码轮次数 | 9,957 |
| 编码 token 数（截断后 / 截断前） | 782,872 / 841,149 |
| 超过 512 token 被截断的索引文本 | 59 条（0.6%），事实在前，截掉的是原文尾部，与官方设置相同 |

耗时不含模型校验、事实抽取（属于 C 线成本）和官方对照。

记录：[全部验证](results/validation.json)、[索引文本核对](results/k1_text_check.json)、[事实转换](results/facts_preparation.json)、[耗时与成本](results/cost.json)、[运行指纹](results/provenance.json)、[依赖环境](results/environment.txt)、[续跑检查](results/resume_check.txt)、[续跑文件校验](results/resume_hash_check.txt)。作业日志在 `results/logs/`。这些检查只说明检索正确，不构成问答正确率或 K1 是否优于 K0 的结论。
