#!/usr/bin/env bash
#SBATCH --job-name=b05-k1-dev40
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:30:00
# B05: development K1 candidates. Reuses ~/B02 venv, Stella model and official code.
set -euo pipefail
: "${SLURM_JOB_ID:?Use sbatch}"
source "$HOME/B02/venv/bin/activate"
export TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
REPO="$HOME/B45/repo"; OUT="$HOME/B45/B05/results"; MODEL="$HOME/B02/stella/dunzhang_stella_en_1.5B_v5"
FACTS="B-检索线/B05/inputs/dev_facts_by_turn.jsonl"
PATCHED="$HOME/B45/B05/official_patched"
CACHE="$HOME/B45/B05/turn-userfact_c03_dev40.json"   # official asserts the path names the method
RUN="python -u B-检索线/shared/kretrieve.py run --stage dev --index K1 --facts $FACTS --model-dir $MODEL --output-dir $OUT --resume"
mkdir -p "$OUT/official"
cd "$REPO"
date -u; hostname
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python -m pip freeze > "$OUT/environment.txt"
$RUN
sha256sum "$OUT/candidates/"*.jsonl > "$OUT/before_resume.sha256"
$RUN > "$OUT/resume_check.txt"
sha256sum -c "$OUT/before_resume.sha256" > "$OUT/resume_hash_check.txt"
# Patched official comparison (two documented fixes; see B05/prepare_official.py).
[ -d "$PATCHED" ] || python B-检索线/B05/prepare_official.py "$HOME/B02/official" "$PATCHED"
cp C03/dev_facts_all40q.json "$CACHE"
cd "$PATCHED"
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
python -u src/retrieval/run_retrieval.py \
  --in_file "$HOME/B03/dev40_longmemeval_s.json" \
  --out_dir "$OUT/official" --outfile_prefix dev40_K1 \
  --cache_dir "$HOME/B02/stella" --retriever flat-stella --granularity turn \
  --index_expansion_method turn-userfact --index_expansion_result_join_mode merge \
  --index_expansion_result_cache "$CACHE"
cd "$REPO"
python B-检索线/shared/kretrieve.py validate --stage dev --index K1 --output-dir "$OUT" \
  --official-log "$OUT/official/dev40_K1_retrievallog_turn_flat-stella" \
  --report "$OUT/validation.json"
echo 'B05 COMPLETED'
