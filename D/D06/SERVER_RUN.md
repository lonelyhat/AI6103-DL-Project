# D06 服务器上传与运行（全部34题 / 1156份材料）

沿用之前《下载assignment2结果到本地》记录中的账号 `yanrui001@10.96.189.12`。本次没有登录或上传到服务器，以下命令由你执行。校外先连接学校 VPN。使用独立目录、独立 Conda 环境和独立模型缓存，不改旧 assignment。

## 1. 上传包包含什么

本机文件：`D/D06/upload/d06-dev34-server-v1.tar.gz`。只上传这个包。

- `inputs/reader_inputs.jsonl`：已验证的1156条输入，保留全部参数身份和完整原文。
- `inputs/plan.json`、`handoff.json`、`recovery_manifest.json`、`preflight.json`：冻结网格、指纹、导出恢复及完整容量检查。
- `E/E03/`：固定批量阅读代码、JSONL读取修复和F导出器。
- `E/E02/run_generation.py`、`export_for_f.py`：E03依赖的固定提示词与答案导出转换。
- `server/`：环境安装、固定模型下载、GPU作业、顺序恢复提交与结果归档脚本。
- `reference_reader_config.json`、`SHA256SUMS`：原E验收配置及包内文件校验。

不包含模型权重、整套原始数据、官方答案、检索模型、Git目录和本机Conda环境。1156份材料已经完成，服务器不用重新运行选择。

## 2. 本机 WSL 上传与登录

```bash
cd /home/cyr2526/DL_project/AI6103-DL-Project
scp D/D06/upload/d06-dev34-server-v1.tar.gz yanrui001@10.96.189.12:~/
ssh yanrui001@10.96.189.12
```

输入学校服务器密码。不要把这些Linux命令粘到Windows PowerShell后省略WSL步骤。

## 3. 服务器解包与校验

以下都在刚登录的服务器终端执行：

```bash
mkdir -p ~/DL_D06
cd ~/DL_D06
test ! -e d06-dev34-server-v1 && tar -xzf ~/d06-dev34-server-v1.tar.gz
cd d06-dev34-server-v1
sha256sum --quiet -c SHA256SUMS && echo 'Upload checksum PASS'
df -h .
mytcinfo
sinfo -p MGPU-TC2 -N -o '%N %t %G'
```

校验通过再继续。安装CUDA PyTorch及下载BF16模型需要数十GB磁盘空间，建议至少预留40GB。这里沿用项目历史的 `stud` / `MGPU-TC2` / `normal`。本次未连接服务器确认配额与当前节点状态；如果你的 `mytcinfo` 显示不同账户或分区，按实际权限修改 `server/run_gpu.sh` 的SBATCH资源行，然后在包根目录执行 `sha256sum server/run_gpu.sh > RESOURCE_OVERRIDE.sha256` 留存本地修改记录，并更新 `SHA256SUMS` 中该脚本的哈希。其余阅读代码、输入及参数不要改。

## 4. 新建独立环境

```bash
bash server/setup_env.sh
source server/activate.sh
```

脚本新建 `d06-reader`（Python3.11.18），安装与E验收一致的 `torch=2.6.0+cu124`、transformers4.51.3、tokenizers0.21.4、huggingface-hub0.30.2等固定依赖。`pip check` 和 runtime_pins_passed 通过后继续。环境已存在时仅复核/安装同一套依赖；不要在已经生成过本轮回答后再修改环境。

## 5. 登录 Hugging Face、下载固定模型

```bash
source server/activate.sh
HF_HUB_OFFLINE=0 huggingface-cli login
HF_HUB_OFFLINE=0 python server/download_model.py
```

登录时在服务器交互输入你自己的HF token，无需把token发给任何人。账号需已获得 `meta-llama/Llama-3.1-8B-Instruct` 访问权限；若出现401/403，先解决账号访问权限。下载脚本固定revision `0e9e39f249a16976918f6564b8830bc894c89659`，缓存到当前包目录的hf_cache，不会在登录节点加载权重或生成回答。网络中断后重新运行下载脚本会复用已缓存内容。

## 6. CPU检查与2条GPU试跑

```bash
python E/E03/run_generation.py --input inputs/reader_inputs.jsonl --schema-only
python E/E03/run_generation.py --input inputs/reader_inputs.jsonl --check-only
mkdir -p logs
sbatch server/run_gpu.sh --stop-after 2
squeue -u "$USER"
```

`--check-only` 只使用CPU校验分词器指纹、全部1156条预算与完整提示词容量，可能需要几分钟。GPU推理仅通过sbatch运行。

记下sbatch打印的作业号，结束后检查（把12345换成实际作业号）：

```bash
sacct -j 12345 --format=JobID,State,ExitCode,Elapsed,NodeList
cat runs/dev34-grid-v1/summary.json
```

应为COMPLETED / 0:0，summary expected=1156、recorded=2、missing=1154，technical_failure/truncated/empty均为0。此时只是试跑完成，还没有完成全部1156条。

## 7. 顺序提交剩余全部回答

确认试跑结束且结果正常后：

```bash
bash server/submit_remaining.sh
squeue -u "$USER"
```

脚本根据缺失条数提交最多6个GPU作业，采用afterok依赖依次执行，每个最多新增200条；都恢复同一个 `runs/dev34-grid-v1`，不会重复生成已经完成的回答。为保持严格恢复配置，后续作业固定在试跑所在节点。脚本会拒绝在已有d06-reader作业、写锁或未解决技术失败时重复提交。

每个作业在执行前都会对全部输入进行CPU检查；最后一个作业结束后，summary应expected=recorded=1156、missing=0。`needs_review` 不代表没有生成回答，最终由F按f03-v1规则处理。

如果某个作业失败，后续依赖作业会保持DependencyNeverSatisfied，不会自动重复采样。先查看对应 `logs/d06-作业号.err` 和 `.out`，不要修改模型、提示词、输出额度或输入文件来恢复旧批次。将错误发回来处理。截断/空回答保留原始状态，不能选择性重采样；技术失败可以按同配置补跑。

## 8. 导出、打包和下载结果

全部完成后在服务器执行：

```bash
cat runs/dev34-grid-v1/summary.json
bash server/finish.sh
```

导出 `answers_for_f.jsonl` 并生成 `d06-dev34-results.tar.gz`。包内保留全部输入、配置、尝试日志、最终回答、用量、耗时、作业记录及代码；不打包模型权重。该脚本拒绝缺失输入、未解决技术失败或覆盖已有归档。

回到你本机新的WSL终端执行下载：

```bash
cd /home/cyr2526/DL_project/AI6103-DL-Project
mkdir -p D/D06/returned/dev34-grid-v1
scp yanrui001@10.96.189.12:~/DL_D06/d06-dev34-server-v1/d06-dev34-results.tar.gz \
  D/D06/returned/dev34-grid-v1/
tar -xzf D/D06/returned/dev34-grid-v1/d06-dev34-results.tar.gz \
  -C D/D06/returned/dev34-grid-v1
source /home/cyr2526/DL_project/.conda/d06/bin/activate
python -m D.D06.check_reader \
  --handoff-dir D/D06/output/dev34-grid-v1 \
  --run-dirs D/D06/returned/dev34-grid-v1/runs/dev34-grid-v1 \
  --output D/D06/returned/dev34-grid-v1/e_receipt.json
```

F使用返回目录中的 `answers_for_f.jsonl` 按f03-v1评分，之后D汇总评分并选择参数。服务器生成完成不等于已评分或D06已选参。
