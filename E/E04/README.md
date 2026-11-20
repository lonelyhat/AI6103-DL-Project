# E04：正式生成与交付

E04 使用 [G02 冻结配置](../../G/G02/plan.json) 和 [D08 八批输入](../../D/D08/delivery/manifest.json)，每批 10 题 × 10 种设置。正式生成归档为 **800 条**，其中 786 条正常生成、14 条达到输出上限，空答和技术失败均为 0。F04 按实际输出为 800 条逐条评分。完整结果链见 [G03 验收](../../G/G03/README.md)。

## 代码和环境

| 内容 | 入口 |
| --- | --- |
| 批量生成与续跑 | [E03/run_generation.py](../E03/run_generation.py) · [E03/batch.py](../E03/batch.py) |
| Slurm 启动 | [jobs/e03_tc2.sh](../../jobs/e03_tc2.sh) |
| 送评导出 | [E03/export_for_f.py](../E03/export_for_f.py) |
| Python 依赖 | [E01/requirements.txt](../E01/requirements.txt) |
| 模型、分词器与提示 | [E02 阅读器](../E02/run_generation.py) · [G02 冻结配置](../../G/G02/plan.json) |

归档的正式环境使用 Python 3.11.18、PyTorch 2.6.0+cu124、Transformers 4.51.3。PyTorch 的 CUDA 版本需与集群驱动匹配，其余生成依赖由 E01 的清单安装。Slurm 启动脚本激活 `e01` 环境；复跑者可在自己的账户下配置同名环境。

在该环境的 Hugging Face 缓存中准备模型 `meta-llama/Llama-3.1-8B-Instruct` 的固定 revision `0e9e39f249a16976918f6564b8830bc894c89659`，包括权重、分词器、chat template 和模型配置。运行器从本地缓存读取。正式设置使用 BF16、greedy 解码、批大小 1、最多生成 800 Token。2048 Token 是 D08 选材的历史正文预算，完整提示另行计数。

## 复跑一个正式批次

在学校集群上，从项目根目录执行。先激活运行环境，再解包原始 D08 输入，依次通过结构检查和 CPU 分词检查。GPU 作业通过 Slurm 提交。以下以 `batch-01` 为例，复跑其他批次时同步替换输入包、输入目录和输出目录。输出目录使用新的批次路径，便于保留原实验记录。

~~~bash
conda activate e01
mkdir -p logs runs/e04

input_dir=runs/e04/d08-batch-01
output_dir=runs/e04/reproduction/batch-01/reader
python -m zipfile -e D/D08/delivery/D08_g02-v1_batch-01.zip "$input_dir"
input="$input_dir/reader_inputs.jsonl"

python E/E03/run_generation.py --input "$input" --stage formal --schema-only &&
python E/E03/run_generation.py --input "$input" --stage formal --check-only &&
sbatch --partition=MGPU-TC2 --qos=normal --job-name=e04-b01 \
  jobs/e03_tc2.sh "$input" "$output_dir" --stage formal
~~~

作业结束后查看输出目录的 `summary.json`、`results.jsonl` 及 Slurm 日志。出现截断或空输出时，程序在写完记录后以非零状态退出；以 `recorded`、`missing` 和逐条状态核实完成度。需恢复缺失或技术失败项时，在相同配置、输入和输出目录下为 Slurm 命令增加 `--resume`。截断及空输出保留原状态。

完整运行的送评导出示例：

~~~bash
python E/E03/export_for_f.py --run-dir "$output_dir" \
  --output "$output_dir/answers_for_f.jsonl"
~~~

## 读取已发布的结果

正式归档位于 `e04-results` 的固定提交 [95438df](https://github.com/lonelyhat/AI6103-DL-Project/tree/95438df71b0730d58ab260d97f4528e3b3228e72/E/E04/results/g02-v1)。如需在本地检查，在 Git 克隆的项目根目录执行：

~~~bash
git fetch origin e04-results
mkdir -p runs/e04/archive
git -c core.autocrlf=false archive --format=tar --output=runs/e04/g02-v1.tar \
  95438df71b0730d58ab260d97f4528e3b3228e72 E/E04/results/g02-v1
tar -xf runs/e04/g02-v1.tar -C runs/e04/archive
~~~

导出文件位于 `runs/e04/archive/E/E04/results/g02-v1/`。八批都有原始回答 `results.jsonl`、送评 `answers_for_f.jsonl`、`config.json` 和 `summary.json`。只有首批在 Git 中保存了完整运行日志与尝试账本。可从 [D08](../../D/D08/delivery/) 恢复其余批次的输入，并按配置中的输入指纹核对。第 7 批使用 L40S，其余批次使用 A40。

获取固定 Git 提交后，可在 CPU 上运行 `python -B G/G03/audit.py`，核对归档回答、实际送评文字、评分和证据。使用源代码 ZIP 时，也可从上方固定提交链接取得结果。
