"""Build an isolated E03 server upload package, without data/model recomputation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from D.D06.prepare import ROOT
from D.D02.prepare_materials import read_jsonl, sha


def build(source, destination):
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_relative_to(ROOT / 'D') or not destination.is_relative_to(ROOT / 'D/D06'):
        raise ValueError('source/output must be inside D/D06')
    if destination.exists() or destination.with_suffix('.tar.gz').exists():
        raise FileExistsError('choose a new upload directory')
    handoff = json.loads((source / 'handoff.json').read_text())
    preflight = json.loads((source / 'preflight.json').read_text())
    if (sha(source / 'reader_inputs.jsonl') != handoff['input_sha256']
            or handoff['records'] != 1156 or len(read_jsonl(source / 'reader_inputs.jsonl')) != 1156
            or preflight['records'] != 1156 or preflight['status'] != 'E_token_prompt_capacity_checks_passed'):
        raise ValueError('expected the verified 1156-record handoff')
    destination.mkdir(parents=True)
    files = ['E/E02/run_generation.py', 'E/E02/export_for_f.py',
             'E/E03/run_generation.py', 'E/E03/batch.py', 'E/E03/export_for_f.py',
             'E/E03/prepare_inputs.py']
    for name in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    for path in (ROOT / 'D/D06/server').iterdir():
        if path.is_file():
            target = destination / 'server' / path.name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(path, target)
    (destination / 'inputs').mkdir()
    for name in ('reader_inputs.jsonl', 'plan.json', 'handoff.json', 'recovery_manifest.json', 'preflight.json'):
        shutil.copyfile(source / name, destination / 'inputs' / name)
    shutil.copyfile(ROOT / 'E/E03/results/dev5-k0-v1/config.json', destination / 'reference_reader_config.json')
    shutil.copyfile(ROOT / 'D/D06/SERVER_RUN.md', destination / 'SERVER_RUN.md')
    inventory = {p.relative_to(destination).as_posix(): sha(p)
                 for p in sorted(destination.rglob('*')) if p.is_file()}
    (destination / 'SHA256SUMS').write_text(''.join(f'{h}  {p}\n' for p, h in inventory.items()), encoding='utf-8')
    archive = destination.with_suffix('.tar.gz')
    with tarfile.open(archive, 'w:gz') as handle:
        handle.add(destination, arcname=destination.name, filter=lambda info: info)
    report = dict(archive=str(archive), archive_bytes=archive.stat().st_size,
                  archive_sha256=sha(archive), files=len(inventory), input_records=1156,
                  model_weights_included=False, upload_performed=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=ROOT / 'D/D06/output/dev34-grid-v1')
    p.add_argument('--output-dir', type=Path, default=ROOT / 'D/D06/upload/d06-dev34-server-v1')
    args = p.parse_args()
    build(args.source, args.output_dir)


if __name__ == '__main__':
    main()
