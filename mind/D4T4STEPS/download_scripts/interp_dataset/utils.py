import os
from pathlib import Path
from mind.D4T4STEPS.config import HF_MIRROR, OUTPUT_DIR

os.environ["HF_ENDPOINT"] = HF_MIRROR

from datasets import load_dataset

SHARD_DOCS = 10_000
DOC_SPLIT = "--DOCSPLIT--"


def stream_to_text(dataset_name, target_tokens, *, dataset_id, text_field="text",
                   config=None, data_dir=None, split="train", filter_fn=None, format_fn=None):
    out_dir = OUTPUT_DIR / dataset_name
    out_dir.mkdir(parents=True, exist_ok=True)

    existing_shards = sorted(out_dir.glob("shard_*.txt"))
    existing_docs = 0
    total_chars = 0
    if existing_shards:
        for s in existing_shards:
            text = s.read_text()
            docs = [d for d in text.split(DOC_SPLIT) if d.strip()]
            existing_docs += len(docs)
            total_chars += len(text)
        shard_idx = len(existing_shards)
        tokens_est = total_chars // 4
        if tokens_est >= target_tokens:
            print(f"  {dataset_name}: already complete — ~{tokens_est:,} tokens ({shard_idx} shards)")
            return
        print(f"  {dataset_name}: resuming — ~{tokens_est:,} tokens from {existing_docs:,} docs in {shard_idx} shards")
    else:
        shard_idx = 0

    ds = load_dataset(dataset_id, config, data_dir=data_dir, split=split, streaming=True, trust_remote_code=True)
    if filter_fn is not None:
        ds = ds.filter(filter_fn)
    if existing_docs > 0:
        ds = ds.skip(existing_docs) 

    buf = []  # [str]

    for row in ds:
        if format_fn is not None:
            text = format_fn(row)
        else:
            text = row.get(text_field, "")
        if not text or not text.strip():
            continue
        buf.append(text.strip())
        total_chars += len(text)

        if len(buf) >= SHARD_DOCS:
            shard_idx += 1
            _write_shard(out_dir, shard_idx, buf)
            tokens_est = total_chars // 4
            buf = []
            print(f"  {dataset_name}: shard {shard_idx:04d} | ~{tokens_est:,} tokens")
            if tokens_est >= target_tokens:
                print(f"  {dataset_name}: target reached — ~{tokens_est:,} tokens ({shard_idx} shards)")
                return

    if buf:
        shard_idx += 1
        _write_shard(out_dir, shard_idx, buf)
    print(f"  {dataset_name}: stream exhausted — ~{total_chars // 4:,} tokens ({shard_idx} shards)")


def _write_shard(out_dir, idx, docs):
    path = out_dir / f"shard_{idx:04d}.txt"
    path.write_text(DOC_SPLIT.join(docs))
