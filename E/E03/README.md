# E03：批量回答与断点恢复

E03 批量生成与恢复已完成真实 GPU 验收。A40 作业 55392 写入 2 条后退出，55399 在同目录续跑至 25 条。两次 SLURM 状态均为 COMPLETED，最终 25 条全为 generated。见 [运行摘要](results/dev5-k0-v1/summary.json)、[调用记录](results/dev5-k0-v1/invocations.jsonl)和 [SLURM 终态](results/dev5-k0-v1/slurm_final.txt)。正式批次沿用本程序，见 [E04](../E04/README.md)。

## 重建开发批次输入

同一批五道开发题使用 B02 的 K0 候选、2048 Token 历史预算和五种选择策略。直接复用已验收的 E02 作业 55386 的 R 选择记录。MMR/C/Q/FL 由固定 D 提交 `eacd6b2` 重建，沿用其开发权重 0.5，并使用 E02 已验证的固定 Llama 分词器。旧 `inputs/dev5_k0_all_methods.jsonl` 只用于离线验证，旧指纹与服务器不匹配。

在服务器仓库根目录、已激活 `e01` 的终端运行：

```bash
bash E/E03/prepare_server_dev5.sh runs/e03/dev5-k0-inputs
```

这会创建新的输入目录、保留 D 批次记录，并对完整 25 条材料执行严格分词、预算和容量检查。看到 `CPU preflight passed` 后再交 Slurm。若需重跑准备部分，选择新目录，并在后续作业中使用相应输入路径。

这批 25 条回答用于 E03 验收及 F03 开发校准。D06 调参和 E04 正式实验使用各自的输入。F02 采用 E02 作业 55386 的预算版归档。

## 本地检查

从仓库根目录运行：

```bash
python -B E/E03/test_e03.py
python E/E03/run_generation.py --input E/E03/results/dev5-k0-v1/inputs.jsonl --schema-only
```

12项离线测试覆盖：真实25条材料重建、正常续跑、技术失败补跑、中断保留、半行修复、完整坏行拒绝、配置变化拒绝、重复及配置标识、并发锁、截断/空输出、未完成导出和重复日志拒绝。GPU生成器在测试中被替代，测试不验证模型推理。

## 复跑开发恢复验证

必须先通过上面的`--check-only`。输出目录用固定名称，不能用每次不同的作业号作为恢复目标。

```bash
mkdir -p logs
sbatch --partition=MGPU-TC2 --qos=normal \
  jobs/e03_tc2.sh runs/e03/dev5-k0-inputs/dev5_k0_all_methods.jsonl \
  runs/e03/dev5-k0-v1 --stop-after 2
```

等待该作业结束，确认`summary.json`显示`recorded=2`、`missing=23`且没有失败，再提交：

```bash
sbatch --partition=MGPU-TC2 --qos=normal \
  jobs/e03_tc2.sh runs/e03/dev5-k0-inputs/dev5_k0_all_methods.jsonl \
  runs/e03/dev5-k0-v1 --resume
```

恢复后应有25条唯一结果、25条尝试（无技术失败时），前2条的原始记录保持不变。再次执行同一恢复命令会跳过全部完成项，不加载模型权重。计划停在2条的第一项作业即使退出码为0，也不表示25条已完成。

技术失败写入日志后退出；修复环境后使用同一命令`--resume`重试。截断/空回答保留为相应状态，不自动重复采样。若决定改变输出上限、模型、运行库或其他配置，必须用新目录并记录原因，不能选择性替换旧回答。

强制终止/SIGKILL可能留下`.writer.lock`。先通过`squeue`/`sacct`确认锁中作业已结束且无其他进程写同一目录，再移走该锁并恢复；运行器不会自动抢锁。只修复没有换行提交标记的末尾半行，并保留`attempts.partial-*.bin`；完整坏行要求人工排查。

## 产物与F交接

开发归档的实际输入统一使用 [inputs.jsonl](results/dev5-k0-v1/inputs.jsonl)。分词器诊断工具见 [diagnose_tokenizer.py](diagnose_tokenizer.py)。

- `inputs.jsonl`：实际输入快照。
- `config.json`：输入、代码、模型、分词器、提示词、运行库和生成参数标识；恢复要求完全一致。
- `attempts.jsonl`：逐条刷盘的全部尝试，含技术失败；计算补跑成本时保留此文件。
- `results.jsonl`：每个输入最后一次尝试，按输入顺序导出，无重试重复条目。
- `summary.json`：期望数、缺失数、状态和待审数；`all_generated`不代表正确率合格。
- `runtime.jsonl`与`invocations.jsonl`：模型加载、预热、设备、作业及调用记录。

```bash
python E/E03/export_for_f.py --run-dir runs/e03/dev5-k0-v1 \
  --output runs/e03/dev5-k0-v1/answers_for_f.jsonl
```

导出不调用Judge、不推断正确性；保留完整回答和`needs_review`。默认拒绝缺失输入，技术失败、截断和空回答均保留原始状态，正式评分按 G02 口径处理。`--allow-incomplete`只用于明确标注的开发交接。

F 分支已支持 E02 v2 的全文回退。E03 导出继续保持公共字段，F03 按以下步骤核对：

1. 去重/续评使用`(record_id, reader_config_id)`；记录`selection_config_id`、`history_sha256`。同一方法不同权重不能因为题号、策略和config_version相同而被跳过。
2. 保留以上标识至评分结果，证据关联使用原选择记录；调参批次不要仅按题号/策略跨批次拼接。
3. `parse_status=needs_review`时保留完整`raw_output`，不能把空hypothesis当作模型没回答。
4. 本地离线测试可检查导出和恢复。F03 实际开发校准的计分范围见 [F 评分配置](../../F/SCORING_CONFIG.md)。

## 接收后续D材料

```bash
python E/E03/prepare_inputs.py \
  --selections path/to/selections.jsonl \
  --turns-dir path/to/A01/public/turns \
  --output path/to/new_reader_inputs.jsonl
```

不覆盖已有输入。输入包含选择配置及其摘要，支持K0/K1和五种策略。开发批次默认使用 `dev`。正式批次使用 [D08 已冻结的打包输入](../../D/D08/delivery/)以及 `--stage formal`。
