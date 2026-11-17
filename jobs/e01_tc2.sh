#!/usr/bin/env bash
# Supply your verified --partition and --qos on the sbatch command line.
# Adjust the example CPU/RAM/time requests to your assigned limits.
#SBATCH --job-name=e01-reader
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:1
#SBATCH --mem=28G
#SBATCH --time=01:00:00
#SBATCH --output=logs/e01-%j.out
#SBATCH --error=logs/e01-%j.err
# Conda activation hooks can read optional unset variables.
set -eo pipefail
: "${SLURM_JOB_ID:?Submit this script with sbatch}"
cd "${SLURM_SUBMIT_DIR:?}"
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01
set -u
export TOKENIZERS_PARALLELISM=false
bash jobs/probe_tc2.sh
python -u E/E01/run_generation.py \
  --input E/E01/input_dev.json \
  --output "runs/e01/job-${SLURM_JOB_ID}" "$@"
