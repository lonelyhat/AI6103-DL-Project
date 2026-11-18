"""Validate E03 return batches against the frozen D06 handoff; never score answers."""
import argparse
import json
from pathlib import Path

from D.D01.selection import digest
from D.D02.prepare_materials import read_jsonl, sha
from D.D06.prepare import ROOT, e_module, save
from D.D06.finalize import JSONL_FIXES


def check(handoff, run_dirs):
    batch = e_module('batch')
    rows = batch.load_inputs(handoff / 'reader_inputs.jsonl')
    receipt = json.loads((handoff / 'handoff.json').read_text())
    if sha(handoff / 'reader_inputs.jsonl') != receipt['input_sha256']:
        raise ValueError('D input file changed')
    expected = {r['record_id']: r for r in rows}
    baseline = json.loads((ROOT / 'E/E03/results/dev5-k0-v1/config.json').read_text())
    found, signatures, configs = {}, set(), []
    for run in run_dirs:
        if (run / '.writer.lock').exists():
            raise ValueError('E batch is still writing')
        inputs = batch.load_inputs(run / 'inputs.jsonl')
        config = json.loads((run / 'config.json').read_text())
        for key in ('model', 'revision', 'tokenizer_revision', 'reader', 'dtype', 'quantization',
                    'do_sample', 'num_beams', 'max_new_tokens', 'seed', 'tokenizer_fingerprint',
                    'prompt_sha256', 'chat_template_sha256', 'source_sha256'):
            accepted = [baseline[key]]
            if key == 'source_sha256':
                corrected = dict(baseline[key])
                corrected['E03/batch.py'] = JSONL_FIXES['E/E03/batch.py'][1]
                accepted.append(corrected)
            if config.get(key) not in accepted:
                raise ValueError(f'E reader differs from accepted configuration: {key}')
        if config['input_sha256'] != sha(run / 'inputs.jsonl'):
            raise ValueError('E config/input hash mismatch')
        if config.get('records') != len(inputs):
            raise ValueError('E config/input count mismatch')
        # Input-specific hashes differ by batch; model/prompt/runtime must stay fixed.
        ignored = {'input_sha256', 'records'}
        signatures.add(digest({k: v for k, v in config.items() if k not in ignored}))
        raw = (run / 'attempts.jsonl').read_bytes()
        if raw and not raw.endswith(b'\n'):
            raise ValueError('E journal has an uncommitted last line')
        latest = batch.latest_attempts([json.loads(x) for x in raw.splitlines()], inputs, batch.digest(config))
        if read_jsonl(run / 'results.jsonl') != [latest[r['record_id']] for r in inputs if r['record_id'] in latest]:
            raise ValueError('E results do not match journal')
        for row in inputs:
            rid = row['record_id']
            if rid not in expected or row['input_record_sha256'] != expected[rid]['input_record_sha256']:
                raise ValueError('unexpected or changed E input')
            if rid in found:
                raise ValueError('duplicate E record across return batches')
            found[rid] = latest.get(rid)
            if found[rid] is not None:
                for key in ('question_id', 'index', 'strategy', 'selection_config_id', 'history_sha256',
                            'selected_turn_ids', 'context_tokens', 'budget_tokens'):
                    if found[rid].get(key) != row.get(key):
                        raise ValueError(f'E result/input identity mismatch: {key}')
        configs.append(dict(path=str(run), reader_config_id=batch.digest(config)))
    if len(signatures) > 1:
        raise ValueError('reader configuration differs across batches')
    missing = sorted(rid for rid in expected if found.get(rid) is None)
    statuses = {s: sum(r is not None and r['status'] == s for r in found.values())
                for s in ('generated', 'truncated', 'empty', 'technical_failure')}
    # f03-v1 scores recorded truncations without resampling. Do not confuse
    # complete generation coverage with every answer ending before its limit.
    ready = not missing and statuses['generated'] + statuses['truncated'] == len(expected)
    return dict(status='reader_complete_waiting_for_scores' if ready else 'reader_incomplete_or_needs_review',
                expected=len(expected), recorded=sum(r is not None for r in found.values()),
                statuses=statuses, missing_record_ids=missing, reader_configs=configs,
                needs_review=sum(r is not None and r.get('parse_status') == 'needs_review' for r in found.values()),
                truncated_retained_for_scoring=statuses['truncated'],
                parameters_selected=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--handoff-dir', type=Path, required=True)
    p.add_argument('--run-dirs', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('choose a new report path')
    if args.output.resolve().is_relative_to(args.handoff_dir.resolve() / 'shards') or any(
            args.output.resolve().is_relative_to(r.resolve()) for r in args.run_dirs):
        p.error('report must be outside E run directories and D shards')
    report = check(args.handoff_dir, args.run_dirs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report['status'] != 'reader_complete_waiting_for_scores':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
