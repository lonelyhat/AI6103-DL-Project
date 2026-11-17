#!/usr/bin/env bash
# Resource flags are supplied on sbatch; TC2 commands request one GPU in both phases.
#SBATCH --job-name=e01-notebook
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=logs/e01-nb-%j.out
#SBATCH --error=logs/e01-nb-%j.err
# Conda activation hooks can read optional unset variables.
set -eo pipefail
: "${SLURM_JOB_ID:?Submit through sbatch}"
cd "${SLURM_SUBMIT_DIR:?}"
phase="${1:-prepare}"
if [[ "$phase" != prepare && "$phase" != generate ]]; then
  echo 'Usage: jobs/e01_notebook_tc2.sh prepare|generate [full_model_SHA]'
  exit 2
fi
if [[ "$phase" == generate && ! "${2:-}" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Generate requires a full, already-downloaded model SHA as its second argument.'
  exit 2
fi
module load anaconda
eval "$(conda shell.bash hook)"
conda activate e01
set -u
export E01_PHASE="$phase"
export E01_MODEL_REVISION="${2:-}"
export E01_OUTPUT_DIR="$PWD/runs/e01/notebook-${phase}-${SLURM_JOB_ID}"
export TOKENIZERS_PARALLELISM=false
mkdir "$E01_OUTPUT_DIR"
bash jobs/probe_tc2.sh > "$E01_OUTPUT_DIR/current_probe.out"
if [[ "$phase" == generate ]]; then
  # Cache must be complete before starting a GPU job.
  export HF_HUB_OFFLINE=1
fi
# Install the kernelspec into this run only, using the active e01 interpreter.
python -m ipykernel install --prefix "$E01_OUTPUT_DIR/kernel" --name e01 --display-name 'Python (e01 job)'
export JUPYTER_PATH="$E01_OUTPUT_DIR/kernel/share/jupyter${JUPYTER_PATH:+:$JUPYTER_PATH}"
python -m nbconvert --to notebook --execute E/E01/E01_environment_and_generation.ipynb \
  --ExecutePreprocessor.kernel_name=e01 --ExecutePreprocessor.timeout=2700 \
  --output executed.ipynb --output-dir "$E01_OUTPUT_DIR"
