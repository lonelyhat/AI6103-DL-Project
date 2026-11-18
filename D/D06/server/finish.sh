#!/usr/bin/env bash
# Export completed results and bundle all raw journals and runtime evidence.
set -eo pipefail
cd "$(dirname "$0")/.."
source server/activate.sh
set -u
python - <<'PY'
import json
from pathlib import Path
p = Path('runs/dev34-grid-v1')
if (p / '.writer.lock').exists():
    raise SystemExit('Writer still active; do not export.')
s = json.loads((p / 'summary.json').read_text())
if s['expected'] != 1156 or s['recorded'] != 1156 or s['missing']:
    raise SystemExit('Batch incomplete; inspect/resume before export.')
if s['statuses']['technical_failure']:
    raise SystemExit('Unresolved technical failures; fix/resume first.')
print(json.dumps(s, indent=2))
PY
if [[ -e runs/dev34-grid-v1/answers_for_f.jsonl || -e d06-dev34-results.tar.gz ]]; then
  echo 'An export/result archive already exists; inspect it instead of overwriting.' >&2
  exit 1
fi
python E/E03/export_for_f.py --run-dir runs/dev34-grid-v1 \
  --output runs/dev34-grid-v1/answers_for_f.jsonl
tar -czf d06-dev34-results.tar.gz runs/dev34-grid-v1 logs inputs \
  reference_reader_config.json SHA256SUMS E server
sha256sum d06-dev34-results.tar.gz
