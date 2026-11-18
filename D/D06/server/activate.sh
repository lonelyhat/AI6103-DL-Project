#!/usr/bin/env bash
# Source from the extracted package root. Keep cache identical on login/GPU nodes.
set -eo pipefail
module load anaconda
eval "$(conda shell.bash hook)"
conda activate d06-reader
export HF_HOME="$PWD/hf_cache"
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
