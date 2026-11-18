"""Download the fixed E03 model revision into this package's HF_HOME cache."""
from huggingface_hub import snapshot_download

path = snapshot_download(
    repo_id='meta-llama/Llama-3.1-8B-Instruct',
    revision='0e9e39f249a16976918f6564b8830bc894c89659',
    allow_patterns=['*.json', '*.safetensors', '*.model', '*.jinja', '*.txt'],
    max_workers=2,
)
print('Pinned model cached:', path)
