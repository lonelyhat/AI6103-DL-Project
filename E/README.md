# E 线：长对话问答的阅读与生成

本目录负责把 D 线选中的原始对话轮次转换为阅读输入，调用固定版本的 Llama 3.1 8B Instruct 生成回答，并向 F 线导出原文、提取答案、状态和配置指纹。正式实验 E04 复用 E03 的批量程序。

| 阶段 | 代码入口 | 验证与归档 |
| --- | --- | --- |
| [E01 环境与单题验证](E01/README_CN.md) | [生成脚本](E01/run_generation.py)、[Notebook](E01/E01_environment_and_generation.ipynb) | [GPU 作业 48880](E01/results/job-48880/README.md) |
| [E02 阅读方式验证](E02/README.md) | [输入准备](E02/prepare_inputs.py)、[阅读与生成](E02/run_generation.py)、[F 导出](E02/export_for_f.py) | [预算版 55386](E02/results/job-55386/)和[排名前 50 参照版 55287](E02/results/job-55287/)，各五题 |
| [E03 批量与恢复](E03/README.md) | [输入准备](E03/prepare_inputs.py)、[批量生成](E03/run_generation.py)、[运行日志与恢复](E03/batch.py)、[F 导出](E03/export_for_f.py) | [开发批次结果](E03/results/dev5-k0-v1/summary.json)，A40 作业 55392 启动，55399 恢复至 25 条 |
| [E04 正式生成](E04/README.md) | [E03 的正式运行模式](E03/run_generation.py)、[Slurm 启动脚本](../jobs/e03_tc2.sh) | `g02-v1` 的 8 批、800 条原始回答及送评文件，发布在 `e04-results` |

## 提交代码时保留的路径

以项目仓库根目录为提交和运行目录。`E/` 中的 Python 源码、Notebook、依赖清单、测试及输入样例按任务归位。重建 E02/E03 输入和运行完整的 E→F 离线测试还依赖同一仓库的 `D/`、`A-数据线/` 和 `F/`；学校 Slurm 的启动脚本集中在根目录的 [jobs](../jobs/)。`inputs/` 保存标准输入和开发样例，`results/` 保存原始运行证据，早期导入工具和已合入的补丁见[历史归档](../archive/README.md)。

提交代码使用仓库中的源文件、依赖清单和必要的样例。模型权重由运行者使用有权限的 Hugging Face 账户取得，令牌保存在运行环境。运行时新生成的文件放在 `runs/` 和 `logs/`。

## 从仓库根目录离线检查

以下命令使用 Python 3.10 或以上。结构校验和离线测试可在 CPU 上运行，无需模型缓存或 API 调用。

~~~bash
python -B E/E02/run_generation.py --input E/E02/inputs/dev5.jsonl --schema-only
python -B E/E02/test_e02.py
python -B E/E03/run_generation.py --input E/E03/results/dev5-k0-v1/inputs.jsonl --schema-only
python -B E/E03/test_e03.py
~~~

E02 与 E03 的参数说明见各自 README。正式运行的环境、解包、Slurm 提交及结果归档见 [E04](E04/README.md)。
