"""Audit a downloaded server archive, E journals, and the exact F export offline."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from D.D02.prepare_materials import read_jsonl, sha
from D.D06.prepare import e_module, save
from D.D06.check_reader import check


def audit(handoff, returned):
    archive = returned / 'd06-dev34-results.tar.gz'
    verified = 0
    with tarfile.open(archive) as handle:
        names = set()
        for entry in handle.getmembers():
            path = PurePosixPath(entry.name)
            if path.is_absolute() or '..' in path.parts or entry.issym() or entry.islnk():
                raise ValueError('unsafe archive member')
            if not entry.isfile():
                continue
            if entry.name in names:
                raise ValueError('duplicate archive member')
            names.add(entry.name)
            local = returned / entry.name
            fingerprint = hashlib.sha256()
            stream = handle.extractfile(entry)
            with stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    fingerprint.update(block)
            if not local.is_file() or sha(local) != fingerprint.hexdigest():
                raise ValueError('download/extracted archive mismatch: ' + entry.name)
            verified += 1
    omitted_documents = []
    for line in (returned / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('unsafe checksum path')
        # finish.sh archives runtime/code/input files but omits this instruction
        # document from the original upload. Record that omission explicitly.
        if name == 'SERVER_RUN.md' and not (returned / name).exists():
            omitted_documents.append(name)
            continue
        if sha(returned / name) != expected:
            raise ValueError('uploaded package checksum mismatch: ' + name)
    for name in ('reader_inputs.jsonl', 'plan.json', 'handoff.json', 'recovery_manifest.json', 'preflight.json'):
        if sha(returned / 'inputs' / name) != sha(handoff / name):
            raise ValueError('returned handoff differs: ' + name)
    run = returned / 'runs/dev34-grid-v1'
    report = check(handoff, [run])
    rows = read_jsonl(run / 'results.jsonl')
    summary = json.loads((run / 'summary.json').read_text())
    if (summary['expected'] != report['expected'] or summary['recorded'] != report['recorded']
            or summary['missing'] != len(report['missing_record_ids'])
            or any(summary['statuses'][key] != report['statuses'][key] for key in report['statuses'])
            or summary['attempts'] != len(read_jsonl(run / 'attempts.jsonl'))):
        raise ValueError('server summary differs from actual records')
    with tempfile.TemporaryDirectory() as directory:
        export = Path(directory) / 'answers.jsonl'
        n_export = e_module('export_for_f').export(run, export)
        if sha(export) != sha(run / 'answers_for_f.jsonl') or n_export != len(rows):
            raise ValueError('F export differs from final attempts')
    report.update(archive_sha256=sha(archive), archive_files_verified=verified,
                  archive_and_upload_checksums='passed', original_handoff_match=True,
                  upload_manifest_documents_omitted_from_return=omitted_documents,
                  final_results_match_attempts=True, f_export_verified_records=n_export,
                  index_strategy_counts=dict(sorted(Counter(r['index'] + '/' + r['strategy'] for r in rows).items())),
                  truncated_records=[dict(question_id=r['question_id'], index=r['index'], strategy=r['strategy'],
                                          record_id=r['record_id'], selection_config_id=r['selection_config_id'])
                                     for r in rows if r['status'] == 'truncated'],
                  scoring_performed=False, parameter_selection_performed=False)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--handoff-dir', type=Path, required=True)
    p.add_argument('--returned-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('choose a new report file')
    result = audit(args.handoff_dir, args.returned_dir)
    save(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
