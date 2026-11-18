#!/usr/bin/env bash
# After a completed smoke run, queue bounded, serial resumes of the same journal.
set -eo pipefail
cd "$(dirname "$0")/.."
source server/activate.sh
set -u
sha256sum --quiet -c SHA256SUMS
if squeue -h -u "$USER" -o '%j' | grep -Fxq d06-reader; then
  echo 'A d06-reader job is already pending/running. Wait for it before submitting more.' >&2
  exit 1
fi
chunks=$(python - <<'PY'
import json
from pathlib import Path
out = Path('runs/dev34-grid-v1')
if (out / '.writer.lock').exists():
    raise SystemExit('Writer lock present; inspect the old job first.')
s = json.loads((out / 'summary.json').read_text())
if s['expected'] != 1156:
    raise SystemExit('Unexpected input count.')
if s['statuses']['technical_failure']:
    raise SystemExit('Resolve technical failures before automatically queuing resumes.')
remaining = s['missing']
print((remaining + 199) // 200)
PY
)
# E03 freezes GPU name and runtime in the resume configuration. Use the smoke
# run's node for every continuation so heterogeneous GPUs cannot invalidate it.
node=$(python - <<'PY'
import json
from pathlib import Path
rows = [json.loads(line) for line in Path('runs/dev34-grid-v1/runtime.jsonl').open() if line.strip()]
print(rows[0]['host'])
PY
)
if [[ ! "$node" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo 'Invalid smoke-run node name.' >&2
  exit 1
fi
previous=''
for ((i=0; i<chunks; i++)); do
  dependency=()
  if [[ -n "$previous" ]]; then dependency=(--dependency="afterok:$previous"); fi
  job=$(sbatch --parsable --nodelist="$node" "${dependency[@]}" server/run_gpu.sh --resume --stop-after 200)
  previous=${job%%;*}
  printf 'Queued resume %s/%s: job %s\n' "$((i+1))" "$chunks" "$previous"
done
if [[ -n "$previous" ]]; then
  echo "Final queued job: $previous. Verify summary.json after it finishes."
else
  echo 'No missing records; inspect summary.json and export results.'
fi
