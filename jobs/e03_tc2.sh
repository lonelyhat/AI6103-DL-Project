#!/usr/bin/env bash
#SBATCH --job-name=e03-reader
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:00:00
#SBATCH --output=logs/e03-%j.out
#SBATCH --error=logs/e03-%j.err
set -eo pipefail
: "${SLURM_JOB_ID:?Submit this script with sbatch}"
cd "${SLURM_SUBMIT_DIR:?}"
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01
set -u
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
input="${1:?Supply prepared input JSONL}"
output="${2:?Supply stable output directory, reused for resume}"
shift 2
python -u E/E03/run_generation.py --input "$input" --output "$output" "$@"
