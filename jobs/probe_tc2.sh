#!/usr/bin/env bash
# Diagnostic only. Submit via sbatch on the user's approved partition/QoS.
# No model/data downloads, no training, no Reader inference.
set -euo pipefail
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo "Run this diagnostic inside a granted SLURM compute job."
  exit 1
fi
date -u
hostname
printf 'SLURM_JOB_ID=%s\n' "$SLURM_JOB_ID"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python --version
python - <<'PY'
import importlib.metadata
for name in ['torch', 'transformers', 'huggingface-hub', 'sentence-transformers']:
    try:
        print(name, importlib.metadata.version(name))
    except importlib.metadata.PackageNotFoundError:
        print(name, 'not installed')
try:
    import torch
    print('cuda_available', torch.cuda.is_available())
    print('torch_cuda', torch.version.cuda)
except ImportError:
    pass
PY
