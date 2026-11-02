# B03：全部开发题的 K0 候选

处理 A01-v2 的 40 道开发题：34 道可回答题、6 道拒答题。检索沿用 B02 的 Stella 编码函数：仅编码历史用户发言，与当前问题比较；命中编号对应完整原始轮次。K0 不加入抽取事实。本次不做材料选择、回答或评分。


2026-11-02 实跑完成：作业 `50064` 在 A40 上正常退出（`0:0`），总用时 **15 分 54 秒**。全部 40 题、4,000 条候选的前 100 顺序均与官方一致；B02 五题的排名和数值分数完全不变。真实完成后续跑跳过全部 40 题，三个导出文件逐字节不变。

## 给下游的文件

| 文件（本目录下） | 内容 |
| --- | --- |
| `candidates/dev_K0.jsonl` | 34 道主线可回答题，每题 100 条候选；D06 优先使用此文件 |
| `candidates/dev_abstention_K0.jsonl` | 6 道拒答题，单独保存，不混入主线 |
| `candidates/dev_all_K0.jsonl` | 完整 40 题存档 |

每题一行，字段与 B02 一致，包含 A01 公共字段和 `candidates: [{turn_id, rank, score}]`。`score` 是相似度，不是正确概率。2048 token 是后续历史阅读预算，不是在检索阶段截断候选的预算。

问题和原文仍从仓库 `A-数据线/A01/output/public/` 读取：`dev_questions.jsonl` 提供问题，`turns/{question_id}.jsonl` 提供完整原始轮次。本次沿用 A01 的 `public_turns()` 补齐其余 35 题，原先五题文件未修改。选择/回答程序不读取 `map/`、`eval/` 和官方检索日志。

## 实现与复跑

- `prepare_inputs.py`：验证原始数据 SHA-256，调用 A01 原函数生成缺失公开轮次；已有文件若不一致则停止，不覆盖。原始标签只进入被忽略的官方对照子集。
- `retrieve_dev.py`：复用 B02 的模型加载/编码方式，逐题原子保存 checkpoint；结果完整后才导出三个候选文件。
- checkpoint 绑定公开输入、模型实际校验值、检索配置、软件/GPU 和代码指纹。配置不同则拒绝续跑；同一目录用文件锁阻止并发覆盖。
- `validate_results.py`：检查 40 题候选、34/6 拆分、D01 输入和原文映射；用仅限核验的 A01 map 转换官方 ID，比较官方前 100 顺序，并回归核对 B02 五题。

本机准备输入（在仓库根目录；完整数据路径按实际位置填写）：

```bash
python3 B-检索线/B03/prepare_inputs.py /path/to/longmemeval_s_cleaned.json \
  --official-subset B-检索线/B03/.private/dev40_longmemeval_s.json \
  --report B-检索线/B03/results/input_preparation.json
python3 B-检索线/B03/test_resume.py
python3 B-检索线/B03/retrieve_dev.py --validate-inputs
```

本次集群复用 `~/B02/venv`、`~/B02/stella/`、`~/B02/official/` 和 `~/B02/repo/`。先将公开轮次与 B03 代码同步到仓库，将私有官方子集上传到 `~/B03/dev40_longmemeval_s.json`，创建 `~/B03/logs`、`~/B03/results`，再提交：

```bash
cd ~/B02/repo
sbatch --account=stud --partition=MGPU-TC2 --qos=normal \
  --output="$HOME/B03/logs/b03-%j.out" --error="$HOME/B03/logs/b03-%j.err" \
  B-检索线/B03/job_b03.sh
```

作业先检索全部 40 题，再检查完成后续跑，最后运行官方程序和验证。中断后重提同一作业，会从 checkpoint 继续本组检索；官方对照部分仍会整批重跑。已完成候选不会因此重新编码。若输入、模型、配置、源码或 GPU/软件变化，应保留原结果并使用新的输出目录。

## 验证记录

中断后仅补跑未完成题、指纹不一致拒绝续跑、部分结果不能替换完整交付这三项故障恢复测试已通过。记录：[全部验证](results/validation.json)、[运行摘要及指纹](results/run_manifest.json)、[逐题耗时](results/timings.json)、[输入准备](results/input_preparation.json)、[依赖环境](results/environment.txt)、[续跑检查](results/resume_check.txt)、[续跑文件校验](results/resume_hash_check.txt)。作业日志在 `results/logs/`。本组 40 题检索合计约 440.11 秒，不含模型加载、完整性检查和官方对照；这些检查不构成问答正确率或证据齐全结论。
