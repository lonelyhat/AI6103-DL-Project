# E01 实验记录：Slurm Job 48880

## 目的与范围
验证回答模型和 GPU 运行环境，使用已有 DEV 材料完成一次真实生成，
记录配置、输入输出、Token、耗时和显存。
本次采用直接回答流程，尚未执行 E02 的正式多次调用 CoN。

## 运行状态
- 分支：e01
- 运行代码 commit：255b2c69eaae9b700b1fb4886a039dbdcdd5eac7
- Slurm 作业：48880
- 状态：COMPLETED；退出码：0:0
- Submit / Start：2026-10-29 18:47:35（集群显示时间）
- 总作业耗时：00:02:29
- 节点 / GPU：TC2N02 / NVIDIA A40

## 模型与配置
- 模型：meta-llama/Llama-3.1-8B-Instruct
- 模型与 tokenizer revision：0e9e39f249a16976918f6564b8830bc894c89659
- BF16，无量化，batch size 1
- Greedy 解码，max_new_tokens=512，seed=42
- 完整配置及环境见 generation/config.json 和 generation/environment.json

## 输入与输出
- DEV 题号：1cea1afa
- 问题：How many Instagram followers do I currently have?
- 实际回答：I do not know based on the provided history.
- 人工核对：输入包含较新的 600 followers 记录，开发参考答案为 600。
- 本题结果：错误拒答；具体原因尚未通过对照实验定位。
- 生成成功不代表回答正确；参考答案仅用于评价，不作为生成输入。

## 实测指标
- 完整输入：2056 Token；其中历史上下文：1949 Token
- 输出：11 Token（含停止符）
- 加载初始化：108.634431 秒
- 独立预热：3.050567 秒
- 生成：0.806000 秒（含输入预填充）
- 测量窗口峰值 allocated 显存：15.444947 GiB
- 未触及输出长度上限

## 结论与限制
E01 的模型访问、GPU 环境和真实生成流程验证成功。
这是一条开发运行记录，不能用于估计总体准确率、比较选择策略，
或直接推算正式 CoN 批量实验耗时。

## 文件
- executed.ipynb：执行后的 notebook
- REPORT_CN.md：运行时自动生成的报告
- generation/：实际输入、提示词、回答、配置和测量记录
- logs/：本次作业标准输出及错误日志
- slurm_final.txt：作业最终状态
