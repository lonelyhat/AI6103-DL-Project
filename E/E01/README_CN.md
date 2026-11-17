# E01：回答模型与运行环境验证

**E01 的技术验证已完成。** 作业48880在学校A40上完成一次真实生成，SLURM为 COMPLETED / 0:0；模型配置、输入输出、环境记录、执行后的Notebook均已归档。该题为错误拒答，不能记为答对。见 [验收补充](ACCEPTANCE_UPDATE_20261117.md)。

- [归档目录](results/job-48880/)：保留当时的文件、路径和日志，不因代码整理而改写。
- [历史分析报告](REPORT_CN.md)：早期“待归档”和CoN说明由验收补充更正。
- [Notebook操作说明](NOTEBOOK_GUIDE_CN.md)：保留用于复核和必要时复跑，当前无需重跑E01。
- [下一步E02](../E02/README.md)：五题真实阅读验证。

## 当前目录与环境

代码从仓库根目录 `e01/` 移至 `E/E01/`。Git分支和Conda环境仍为 `e01`，作业脚本仍在 `jobs/`，输出仍在 `runs/e01/`。

输入文件 `input_dev.json` 来自旧DEV题及原文材料；旧Qwen的Token预算不能代替Llama计数。输入清单保留来源和哈希，禁止用参考答案或旧回答代替新模型生成。

## 服务器连接

校外先连接学校VPN，再在Windows PowerShell执行：

```powershell
Test-NetConnection 10.96.189.12 -Port 22
ssh chunjie001@10.96.189.12
```

TC2地址来自项目留存的学校手册，若学校更新地址以最新通知为准。VPN入口域名与TC2的SSH地址用途不同。连接后进入已有项目：

```bash
cd /home/msai/chunjie001/projects/AI6103-DL-Project
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01
mytcinfo
```

需要复跑时仍通过 `jobs/e01_tc2.sh` 或 `jobs/e01_notebook_tc2.sh` 提交Slurm作业，不在登录节点运行模型。详细参数见Notebook操作说明。

`prepare_input.py` 是旧归档导出工具。现有输入已经准备好，通常无需再次调用；如确需重建，在仓库根目录显式提供实际归档路径：

```bash
python E/E01/prepare_input.py --archive /path/to/baseline_results.zip --output E/E01/another_dev.json
```

工具不会覆盖已有输出。旧归档不要求为了重跑现有输入而重新上传到服务器。
