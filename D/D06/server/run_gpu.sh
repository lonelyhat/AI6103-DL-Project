#!/usr/bin/env bash
#SBATCH --job-name=d06-reader
#SBATCH --account=stud
#SBATCH --partition=MGPU-TC2
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=02:00:00
#SBATCH --output=logs/d06-%j.out
#SBATCH --error=logs/d06-%j.err
set -eo pipefail
: "${SLURM_JOB_ID:?Submit this script using sbatch}"
cd "${SLURM_SUBMIT_DIR:?}"
source server/activate.sh
set -u
sha256sum --quiet -c SHA256SUMS
python server/check_environment.py
python -u E/E03/run_generation.py \
  --input inputs/reader_inputs.jsonl --output runs/dev34-grid-v1 "$@"
