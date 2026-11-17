# E03：批量回答与断点恢复

当前状态：批量程序及离线检查完成。E02 的预算版 55386 与 top-50 版 55287 已验收。E03 等待服务器重建输入和两段 GPU 验收。

## 服务器 CPU 准备

同一批五道开发题使用 B02 的 K0 候选、2048 Token 历史预算和五种选择策略。直接复用已验收的 E02 作业 55386 的 R 选择记录。MMR/C/Q/FL 由固定 D 提交 `eacd6b2` 重建，沿用其开发权重 0.5，并使用 E02 已验证的固定 Llama 分词器。旧 `inputs/dev5_k0_all_methods.jsonl` 只用于离线验证，旧指纹与服务器不匹配。

在服务器仓库根目录、已激活 `e01` 的终端运行：

```bash
bash E/E03/prepare_server_dev5.sh runs/e03/dev5-k0-inputs
```

这会创建新的输入目录、保留 D 批次记录，并对完整 25 条材料执行严格分词、预算和容量检查。看到 `CPU preflight passed` 后再交 Slurm。若需重跑准备部分，选择新目录，并在后续作业中使用相应输入路径。

当前批次用于 E03 真实验收和 F03 开发评分校准。K1 和 D06 调参属于后续对照实验。F02 仍使用 E02 作业 55386 的归档。

## 本地检查

从仓库根目录运行：

```bash
python -B E/E03/test_e03.py
python E/E03/run_generation.py --input E/E03/inputs/dev5_k0_all_methods.jsonl --schema-only
```

12项离线测试覆盖：真实25条材料重建、正常续跑、技术失败补跑、中断保留、半行修复、完整坏行拒绝、配置变化拒绝、重复及配置标识、并发锁、截断/空输出、未完成导出和重复日志拒绝。GPU生成器在测试中被替代，测试不验证模型推理。

## 服务器验收：先2条，再恢复到25条

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

导出不调用Judge、不推断正确性；保留完整回答和`needs_review`。默认拒绝缺失输入，技术失败、截断和空回答仍以失败状态交给F，不能删掉后计算分母。`--allow-incomplete`只用于明确标注的开发交接。

F 分支已支持 E02 v2 的全文回退。E03 导出继续保持公共字段，F03 按以下步骤核对：

1. 去重/续评使用`(record_id, reader_config_id)`；记录`selection_config_id`、`history_sha256`。同一方法不同权重不能因为题号、策略和config_version相同而被跳过。
2. 保留以上标识至评分结果，证据关联使用原选择记录；调参批次不要仅按题号/策略跨批次拼接。
3. `parse_status=needs_review`时保留完整`raw_output`，不能把空hypothesis当作模型没回答。
4. 用真实25条结果核对计分范围；当前本地测试只验E端导出，未运行F02/F03真实评分。

可先单独为当前单参数25条建评分文件；跨配置复用评分文件之前，F需确认上述标识已接入。

## 接收后续D材料

```bash
python E/E03/prepare_inputs.py \
  --selections path/to/selections.jsonl \
  --turns-dir path/to/A01/public/turns \
  --output path/to/new_reader_inputs.jsonl
```

不覆盖已有输入。输入包含选择配置及其摘要，支持K0/K1和五种策略。正式输入仍须先通过G02冻结；程序默认只接受dev，正式运行需要显式`--stage formal`，这不是绕过项目验收的许可。
