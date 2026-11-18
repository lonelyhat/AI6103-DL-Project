#!/usr/bin/env bash
#SBATCH --job-name=b03-k0-dev40
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Use sbatch}"
source "$HOME/B02/venv/bin/activate"
export TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
cd "$HOME/B02/repo"
mkdir -p "$HOME/B03/results/official"
date -u
hostname
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python -m pip freeze > "$HOME/B03/results/environment.txt"
python -u B-检索线/B03/retrieve_dev.py \
  --model-dir "$HOME/B02/stella/dunzhang_stella_en_1.5B_v5" \
  --output-dir "$HOME/B03/results" --resume
# Exercise completed-checkpoint recovery on the same real GPU allocation.
sha256sum "$HOME/B03/results/candidates/"*.jsonl > "$HOME/B03/results/before_resume.sha256"
python -u B-检索线/B03/retrieve_dev.py \
  --model-dir "$HOME/B02/stella/dunzhang_stella_en_1.5B_v5" \
  --output-dir "$HOME/B03/results" --resume \
  > "$HOME/B03/results/resume_check.txt"
sha256sum -c "$HOME/B03/results/before_resume.sha256" > "$HOME/B03/results/resume_hash_check.txt"
cd "$HOME/B02/official"
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
python -u src/retrieval/run_retrieval.py \
  --in_file "$HOME/B03/dev40_longmemeval_s.json" \
  --out_dir "$HOME/B03/results/official" --outfile_prefix dev40 \
  --cache_dir "$HOME/B02/stella" --retriever flat-stella --granularity turn
cd "$HOME/B02/repo"
python B-检索线/B03/validate_results.py \
  --output-dir "$HOME/B03/results" \
  --official-log "$HOME/B03/results/official/dev40_retrievallog_turn_flat-stella" \
  --report "$HOME/B03/results/validation.json"
echo 'B03 COMPLETED'
