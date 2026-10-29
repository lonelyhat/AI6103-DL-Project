# E01：分支、TC2 连接与一次真实生成

依据本地 `TASK_BOARD.md` 的 E01 和 `PROJECT_PLAN.md`，2026-10-29 编写。
尚未登录学校服务器、创建远程分支或运行真实 GPU 生成。脚本的本地检查不能代替 E01 实验。
GitHub 在本次环境中无法访问，远程 main 与本地材料的一致性尚未核实。

## 1. 本周的交付范围

E01 要验证 `meta-llama/Llama-3.1-8B-Instruct` 的访问、GPU 环境和一次真实开发输入的生成，交出模型 commit SHA、运行配置、完整输入输出、输入/输出 Token、耗时与保存位置。

这里复用旧归档中**已使用的 DEV 题与选中原文**，重新用 Llama 实际生成。
不会把旧 Qwen 输出当作新结果。旧材料的 2048 Token 用旧 Qwen tokenizer 计量，脚本会重新记录 Llama 的实际长度，不声称符合本轮 2048 Token 预算。

此脚本使用直接回答来验证 E01。原论文逐块笔记提取、再汇总回答的多次 CoN 调用留到 E02 接 D02 时核对；一次提示词中的“先整理再回答”也不能等同于官方 CoN。E01 不需要等待五种选择器、事实增强、评分或 800 条正式回答。

## 2. Windows：克隆并建分支

当前 `C:\Users\avalon\Desktop\DL project` 没有 `.git`，是项目材料目录。保留它，在内部克隆一个真正的 Git 工作目录。以下在 **Windows PowerShell** 执行，命令成功后才执行下一步：

```powershell
Set-Location 'C:\Users\avalon\Desktop\DL project'
git clone https://github.com/lonelyhat/AI6103-DL-Project.git AI6103-DL-Project
Set-Location '.\AI6103-DL-Project'
git fetch origin
git switch -c member5/e01-reader-env origin/main
git status --short --branch
```

如果你已有别处的正式 clone，就直接进入那个目录，先用 `git status` 确认自己的改动，再从 `origin/main` 建分支。不要在材料目录执行 `git init` 来代替 clone。

复制本次新增的运行工具到 clone，再核对远程的任务说明和归档文件是否仍存在：

```powershell
Copy-Item -LiteralPath '..\e01' -Destination '.\e01' -Recurse
Copy-Item -LiteralPath '..\jobs\e01_tc2.sh' -Destination '.\jobs\e01_tc2.sh'
git diff --stat
git status --short
git add e01 jobs/e01_tc2.sh
git commit -m "Add member 5 E01 reader environment smoke test"
git push -u origin member5/e01-reader-env
```

如果目标已有同名工具，先比较文件，再合并；不要直接覆盖队友的新改动。`git diff` 默认不显示未跟踪文件，新增文件以 `git status` 为准。
push 若无权限，需要维护者赋予仓库写权限，或按团队流程使用 fork/PR。

## 3. 连接学校 TC2

本地学校手册为 2025-08-13 版：校外先连接 NTU VPN；TC2 地址为 `10.96.189.12`，端口 22，使用小写 NTU network account ID。以学校最新通知和实际可访问地址为准。

在 **Windows PowerShell** 中，将 `your_ntu_id` 换成自己的账号：

```powershell
Test-NetConnection 10.96.189.12 -Port 22
ssh your_ntu_id@10.96.189.12
```

密码只在 SSH 提示中输入。登录后先执行以下 **服务器 Bash** 命令：

```bash
pwd
mytcinfo
sacctmgr show user "$USER" withassoc format=user,account,partition,qos
scontrol show partition
module avail
```

手册中的示例是 `MGPU-TC2` 和 `normal`，需要查询确认自己确实能用。CPU、RAM、GPU 数量和最长时间也以你自己的 QoS 为准。`--mem` 是主机内存，不是显卡显存。

登录节点负责文件、环境准备和提交作业。不要在那里运行回答模型或 `nvidia-smi`；手册要求非交互作业通过 `sbatch` 进入计算节点。

## 4. 服务器取代码、创建环境并探测 GPU

以下都在 **服务器 Bash**，路径与 Windows 本地互相独立：

```bash
mkdir -p ~/projects
cd ~/projects
git clone --branch member5/e01-reader-env --single-branch https://github.com/lonelyhat/AI6103-DL-Project.git
cd AI6103-DL-Project
mkdir -p logs runs/e01
module load anaconda
eval "$(conda shell.bash hook)"
conda create -n e01 python=3.11 pip -y
conda activate e01
```

若该 clone 已存在，进入它，确认 `git status` 干净后 `git fetch origin`、切换该分支并 `git pull --ff-only`；不要重复 clone。若服务器无法连 GitHub，可在 Windows 将已提交的分支打包：

```powershell
git bundle create e01.bundle member5/e01-reader-env
scp .\e01.bundle your_ntu_id@10.96.189.12:~/
```

然后服务器执行 `git clone -b member5/e01-reader-env ~/e01.bundle ~/projects/AI6103-DL-Project`。
bundle 路线的 origin 指向本地 bundle；需要 push 时在服务器重新设置 GitHub remote，或将结果下载回 Windows 后再提交。

先提交已有探测脚本。以下分区/QoS 与资源只是示例，按查询结果修改：

```bash
sbatch --partition=MGPU-TC2 --qos=normal --nodes=1 --ntasks=1 \
  --cpus-per-task=1 --gres=gpu:1 --mem=2G --time=00:05:00 \
  --output=logs/probe-%j.out --error=logs/probe-%j.err \
  --wrap='module load anaconda; eval "$(conda shell.bash hook)"; conda activate e01; bash jobs/probe_tc2.sh'
squeue -u "$USER"
```

读取返回 job ID 对应的 `logs/probe-JOBID.out`，确认 GPU 名称、显存和驱动。探测阶段 torch 未安装是正常的。

建议先用单卡、batch=1、无量化的 BF16；显存需要容纳约 16GB 权重及运行开销，24GB 以上可作为短输入试跑起点，仍需实测，40GB 更宽裕。
若分配到较小显卡，先查看可申请的 GPU 资源或向管理员确认。不要用 CPU offload 后仍把速度写成纯 GPU 测量；脚本固定把全部权重放在一张 GPU 上。

根据探测到的驱动与硬件选择 PyTorch wheel。以下是官方提供的固定版本安装示例，仅在其 CUDA 12.4 构建支持该节点 GPU/驱动时执行；更新架构或不同驱动应选兼容构建并记录版本：

```bash
conda activate e01
python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
python -m pip install -r e01/requirements.txt
python -m pip check
```

选择依据：<https://pytorch.org/get-started/previous-versions/>。
不要仅根据系统 `nvcc` 版本选择 wheel；PyTorch 自带 CUDA 运行库还需要与节点驱动及 GPU 架构匹配。安装到自己的 e01 环境，不需要 sudo。

## 5. 取得模型权限、准备真实 DEV 输入

在 Hugging Face 网页登录自己的账号，申请并取得模型访问权限：
<https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct>。
模型页要求同意许可并共享账号信息，申请是否通过以该账号实际状态为准。

在服务器准备好访问令牌后执行交互式登录；不要把令牌写进脚本或 Git：

```bash
conda activate e01
huggingface-cli login
test -f e01/input_dev.json || python e01/prepare_input.py
```

本次已准备好 `e01/input_dev.json`，上述命令会保留它；文件缺失时才从旧归档导出 DEV `1cea1afa` 的问题、日期和原文上下文。也可用 `--question-id DEV_ID --output e01/another_dev.json` 指定旧 DEV；非 DEV 会被拒绝，已存在的输入不会被覆盖。
如果远程仓库没有该 ZIP，把本地 `artifacts/raw/baseline_v1/baseline_v1_20261013_160804_baseline_results.zip` 用 scp 上传到同一路径即可。只上传此文件，不需要传全部 archive。

建议提前锁定模型 SHA 并预下载到 Hugging Face 缓存，减少占用 GPU 的下载时间：

```bash
export MODEL=meta-llama/Llama-3.1-8B-Instruct
REV=$(python -c 'import os; from huggingface_hub import HfApi; print(HfApi().model_info(os.environ["MODEL"]).sha)')
printf '%s\n' "$REV"
huggingface-cli download "$MODEL" --revision "$REV"
```

以上在登录节点只做文件下载，不运行推理。先检查自己的磁盘配额，确认模型缓存和环境有足够空间。
如果计算节点不能联网，预下载完成后可设置 `export HF_HUB_OFFLINE=1`，提交时必须传入已下载的完整 SHA。
如果退出过 SSH 导致 `REV` 丢失，重新设置为刚记录的完整 SHA，再提交作业。

## 6. 提交真实生成并查看记录

确认 `jobs/e01_tc2.sh` 的 CPU、主机内存和时间满足自己的 QoS。默认申请 2 CPU、28G RAM、1 GPU、1 小时。
Windows 编辑的 `.sh` 如出现 CRLF 错误，上传前在编辑器保存为 LF，或在服务器对这两个脚本执行 `sed -i 's/\r$//' jobs/e01_tc2.sh jobs/probe_tc2.sh`。

```bash
mkdir -p logs runs/e01
sbatch --partition=MGPU-TC2 --qos=normal jobs/e01_tc2.sh --revision "$REV"
squeue -u "$USER"
```

用返回的实际 ID 替换 `JOBID`：

```bash
tail -f logs/e01-JOBID.out
cat logs/e01-JOBID.err
sacct -j JOBID --format=JobID,State,ExitCode,Submit,Start,Elapsed,MaxRSS
seff JOBID
```

`tail -f` 用 Ctrl+C 退出，不会取消 sbatch 作业。Pending 时先看 Reason；Priority/Resources 通常表示等待，QoS 限额错误要调整申请。SSH 断开后 sbatch 作业可继续。

每个作业的输出目录为 `runs/e01/job-JOBID/`：

| 文件 | 用途 |
| --- | --- |
| `config.json`、`generation_config.json` | 模型和 tokenizer SHA、精度、生成上限、采样配置与输入哈希 |
| `environment.json`、`pip_freeze.txt` | GPU/驱动、Python、PyTorch/CUDA、依赖、Git commit 和代码状态 |
| `input.json`、`messages.json`、`prompt.txt` | 真实 DEV 材料、聊天消息、最终应用 Llama 模板后的完整输入 |
| `output.txt`、`token_ids.json` | 本次新生成的原始回答、实际输入/输出 Token ID |
| `metrics.json` | 输入与上下文 Token、含停止符的输出 Token、生成耗时、吞吐量、峰值显存、输出上限标记 |
| `failure.json` | 失败时的错误类型及信息；保留失败，改配置后用新 job ID 重跑 |

计时在 GPU 同步后开始和结束，`generation_seconds` 包括输入预填充与输出生成，吞吐量为输出 Token/该耗时，不能称为纯解码速度。
下载/加载、独立 warmup 和真实生成分别计时；排队时间根据 SLURM 的 Submit/Start 另记。`metrics.json` 的 status 为 generated 也需要人工打开 `output.txt` 检查；不代表回答已评分。

若 `hit_output_limit=true` 或输出为空，检查日志并用新作业目录重试；提高上限属于新配置，需要记录。
若不支持 BF16，可在同一 sbatch 命令末尾添加 `--dtype float16`，将其作为另一配置记录。
若 CUDA 不可用、OOM、模型访问 401/403 或下载失败，先按实际错误修复，不能把环境探测或历史输出作为 E01 已完成的证明。

## 7. 下载结果、写报告并提交

在 **Windows PowerShell** 中，进入正式 clone 后执行，替换账号和 JOBID：

```powershell
New-Item -ItemType Directory -Force '.\runs\e01'
scp -r your_ntu_id@10.96.189.12:~/projects/AI6103-DL-Project/runs/e01/job-JOBID .\runs\e01\
scp your_ntu_id@10.96.189.12:~/projects/AI6103-DL-Project/logs/e01-JOBID.out .\runs\e01\
scp your_ntu_id@10.96.189.12:~/projects/AI6103-DL-Project/logs/e01-JOBID.err .\runs\e01\
```

把 `sacct` 的 Submit、Start、Elapsed 也保存到该次结果目录。模型权重、环境目录和 Hugging Face token 不纳入 Git。
在 `e01/REPORT_CN.md` 写一页报告，填写本次实测值，不填估算：

- 日期、负责人、Git branch/commit、SLURM job ID、结果路径。
- GPU 与显存、驱动、Python、torch/CUDA、transformers 版本。
- 模型 ID、完整 revision SHA、tokenizer SHA、BF16/FP16、无量化、batch=1。
- 输入来源、DEV question ID、旧材料配置及 Llama 实际 Token 数。
- 完整输入/输出链接、`max_new_tokens`、greedy 设置、是否为空或截断。
- 排队、下载/加载、warmup、真实生成时间、含 prefill 的吞吐量、峰值显存。
- 人工检查结果与失败处理；说明本次是 E01，E02 的 CoN 与原排名设置待核对。

检查实际产物后再提交（以下为 Windows PowerShell）：

```powershell
git add e01/REPORT_CN.md e01/input_dev.json runs/e01/job-JOBID
git status --short
git commit -m "Record E01 real DEV generation configuration and timing"
git push
```

可向 main 创建 PR 供组员审阅。若仓库忽略 runs，先按团队约定调整结果保存位置，并在报告中给出能访问的产物路径。
把报告和产物位置交给全员后，E01 才具备验收证据；收到 D02 阅读材料后接 E02。

学校连接、模块和作业要求来源：本地 `docs/resources/CCDSGPU-TC2-Masters-UserGuide.pdf` 第 4、9–13、16–18 页。账号权限、QoS、GPU 与连通性尚未实测。
