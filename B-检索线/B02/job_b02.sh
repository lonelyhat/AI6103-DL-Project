#!/usr/bin/env bash
# B02：首批 5 题 K0 检索（本组脚本）+ 官方 run_retrieval.py 对照，同一个作业里依次跑。
# partition / qos 在 sbatch 命令行给出，例如：
#   sbatch --partition=<你的partition> --qos=<你的qos> B-检索线/B02/job_b02.sh
# 约定目录（均在家目录下）：
#   ~/B02/repo          仓库（含 A-数据线/A01/output/public 与本脚本）
#   ~/B02/stella        精简模型包，内含 dunzhang_stella_en_1.5B_v5/
#   ~/B02/official      官方 LongMemEval 源码
#   ~/B02/dev5_longmemeval_s.json  5 题子集
#SBATCH --job-name=b02-k0
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:00:00
#SBATCH --output=logs/b02-%j.out
#SBATCH --error=logs/b02-%j.err
set -euo pipefail
: "${SLURM_JOB_ID:?请用 sbatch 提交}"
mkdir -p "$HOME/B02/logs" "$HOME/B02/results"
cd "$HOME/B02"
source "$HOME/B02/venv/bin/activate"
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4

echo "== 环境 =="; date -u; hostname
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python - <<'PY'
import torch, transformers
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), "transformers", transformers.__version__)
PY
python -m pip freeze > "$HOME/B02/results/environment.txt"

echo "== 1/2 本组脚本 =="
cd "$HOME/B02/repo"
python -u B-检索线/B02/retrieve_k0.py \
  --model-dir "$HOME/B02/stella/dunzhang_stella_en_1.5B_v5" \
  --output "$HOME/B02/results/dev_K0.jsonl"

echo "== 2/2 官方 run_retrieval.py 对照 =="
cd "$HOME/B02/official"
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
mkdir -p "$HOME/B02/results/official"
python -u src/retrieval/run_retrieval.py \
  --in_file "$HOME/B02/dev5_longmemeval_s.json" \
  --out_dir "$HOME/B02/results/official" \
  --outfile_prefix dev5 \
  --cache_dir "$HOME/B02/stella" \
  --retriever flat-stella --granularity turn
cd "$HOME/B02/repo"
python B-检索线/B02/check_and_compare.py "$HOME/B02/results/dev_K0.jsonl" \
  "$HOME/B02/results/official/dev5_retrievallog_turn_flat-stella" \
  | tee "$HOME/B02/results/validation.txt"
echo "== 完成 =="; ls -la "$HOME/B02/results" "$HOME/B02/results/official"
