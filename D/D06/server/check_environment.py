"""Verify the pinned reader runtime without loading weights or requiring a GPU."""
import importlib.metadata
import json
import platform

expected = dict(torch='2.6.0', transformers='4.51.3', tokenizers='0.21.4',
                **{'huggingface-hub': '0.30.2', 'accelerate': '1.6.0', 'safetensors': '0.5.3'})
actual = {name: importlib.metadata.version(name) for name in expected}
bad = {name: version for name, version in actual.items() if version.split('+')[0] != expected[name]}
if platform.python_version_tuple()[:2] != ('3', '11'):
    bad['python'] = platform.python_version()
if bad:
    raise SystemExit('Reader runtime mismatch: ' + json.dumps(bad))
print(json.dumps({'python': platform.python_version(), 'packages': actual, 'status': 'runtime_pins_passed'}, indent=2))
