# E01：回答模型与运行环境验证报告

## 状态与范围

模型访问、GPU 环境和一次真实开发材料生成已获得运行记录。**最终交付待确认 SLURM 作业终态、完整 executed notebook 和原始产物归档。**

本报告基于成员5提供的服务器 `metrics.json`、`config.json`、`environment.json` 和实际回答文本整理；当前尚未将服务器原始结果下载到本地仓库。输入来源与失败诊断另用本地开发材料和历史开发评价记录核对。

本次只验证 E01 的直接回答流程。E02 的 D02 五题材料、多次调用 CoN 阅读与原排名截取核对尚未开展。单条输出不能用于估计模型总体准确率。

## 1. 可追溯位置

| 项目 | 记录 |
| --- | --- |
| 负责人账号 | chunjie001 |
| Git 分支 | e01 |
| 运行代码 commit | `255b2c69eaae9b700b1fb4886a039dbdcdd5eac7` |
| 服务器仓库 | `/home/msai/chunjie001/projects/AI6103-DL-Project` |
| 本地仓库 | `C:\Users\avalon\Desktop\Project\AI6103-DL-Project` |
| 生成作业 | 48880 |
| 作业分区 / QoS | MGPU-TC2 / normal |
| 作业输出目录 | `/home/msai/chunjie001/projects/AI6103-DL-Project/runs/e01/notebook-generate-48880` |
| Notebook 日志 | `logs/e01-nb-48880.out`、`logs/e01-nb-48880.err` |
| 环境记录时间 | 2026-10-29 18:48:09，新加坡时间；对应 UTC 10:48:09 |
| 运行器脚本 SHA256 | `b617e38ff0cb07cfe0fa7b57821524238d722478df770ca98d98b828c832b1e6` |

运行时 Git 状态只有未跟踪的 `logs/` 与 `runs/`，没有已跟踪源文件的未提交变更。
环境记录时间不是 SLURM Submit/Start 或任务完成时间；后者须由 sacct 补充。

## 2. 实际运行环境

| 项目 | 实测 / 记录值 |
| --- | --- |
| 计算节点 | TC2N02 |
| GPU | NVIDIA A40 |
| PyTorch 可见 GPU 总显存 | 44.4326171875 GiB |
| 加载模型前可用显存 | 44.17071533203125 GiB |
| nvidia-smi 总显存 | 46068 MiB，与 PyTorch 报告值不同，分别保留；差异原因未定位 |
| NVIDIA 驱动 | 570.148.08 |
| Python | 3.11.18 |
| PyTorch | 2.6.0+cu124 |
| torch CUDA 运行库 | 12.4 |
| CUDA 可用 | True |
| transformers | 4.51.3 |
| huggingface-hub | 0.30.2 |
| accelerate | 1.6.0 |
| safetensors | 0.5.3 |
| 操作系统 | Linux 5.14.0-503.14.1.el9_5.x86_64，glibc 2.34 |

`nvidia-smi` 显示 CUDA Version 12.8，表示驱动支持信息；本次 PyTorch 使用的 CUDA 运行库实际为 12.4，两者不应混写。
前次探测作业 48855 分配到 L40S，本次生成使用 A40；本次速度与显存结果只归属于本次 A40 作业。

## 3. 模型与生成配置

| 项目 | 配置 |
| --- | --- |
| 模型 | `meta-llama/Llama-3.1-8B-Instruct` |
| 模型 revision | `0e9e39f249a16976918f6564b8830bc894c89659` |
| tokenizer revision | `0e9e39f249a16976918f6564b8830bc894c89659` |
| 精度 | bfloat16 |
| 量化 | 无 |
| Batch size | 1 |
| 解码 | greedy；do_sample=false，num_beams=1 |
| 随机种子 | 42 |
| 最大新增 Token | 512 |
| Attention 实现 | sdpa |
| 设备 | cuda:0；没有 CPU offload |
| 阅读方式 | 原始上下文直接回答；E02 的官方多次 CoN 调用待核对 |

模型文件在提交前已预下载；生成作业启用了离线缓存模式。本报告未取得独立的模型下载耗时，保留为未记录。

## 4. 真实开发输入

题号：`1cea1afa`；问题日期：2023/06/14 13:43。

问题：

> How many Instagram followers do I currently have?

输入来自已经使用的旧 DEV 阅读材料，含 6 个完整原文轮次、12 条消息。生成输入未包含参考答案、证据标签或旧实验的最终回答；原始历史对话中的助手发言照常保留。

| 输入身份 | SHA256 |
| --- | --- |
| 本次服务器原始输入文件 | `f6a91f1b44ad58a34aa37a70937f47d6ad49794565dc1edc1ae99cae2958399c` |
| 跨平台规范化 JSON | `a723966152338686ff93bbfe8ad9c8ae42781f7724a655090c2c8e3c748e8341` |

本地 Windows 文件的原始字节哈希与服务器不同，核对发现：将本地 CRLF 转为 LF 后，哈希恰好等于服务器记录；这是 Git 换行转换，输入 JSON 内容一致。

历史上下文实测 1949 个 Llama Token，最终聊天模板后的完整输入为 2056 Token。旧材料的 2048 Token 配置使用 Qwen tokenizer，本次没有直接沿用该计数。本次单题也不能据此固定后续所有材料的正式预算。

完整 prompt：`generation/prompt.txt`；原始输入：`generation/input.json`；精确 Token ID：`generation/token_ids.json`。

## 5. 真实输出与诊断

原始回答完整保留：

> I do not know based on the provided history.

输出非空，未达到输出上限；技术上已生成成功。**但本条回答是错误拒答，不能记为答对。**

评价侧核对（本节不回填给生成模型）：

- `m00013`，2023/05/27 07:39，用户曾提到达到 500 个粉丝。
- 较新的 `m00232`，2023/05/28 22:57，用户明确写道：`I'm now at 600 followers`。
- 历史 DEV 评价记录的参考答案为 `600`。

因此本次应记录为“当前输入已包含相关证据，但模型仍拒答”的开发失败案例。具体是时间推断、提示词理解或其他阅读因素导致，尚未定位，不应将其直接归因为硬件、量化或某种选择策略。

本次不更改原始输入、提示词、测量或回答来掩盖该失败。后续阅读流程诊断使用新的开发运行记录，并保留独立配置身份。正式评分流程仍由后续任务校准。

## 6. Token、耗时与显存

| 指标 | 实测值 |
| --- | ---: |
| 完整输入 Token | 2056 |
| 其中历史上下文 Token | 1949 |
| 输出 Token，含停止符 | 11 |
| tokenizer / 模型加载与初始化 | 108.634431 秒 |
| 独立 warmup | 3.050567 秒 |
| 真实生成，含输入预填充 | 0.806000 秒 |
| 输出 Token / 真实生成秒数 | 13.647641 Token/秒 |
| 测量窗口峰值 allocated 显存 | 15.444947 GiB |
| 测量窗口峰值 reserved 显存 | 15.542969 GiB |
| hit_output_limit | false |
| nonempty_output | true |
| 运行器 status | generated |

真实生成计时前后均进行 CUDA 同步；吞吐量包含输入 prefill，不能称为纯解码吞吐量。
单条短回答只有 11 个输出 Token，不能直接外推长回答、批处理或 E02 CoN 流程的速度。
峰值显存统计在 warmup 之后重置，是测量窗口的峰值；不代表包含模型加载阶段在内的全作业峰值。
独立下载时间、排队时间、总作业耗时尚未取得，不用上述几个计时项相加冒充作业总时间。

## 7. 已处理问题与剩余交付

前次作业 48878 在 Conda 激活时失败：学校 Qt hook 读取未定义的 `QT_XCB_GL_INTEGRATION`，与过早启用 `set -u` 冲突。已改为激活环境后再启用 nounset，重新提交为 48880。保留失败日志以追溯修复过程。

- [x] 模型权限与访问已用于真实加载。
- [x] 已取得实际 GPU、软件环境和锁定配置。
- [x] 已取得真实输入输出、Token、生成耗时和显存记录。
- [x] 已核对输出非空、没有触及上限，并如实记录错误拒答。
- [ ] 用 sacct 确认 48880 的最终 State、ExitCode、Submit、Start、Elapsed。
- [ ] 确认 `executed.ipynb` 与运行目录的 `REPORT_CN.md` 已生成，notebook 后续单元没有失败。
- [ ] 将原始产物、SLURM 日志与 accounting 记录归档到组员可访问的位置。
- [ ] 提交本报告与产物位置给全员。

以上剩余项完成后，本次具备 E01 所列的完整交付证据。E01 验证可运行性与记录完整性，本报告不声称回答质量已达标，也不代替 E02/F02。
