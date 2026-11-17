#!/usr/bin/env bash
# Run from the repository root in e01 on the login node (CPU only).
set -euo pipefail

output=${1:?Supply a new batch directory, e.g. runs/e03/dev5-k0-inputs}
mkdir -p "$(dirname "$output")"
mkdir "$output"
output=$(cd "$output" && pwd -P)
repo=$(pwd -P)
d_commit=eacd6b246edef166ceae5b630cc2a4f2a2fc3cc6
if ! git cat-file -e "$d_commit^{commit}" 2>/dev/null; then
  git fetch origin d03-d05-selection
fi
git worktree add --detach "$output/d-code" "$d_commit"

export HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
tokenizer_dir=$(python - <<'PY'
import sys
from huggingface_hub import snapshot_download

sys.path.insert(0, 'E/E03')
from batch import reader

print(snapshot_download(reader.MODEL, revision=reader.REVISION, local_files_only=True))
PY
)
(
  cd "$output/d-code"
  python -m D.selection_batch \
    --candidates "$repo/E/E02/inputs/sources/b02_candidates.jsonl" \
    --public-root "$repo/A-数据线/A01/output/public" \
    --tokenizer "$tokenizer_dir" \
    --tokenizer-label meta-llama/Llama-3.1-8B-Instruct \
    --strategies MMR C Q FL --index K0 \
    --redundancy-weight 0.5 --coverage-weight 0.5 \
    --output-dir "$output/d03-d05"
)
python E/E03/prepare_inputs.py \
  --selections E/E02/results/job-55386/selections.jsonl "$output/d03-d05/selections.jsonl" \
  --turns-dir E/E02/inputs/sources/turns \
  --output "$output/dev5_k0_all_methods.jsonl" > "$output/preparation.json"

# Refuse partial or unexpectedly mixed settings, even if individual rows are valid.
python - "$output/dev5_k0_all_methods.jsonl" <<'PY'
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, 'E/E03')
from batch import load_inputs

rows = load_inputs(Path(sys.argv[1]))
questions = {'2318644b', '1cea1afa', 'gpt4_7a0daae1', '4c36ccef', 'c960da58'}
expected = Counter((qid, m) for qid in questions for m in ('R', 'MMR', 'C', 'Q', 'FL'))
actual = Counter((r['question_id'], r['strategy']) for r in rows
                 if r['index'] == 'K0' and r['budget_tokens'] == 2048)
if len(rows) != len(expected) or actual != expected:
    raise SystemExit('Expected 5 questions × 5 methods under K0/2048')
PY
python E/E03/run_generation.py --input "$output/dev5_k0_all_methods.jsonl" --check-only
printf 'CPU preflight passed. Use %s/dev5_k0_all_methods.jsonl for Slurm.\n' "$output"
