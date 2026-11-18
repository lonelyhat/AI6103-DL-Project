#!/usr/bin/env bash
# Run from package root; creates a dedicated environment, not the old assignments'.
set -eo pipefail
module load anaconda
eval "$(conda shell.bash hook)"
if ! conda env list | awk '{print $1}' | grep -Fxq d06-reader; then
  conda create -y -n d06-reader python=3.11.18 pip
fi
conda activate d06-reader
python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
python -m pip install -r server/requirements.txt
python -m pip check
python server/check_environment.py
