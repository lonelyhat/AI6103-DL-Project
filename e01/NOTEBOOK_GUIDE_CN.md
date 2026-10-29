# E01 notebook：先准备，模型批准后再生成

本地仓库：`C:\Users\avalon\Desktop\Project\AI6103-DL-Project`。
服务器仓库：`/home/msai/chunjie001/projects/AI6103-DL-Project`。
Git 分支：`e01`。后续命令均在 VS Code Terminal 中执行。

## 当前可以做什么

`E01_environment_and_generation.ipynb` 已写好。`prepare` 阶段不访问 Llama、不下载模型。按 TC2 手册作业模板仍申请 1 张 GPU，用于短暂探测设备与 CUDA；不加载回答模型。
它保存已有探测日志、软件环境、Git commit、代码哈希、开发输入检查结果和待填报告。
`generate` 阶段复用已有 `run_generation.py`，完成真正的新回答。

学校登录节点只用于编辑、安装环境、下载文件与提交作业。Notebook 在服务器端通过 sbatch 执行，在 VS Code 中查看执行后的副本；无需在登录节点启动 Jupyter 服务。
Notebook 首个代码单元会阻止在未分配 SLURM 作业的 Linux 环境中继续运行。

## 1. 同步本地新文件

在本地 VS Code 的 PowerShell Terminal：

```powershell
Set-Location 'C:\Users\avalon\Desktop\Project\AI6103-DL-Project'
git status --short --branch
git add e01/E01_environment_and_generation.ipynb e01/notebook_utils.py e01/input_manifest.json e01/requirements-notebook.txt e01/NOTEBOOK_GUIDE_CN.md jobs/e01_notebook_tc2.sh
git commit -m "Add E01 preparation and generation notebook"
git push origin e01
```

在服务器 VS Code 的 Bash Terminal：

```bash
cd /home/msai/chunjie001/projects/AI6103-DL-Project
git status --short --branch
git pull --ff-only origin e01
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01
python -m pip install -r e01/requirements-notebook.txt
python -m pip check
mkdir -p logs runs/e01
```

如果有本地或远程改动，先检查内容再合并。不要丢弃已有实验日志。

## 2. 现在提交准备检查

在服务器 Bash Terminal：

```bash
sbatch --partition=MGPU-TC2 --qos=normal --cpus-per-task=1 --gres=gpu:1 --mem=4G --time=00:10:00 jobs/e01_notebook_tc2.sh prepare
```

用返回的真实作业编号替换 JOBID：

```bash
squeue -j JOBID
sacct -j JOBID --format=JobID,State,ExitCode,Submit,Start,Elapsed
cat logs/e01-nb-JOBID.out
cat logs/e01-nb-JOBID.err
```

输出目录：`runs/e01/notebook-prepare-JOBID/`。
在远程 VS Code 左侧文件列表找到并打开 `executed.ipynb`，直接查看保存的单元输出；不需要点 Run All。

该目录包含：

- `input_audit.json`：DEV 身份、哈希、字段白名单、原文重建、轮次及时间顺序检查。
- `preparation_environment.json`、`pip_freeze.txt`、`pip_check.json`：本次 kernel 的软件环境，不把它冒充旧 GPU 作业环境。
- `prior_probes/`、`prior_probe_records.json`：读取 `logs/probe-48841.*` 和 `logs/cuda-check-48855.*` 的原始记录，分别保留 A40 与 L40S 身份；文件缺失会明确标记。
- `current_probe.out`、`current_probe_record.json`：准备作业本次实际分配的 GPU/CUDA 探测，不混用旧作业的设备信息。
- `slurm_accounting.json`：通过 sacct 取得的两个历史作业状态与时间；失败时保存原因。
- `REPORT_CN.md`：准备阶段的报告草稿，模型与生成测量保留为待完成。

输入清单在本次 authoring 时与旧 ZIP 的 DEV 清单及选中材料核对过。新仓库没有旧 ZIP 时，可以用清单进行哈希和成员检查；这不等于在服务器重新检查了原 ZIP。
来源锁定使用规范化 JSON 的 SHA256，避免 Git 的 CRLF/LF 换行转换造成误报；同时另存本次输入文件的原始字节 SHA256。
修改材料后不要只更新哈希来绕过检查，应重新核对 DEV 来源、轮次和交接版本。

检查不使用参考答案来判断正确率；它证明输入结构与来源符合当前试跑约定，不代替 F01/F02 评分。
没有 Llama tokenizer 时不估算实际 Token，旧 2048 Qwen Token 也不冒充 Llama 预算。

## 3. 模型获批后才做

先在服务器 Bash Terminal 中激活 e01，交互式登录，令牌不写入 notebook：

```bash
huggingface-cli login
```

锁定模型 SHA，并仅预下载 Transformers 所需文件，避免同时下载原生格式的重复权重：

```bash
export MODEL=meta-llama/Llama-3.1-8B-Instruct
REV=$(python -c 'import os; from huggingface_hub import HfApi; print(HfApi().model_info(os.environ["MODEL"]).sha)')
printf '%s\n' "$REV"
huggingface-cli download "$MODEL" --revision "$REV" --include '*.json' '*.safetensors' '*.model' '*.jinja' '*.txt' --exclude 'original/*'
```

下载成功后提交 GPU 作业：

```bash
sbatch --partition=MGPU-TC2 --qos=normal --cpus-per-task=2 --gres=gpu:1 --mem=28G --time=01:00:00 jobs/e01_notebook_tc2.sh generate "$REV"
```

完整 SHA 是必须参数。生成阶段设置离线模式，仅使用已下载缓存；缓存缺失会失败并记录，不会在 GPU 计时中悄悄下载。
新作业的 GPU 可能不同于两次探测，实际型号以 `generation/environment.json` 为准。

输出目录：`runs/e01/notebook-generate-JOBID/`。
`generation/` 内保存真实回答及配置，`executed.ipynb` 汇总 Token、耗时与实际输入输出。
生成前用同一模型 SHA 的 tokenizer 记录完整 prompt 长度，并检查不会超出模型上下文；不强行截短原始材料。

该 notebook 使用原有直接回答运行器，只完成 E01。原论文逐块笔记再汇总回答的 CoN 核对是 E02 范围。

## 4. 交付前人工检查

打开 `generation/output.txt`、`generation/metrics.json` 与 `REPORT_CN.md`。
确认真实输出非空、检查 `hit_output_limit`，填写报告中的人工核对项。生成阶段成功不等于答案正确。
吞吐量包含输入 prefill；下载、加载、warmup、生成和排队需分开记录。
模型未获批或没有真实生成时，E01 保持未完成，报告不能写成实验已完成。

Notebook 和报告只整理明确的环境字段，不导出 HF token 或完整环境变量。不要提交模型权重或 kernel 连接文件。
需要交付结果时，选择提交对应输出目录中的报告、审计 JSON、环境 JSON、完整输入输出、原始日志及 executed notebook；省略运行期 `kernel/` 子目录。

参考：

- <https://nbconvert.readthedocs.io/en/latest/execute.html>
- <https://code.visualstudio.com/docs/datascience/jupyter-notebooks>
- <https://huggingface.co/docs/huggingface_hub/v0.30.2/package_reference/file_download>
