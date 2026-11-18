#!/usr/bin/env bash
#SBATCH --job-name=b06-k1-formal80
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:00:00
# B06 step 1: formal K1 candidates + completed-checkpoint recovery check.
set -euo pipefail
: "${SLURM_JOB_ID:?Use sbatch}"
source "$HOME/B02/venv/bin/activate"
export TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
REPO="$HOME/B45/repo"; OUT="$HOME/B45/B06/results"; MODEL="$HOME/B02/stella/dunzhang_stella_en_1.5B_v5"
FACTS="B-检索线/B06/inputs/formal_facts_by_turn.jsonl"
RUN="python -u B-检索线/shared/kretrieve.py run --stage formal --index K1 --facts $FACTS --model-dir $MODEL --output-dir $OUT --resume"
mkdir -p "$OUT"
cd "$REPO"
date -u; hostname
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python -m pip freeze > "$OUT/environment.txt"
$RUN
sha256sum "$OUT/candidates/"*.jsonl > "$OUT/before_resume.sha256"
$RUN > "$OUT/resume_check.txt"
sha256sum -c "$OUT/before_resume.sha256" > "$OUT/resume_hash_check.txt"
echo 'B06 RETRIEVAL COMPLETED'
