#!/usr/bin/env bash
#SBATCH --job-name=b04-k0-formal80
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:30:00
# B04: formal K0 candidates. Reuses ~/B02 venv, Stella model and official code.
set -euo pipefail
: "${SLURM_JOB_ID:?Use sbatch}"
source "$HOME/B02/venv/bin/activate"
export TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
REPO="$HOME/B45/repo"; OUT="$HOME/B45/B04/results"; MODEL="$HOME/B02/stella/dunzhang_stella_en_1.5B_v5"
RUN="python -u B-检索线/shared/kretrieve.py run --stage formal --index K0 --model-dir $MODEL --output-dir $OUT --resume"
mkdir -p "$OUT/official"
cd "$REPO"
date -u; hostname
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python -m pip freeze > "$OUT/environment.txt"
$RUN
# Completed-checkpoint recovery on the same allocation: must skip all and keep bytes identical.
sha256sum "$OUT/candidates/"*.jsonl > "$OUT/before_resume.sha256"
$RUN > "$OUT/resume_check.txt"
sha256sum -c "$OUT/before_resume.sha256" > "$OUT/resume_hash_check.txt"
cd "$HOME/B02/official"
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
python -u src/retrieval/run_retrieval.py \
  --in_file "$HOME/B45/B04/formal80_longmemeval_s.json" \
  --out_dir "$OUT/official" --outfile_prefix formal80 \
  --cache_dir "$HOME/B02/stella" --retriever flat-stella --granularity turn
cd "$REPO"
python B-检索线/shared/kretrieve.py validate --stage formal --index K0 --output-dir "$OUT" \
  --official-log "$OUT/official/formal80_retrievallog_turn_flat-stella" \
  --report "$OUT/validation.json"
echo 'B04 COMPLETED'
