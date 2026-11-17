#!/usr/bin/env bash
#SBATCH --job-name=e02-reader
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:00:00
#SBATCH --output=logs/e02-%j.out
#SBATCH --error=logs/e02-%j.err
set -eo pipefail
: "${SLURM_JOB_ID:?Submit this script with sbatch}"
cd "${SLURM_SUBMIT_DIR:?}"
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01
set -u
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
python -u E/E02/run_generation.py \
  --input "${1:?Supply the prepared D02 JSONL path}" \
  --output "runs/e02/job-${SLURM_JOB_ID}"
