# E：回答模型与生成

成员5（Noir / 张纯洁）。E01、E02 统一放在本目录；作业启动脚本仍在仓库根目录 `jobs/`，Git分支和 Conda 环境仍叫 `e01`。

| 任务 | 入口 | 当前状态 |
|---|---|---|
| E01：环境与一次真实生成 | [E01/README_CN.md](E01/README_CN.md) | 已有真实运行和归档；见验收补充。单题错误拒答不代表生成失败，也不代表模型效果合格 |
| E02：五题阅读验证 | [E02/README.md](E02/README.md) | 预算版 55386 与 top-50 版 55287 均已生成并通过归档核对 |
| E→F 交接 | [E02/README.md](E02/README.md) | 预算版回答和对应的重建 D02 选择记录已归档，待 F02 评分和统计证据 |

## 从仓库根目录运行

```bash
python E/E02/run_generation.py --input E/E02/inputs/dev5.jsonl --schema-only
python -B E/E02/test_e02.py
```

学校服务器沿用已有 e01 环境，输入检查通过后提交：

```bash
python E/E02/run_generation.py --input E/E02/results/job-55386/dev5_budget.jsonl --check-only &&
sbatch --partition=MGPU-TC2 --qos=normal jobs/e02_tc2.sh E/E02/results/job-55386/dev5_budget.jsonl
```

参照版使用 `E/E02/inputs/dev5_topk.jsonl`，也先执行 `--check-only`。完整步骤在 E02 README。

## 目录迁移说明（2026-11-17）

- 原 `e01/` → `E/E01/`；原 `e02/` → `E/E02/`。
- Python默认路径、Notebook源文件、测试、当前操作说明和三个作业脚本已同步更新。
- E01 `results/job-48880/` 归档及历史报告、输入来源清单保持原始内容；其中旧路径是当时的运行记录，不应批量改写。
- 已有服务器产物路径 `runs/e01/`、`runs/e02/` 和日志路径保持可用。
- 本次仅整理本地文件；未commit、push、合并其他分支或执行服务器任务。
