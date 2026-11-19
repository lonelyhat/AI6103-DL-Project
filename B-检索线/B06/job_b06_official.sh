#!/usr/bin/env bash
#SBATCH --job-name=b06-official
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:00:00
# B06 step 2: official K1 comparison run, then validation of the step-1 candidates.
set -euo pipefail
: "${SLURM_JOB_ID:?Use sbatch}"
source "$HOME/B02/venv/bin/activate"
export TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
REPO="$HOME/B45/repo"; OUT="$HOME/B45/B06/results"
OFFICIAL="$HOME/B45/B06/official_prepared"
CACHE="$HOME/B45/B06/turn-userfact_c04_formal80.json"   # official asserts the path names the method
mkdir -p "$OUT/official"
cd "$REPO"
[ -d "$OFFICIAL" ] || python B-检索线/B05/prepare_official.py "$HOME/B02/official" "$OFFICIAL"
cp C04_new/c04_facts_80q.json "$CACHE"
cd "$OFFICIAL"
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
python -u src/retrieval/run_retrieval.py \
  --in_file "$HOME/B45/B04/formal80_longmemeval_s.json" \
  --out_dir "$OUT/official" --outfile_prefix formal80_K1 \
  --cache_dir "$HOME/B02/stella" --retriever flat-stella --granularity turn \
  --index_expansion_method turn-userfact --index_expansion_result_join_mode merge \
  --index_expansion_result_cache "$CACHE"
cd "$REPO"
python B-检索线/shared/kretrieve.py validate --stage formal --index K1 --output-dir "$OUT" \
  --official-log "$OUT/official/formal80_K1_retrievallog_turn_flat-stella" \
  --report "$OUT/validation.json"
echo 'B06 OFFICIAL COMPARISON COMPLETED'
