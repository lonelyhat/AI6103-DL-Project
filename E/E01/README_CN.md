# E01：回答模型与运行环境验证

**E01 的技术验证已完成。** 作业48880在学校A40上完成一次真实生成，SLURM为 COMPLETED / 0:0；模型配置、输入输出、环境记录、执行后的Notebook均已归档。该题为错误拒答，不能记为答对。见 [验收补充](../../archive/E/E01/ACCEPTANCE_UPDATE_20261117.md)。

- [归档目录](results/job-48880/)：保留当时的文件、路径和日志，不因代码整理而改写。
- [Notebook操作说明](NOTEBOOK_GUIDE_CN.md)：保留用于复核和必要时复跑，当前无需重跑E01。
- [下一步E02](../E02/README.md)：五题真实阅读验证。

## 当前目录与环境

当前代码位于 `E/E01/`。服务器作业脚本使用 `e01` Conda 环境，脚本位于仓库根目录的 `jobs/`，运行输出位于 `runs/e01/`。

输入文件 `input_dev.json` 来自旧DEV题及原文材料；旧Qwen的Token预算不能代替Llama计数。输入清单保留来源和哈希，禁止用参考答案或旧回答代替新模型生成。

## 服务器连接

使用自己的学校账户连接集群，在服务器进入项目根目录。已配置的运行环境可按下列命令激活。

```bash
cd /path/to/AI6103-DL-Project
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01
mytcinfo
```

需要复跑时仍通过 `jobs/e01_tc2.sh` 或 `jobs/e01_notebook_tc2.sh` 提交Slurm作业，不在登录节点运行模型。详细参数见Notebook操作说明。

复跑用的 [开发输入](input_dev.json) 和 [来源清单](input_manifest.json) 已准备好。导入旧 Qwen 归档的工具和早期报告见[历史归档](../../archive/README.md)。
