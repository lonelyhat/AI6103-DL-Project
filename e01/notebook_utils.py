"""CPU-only E01 audit helpers. No model, CUDA or credential imports."""
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def command(args, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=30)
        return {'returncode': result.returncode, 'stdout': result.stdout.strip(),
                'stderr': result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'returncode': None, 'stdout': '', 'stderr': str(error)}


def inspect_input(repo):
    repo = Path(repo)
    path = repo / 'e01/input_dev.json'
    item = json.loads(path.read_text(encoding='utf-8'))
    manifest = json.loads((repo / 'e01/input_manifest.json').read_text(encoding='utf-8'))
    assert set(item) == {'stage', 'question_id', 'question_date', 'question', 'context', 'units', 'source'}
    assert item['stage'] == 'dev' and item['question_id'] in manifest['archived_dev_ids']
    assert item['question_id'] == manifest['question_id']
    canonical_sha = hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True,
                                               separators=(',', ':')).encode()).hexdigest()
    assert canonical_sha == manifest['canonical_input_sha256'], 'Input changed; review its provenance before running'
    assert item['source']['archive_sha256'] == manifest['archive_sha256']
    assert re.fullmatch(r'[0-9a-f]{64}', item['source']['archive_sha256'])
    assert item['question'].strip() and item['question_date'].strip() and item['context'].strip()
    units = item['units']
    assert units and len({u['id'] for u in units}) == len(units)
    orders, dates, parts = [], [], []
    for unit in units:
        assert set(unit) == {'id', 'order', 'timestamp', 'messages'}
        assert unit['messages'] and unit['messages'][0]['role'] == 'user'
        orders.append(unit['order'])
        dates.append(datetime.strptime(unit['timestamp'], '%Y/%m/%d (%a) %H:%M'))
        for msg in unit['messages']:
            assert set(msg) == {'role', 'content'}, 'Unexpected labels or metadata in a message'
            assert msg['role'] in ('user', 'assistant') and isinstance(msg['content'], str)
        lines = '\n'.join(f"{m['role']}: {m['content']}" for m in unit['messages'])
        parts.append(f"[{unit['id']} | {unit['timestamp']}]\n{lines}")
    assert orders == sorted(orders) and len(set(orders)) == len(orders)
    assert dates == sorted(dates), 'Selected rounds are not in chronological order'
    assert item['context'] == '\n\n'.join(parts), 'Context differs from serialized public rounds'
    for token in ('<|im_start|>', '<|im_end|>'):
        assert token not in item['context'] and token not in item['question']
    result = {
        'status': 'passed', 'question_id': item['question_id'], 'stage': item['stage'],
        'question': item['question'], 'question_date': item['question_date'],
        'input_sha256': sha(path), 'canonical_input_sha256': canonical_sha,
        'context_sha256': hashlib.sha256(item['context'].encode()).hexdigest(),
        'round_count': len(units), 'message_count': sum(len(u['messages']) for u in units),
        'context_characters': len(item['context']), 'round_ids': [u['id'] for u in units],
        'checks': ['archived DEV membership', 'pinned input SHA256', 'public field whitelist',
                   'exact context serialization', 'unique round IDs', 'chronological order',
                   'no archived Qwen chat template'],
        'token_count_status': 'pending actual Llama tokenizer at the locked model revision',
        'budget_note': 'Historical 2048 uses Qwen tokens; this is not a Llama 2048-token assertion',
        'provenance_note': 'Manifest checked against the original archive during authoring; '
                           'no original ZIP is needed for these manifest-based checks',
    }
    return item, result


def parse_probe(text):
    result = {'job_id': None, 'gpu': None, 'memory_total_mib': None, 'driver': None,
              'python': None, 'packages': {}, 'cuda_available': None, 'torch_cuda': None}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('SLURM_JOB_ID='):
            result['job_id'] = line.split('=', 1)[1].strip()
        if line.startswith('name, memory.total') and i + 1 < len(lines):
            row = next(csv.reader([lines[i + 1]], skipinitialspace=True))
            if len(row) == 3:
                memory = re.fullmatch(r'(\d+)(?:\s+MiB)?', row[1].strip())
                result.update(gpu=row[0].strip(), memory_total_mib=int(memory[1]) if memory else None,
                              driver=row[2].strip())
        if line.startswith('Python '):
            result['python'] = line.split(' ', 1)[1]
        for name in ('torch', 'transformers', 'huggingface-hub', 'sentence-transformers'):
            if line.startswith(name + ' '):
                result['packages'][name] = line[len(name) + 1:]
        if line.startswith('cuda_available '):
            value = line.split()[-1]
            result['cuda_available'] = {'True': True, 'False': False}.get(value)
        if line.startswith('torch_cuda '):
            result['torch_cuda'] = line.split(' ', 1)[1]
    return result


def collect_records(repo, output):
    repo, output = Path(repo), Path(output)
    (output / 'prior_probes').mkdir(parents=True, exist_ok=True)
    records = []
    for stem in ('probe-48841', 'cuda-check-48855'):
        entry = {'expected_stem': stem, 'status': 'missing_raw_log', 'parsed': None}
        for suffix in ('.out', '.err'):
            source = repo / 'logs' / (stem + suffix)
            if source.exists():
                shutil.copy2(source, output / 'prior_probes' / source.name)
                if suffix == '.out':
                    parsed = parse_probe(source.read_text(encoding='utf-8', errors='replace'))
                    entry.update(status='parsed_raw_log' if parsed['gpu'] and parsed['job_id'] else 'unrecognized_log',
                                 parsed=parsed, stdout_sha256=sha(source))
        records.append(entry)
    write_json(output / 'prior_probe_records.json', records)
    current_probe = output / 'current_probe.out'
    current_gpu_record = (parse_probe(current_probe.read_text(encoding='utf-8', errors='replace'))
                          if current_probe.exists() else {'status': 'no_current_compute_probe'})
    write_json(output / 'current_probe_record.json', current_gpu_record)
    packages = {}
    for name in ('torch', 'transformers', 'huggingface-hub', 'accelerate', 'safetensors',
                 'nbformat', 'nbconvert', 'ipykernel'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = 'not installed in current execution environment'
    environment = {
        'recorded_utc': datetime.now(timezone.utc).isoformat(),
        'record_scope': 'current notebook kernel environment; GPU facts are only in raw probe logs or generation records',
        'python': platform.python_version(), 'executable': sys.executable,
        'platform': platform.platform(), 'hostname': platform.node(), 'packages': packages,
        'current_compute_probe': current_gpu_record,
        'git_commit': command(['git', 'rev-parse', 'HEAD'], repo),
        'git_branch': command(['git', 'branch', '--show-current'], repo),
        'git_status': command(['git', 'status', '--short'], repo),
        'file_sha256': {str(p.relative_to(repo)): sha(p) for p in
                        [repo / 'e01/input_dev.json', repo / 'e01/run_generation.py',
                         repo / 'e01/notebook_utils.py', repo / 'e01/E01_environment_and_generation.ipynb']},
    }
    write_json(output / 'preparation_environment.json', environment)
    freeze = command([sys.executable, '-m', 'pip', 'freeze'], repo)
    (output / 'pip_freeze.txt').write_text(freeze['stdout'], encoding='utf-8')
    write_json(output / 'pip_check.json', command([sys.executable, '-m', 'pip', 'check'], repo))
    write_json(output / 'slurm_accounting.json', command(
        ['sacct', '-j', '48841,48855', '-P', '--format=JobID,State,ExitCode,Submit,Start,Elapsed,MaxRSS'], repo))
    return environment, records


def write_report(output, audit, records, generation=None):
    output = Path(output)
    status = '准备检查通过，尚未完成真实生成' if generation is None else '已产生真实输出，待人工核对'
    if generation and (generation.get('hit_output_limit') or not generation.get('nonempty_output')):
        status = '生成需要复查：输出为空或触及上限'
    lines = ['# E01 实验记录', '', f'状态：{status}', '',
             f"开发题：`{audit['question_id']}`", f"输入 SHA256：`{audit['input_sha256']}`", '',
             '## 开发输入', '', f"完整原文轮次：{audit['round_count']}；消息：{audit['message_count']}。",
             '结构、来源清单、哈希、顺序和原文拼接检查通过。未把参考答案或旧输出作为新回答。',
             '当前材料的旧 2048 Token 预算使用 Qwen tokenizer；Llama Token 数在模型阶段实测。', '',
             '## 已有探测记录', '']
    for entry in records:
        p = entry.get('parsed')
        if entry['status'] != 'parsed_raw_log':
            lines.append(f"- {entry['expected_stem']}：原始日志缺失或未识别，不能作为已核实记录。")
        else:
            lines.append(f"- 作业 {p['job_id']}：{p['gpu']}，{p['memory_total_mib']} MiB，驱动 {p['driver']}；"
                         f"CUDA available={p['cuda_available']}。每个作业保留自己的设备身份。")
    lines += ['', '## 模型与生成', '']
    if generation is None:
        lines += ['模型访问、完整 revision、输入输出 Token、真实输出、生成耗时、吞吐量和峰值显存：待实测。']
    else:
        lines += ['配置与实际 GPU：见 `generation/config.json` 和 `generation/environment.json`。',
                  '完整输入输出：见 `generation/prompt.txt` 和 `generation/output.txt`。', '',
                  '```json', json.dumps(generation, ensure_ascii=False, indent=2), '```']
    lines += ['', '## 人工核对（执行后填写）', '',
              '- [ ] 已打开完整输入和输出，确认非空并检查截断。',
              '- [ ] 已核对模型 SHA、tokenizer SHA、精度和实际作业 GPU。',
              '- [ ] 已区分排队、下载/加载、warmup 与生成时间。',
              '- [ ] 已填写实际产物路径并交付全员。', '',
              '本次为 E01 直接回答试跑；E02 的 D02 材料与官方多次调用 CoN 流程仍待接入。',
              '输入结构检查和生成成功均不等于答案已经完成评分。', '']
    (output / 'REPORT_CN.md').write_text('\n'.join(lines), encoding='utf-8')
