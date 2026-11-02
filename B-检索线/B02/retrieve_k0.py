#!/usr/bin/env python3
"""B02: rank the first five A01 public histories with the official Stella K0 method."""
import argparse
import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A01 = ROOT / "A-数据线/A01/output"
TOKENIZER = "meta-llama/Llama-3.1-8B-Instruct"


def read_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def load_inputs():
    manifest = json.loads((A01 / "dev_manifest.json").read_text(encoding="utf-8"))
    ids = [entry["question_id"] for entry in manifest["first_batch"]]
    questions = {x["question_id"]: x for x in read_jsonl(A01 / "public/dev_questions.jsonl")}
    if len(ids) != 5 or len(set(ids)) != 5:
        raise ValueError("Expected five distinct first-batch questions")
    result = []
    for qid in ids:
        question = questions[qid]
        turns = read_jsonl(A01 / "public/turns" / f"{qid}.jsonl")
        turn_ids = [turn["turn_id"] for turn in turns]
        if len(turn_ids) < 100 or len(set(turn_ids)) != len(turn_ids):
            raise ValueError(f"{qid}: expected at least 100 distinct turns")
        for turn in turns:
            messages = turn["messages"]
            if not messages or messages[0]["role"] != "user":
                raise ValueError(f"{turn['turn_id']}: first message is not a user message")
            if any(key in turn for key in ("official_corpus_id", "has_answer", "question_type")):
                raise ValueError("Unexpected protected field in public turns")
        result.append((question, turns))
    return manifest, result


def load_model(model_dir, device):
    import torch
    from transformers import AutoModel, AutoTokenizer

    projection = model_dir / "2_Dense_1024/pytorch_model.bin"
    if not projection.is_file():
        raise FileNotFoundError(f"Official Stella projection missing: {projection}")
    model = AutoModel.from_pretrained(str(model_dir), trust_remote_code=True, local_files_only=True).to(device)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), trust_remote_code=True, local_files_only=True)
    linear = torch.nn.Linear(model.config.hidden_size, 1024).to(device)
    weights = torch.load(projection, map_location="cpu", weights_only=True)
    linear.load_state_dict({key.replace("linear.", ""): value for key, value in weights.items()})
    linear.eval()
    return tokenizer, model, linear


def embed(texts, tokenizer, model, linear, batch_size):
    import torch
    from sklearn.preprocessing import normalize
    import numpy as np

    vectors = []
    with torch.no_grad():
        for start in range(0, len(texts), batch_size):
            inputs = tokenizer(texts[start:start + batch_size], padding="longest", truncation=True,
                               max_length=512, return_tensors="pt")
            inputs = {key: value.to(model.device) for key, value in inputs.items()}
            mask = inputs["attention_mask"]
            hidden = model(**inputs)[0].masked_fill(~mask[..., None].bool(), 0.0)
            pooled = hidden.sum(dim=1) / mask.sum(dim=1)[..., None]
            vectors.append(normalize(linear(pooled).detach().cpu()))
    return np.concatenate(vectors, axis=0)


def write_jsonl_atomic(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        tmp = stream.name
        try:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        except Exception:
            os.unlink(tmp)
            raise
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, help="Local Stella model directory")
    parser.add_argument("--output", type=Path, help="Output JSONL file")
    parser.add_argument("--batch-size", type=int, default=64, help="Official default: 64")
    parser.add_argument("--validate-inputs", action="store_true", help="Check A01 input without GPU")
    args = parser.parse_args()
    manifest, items = load_inputs()
    for question, turns in items:
        print(f"{question['question_id']}: {len(turns)} public turns", flush=True)
    if args.validate_inputs:
        return
    if args.model_dir is None or args.output is None or args.batch_size < 1:
        parser.error("--model-dir and --output are required; batch size must be positive")
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU not available; use --validate-inputs for a CPU input check")
    tokenizer, model, linear = load_model(args.model_dir, torch.device("cuda:0"))
    rows = []
    for question, turns in items:
        start = time.monotonic()
        qvec = embed([question["question"]], tokenizer, model, linear, 1)
        dvec = embed([turn["messages"][0]["content"] for turn in turns], tokenizer, model, linear, args.batch_size)
        scores = torch.tensor((qvec @ dvec.T).squeeze(0))
        ranks = scores.argsort(descending=True)[:100].tolist()
        candidates = [{"turn_id": turns[i]["turn_id"], "rank": rank, "score": float(scores[i])}
                      for rank, i in enumerate(ranks, 1)]
        rows.append({"question_id": question["question_id"], "stage": "dev", "index": "K0",
                     "strategy": None, "budget_tokens": 2048, "tokenizer": TOKENIZER,
                     "config_version": manifest["config_version"], "candidates": candidates})
        print(f"{question['question_id']}: {len(candidates)} ranked in {time.monotonic() - start:.1f}s", flush=True)
    write_jsonl_atomic(args.output, rows)
    print(f"Wrote {len(rows)} questions to {args.output}", flush=True)


if __name__ == "__main__":
    main()
