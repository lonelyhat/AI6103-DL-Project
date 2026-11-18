"""Assemble compact, auditable D06 Git deliverables without invoking Git."""
import json
from pathlib import Path
import shutil

from D.D02.prepare_materials import sha
from D.D06.prepare import ROOT


def main():
    here = ROOT / 'D/D06'
    delivery = here / 'delivery'
    delivery.mkdir(exist_ok=True)
    selected = here / 'output/dev34-parameter-selection-v1'
    params = json.loads((selected / 'selected_parameters.json').read_text())
    scores = ROOT / 'F/scores/d06_dev34_grid_v1.jsonl'
    if sha(scores) != params['provenance_sha256'][str(scores)]:
        raise ValueError('scores changed since parameter selection')
    mappings = {here / 'output/dev34-grid-v1' / name: delivery / name
                for name in ('plan.json', 'handoff.json', 'recovery_manifest.json', 'preflight.json')}
    returned = here / 'returned/dev34-grid-v1'
    mappings[returned / 'return_audit.json'] = delivery / 'return_audit.json'
    mappings[returned / 'd06-dev34-results.tar.gz'] = delivery / 'd06-dev34-results.tar.gz'
    for source, target in mappings.items():
        if target.exists() and sha(target) != sha(source):
            raise ValueError(f'existing delivery changed: {target.name}')
        if not target.exists():
            shutil.copyfile(source, target)
    evidence = sorted(mappings.values()) + sorted(p for p in selected.iterdir() if p.is_file()) + [scores]
    (delivery / 'SHA256SUMS').write_text(''.join(
        f'{sha(p)}  {p.relative_to(ROOT).as_posix()}\n' for p in evidence), encoding='utf-8')
    print(json.dumps(dict(status='delivery_prepared', evidence_files=len(evidence),
                         evidence_bytes=sum(p.stat().st_size for p in evidence),
                         git_executed=False, delivery=str(delivery)), indent=2))


if __name__ == '__main__':
    main()
