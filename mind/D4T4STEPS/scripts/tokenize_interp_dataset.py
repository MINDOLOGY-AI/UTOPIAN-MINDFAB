import json
import tempfile
import numpy as np
from pathlib import Path
from mind.EV0K3.OlMo2_1b.run.loader import load_olmo2_tokenizer
from mind.D4T4STEPS.config import OUTPUT_DIR

CHUNK_SIZE = 1024
TRAIN_SPLIT = 0.7
SHUFFLE_SEED = 42
WRITE_BATCH = 10_000

TXT_DIR = OUTPUT_DIR  # mind/data/D4T4STEPS/txt/interp_dataset
OUT_DIR = Path.cwd() / "mind" / "data" / "D4T4STEPS" / "tokenized" / "interp_dataset"


def main():
    tok = load_olmo2_tokenizer()
    bos = tok.bos_token_id
    eos = tok.eos_token_id

    datasets = sorted(d for d in TXT_DIR.iterdir() if d.is_dir())
    print(f"datasets: {len(datasets)}")
    for d in datasets:
        shards = sorted(d.glob("shard_*.txt"))
        print(f"  {d.name}: {len(shards)} shards")

    tmp_path = Path(tempfile.mktemp(suffix=".bin"))
    total_tokens = 0

    print("\n--- tokenizing ---")
    with open(tmp_path, "wb") as f:
        for ds_dir in datasets:
            ds_total = 0
            for shard in sorted(ds_dir.glob("shard_*.txt")):
                text = shard.read_text()
                docs = [d.strip() for d in text.split("--DOCSPLIT--") if d.strip()]
                for doc in docs:
                    ids = [bos] + tok.encode(doc) + [eos]
                    arr = np.array(ids, dtype=np.int32)
                    arr.tofile(f)
                    ds_total += len(ids)
            total_tokens += ds_total
            print(f"  {ds_dir.name}: {ds_total:,} tokens")

    print(f"\ntotal tokens: {total_tokens:,}")

    num_chunks = total_tokens // CHUNK_SIZE
    discard = total_tokens - num_chunks * CHUNK_SIZE
    print(f"chunks: {num_chunks:,} (discarding {discard} trailing tokens)")

    tokens = np.memmap(tmp_path, dtype=np.int32, mode="r", shape=(num_chunks * CHUNK_SIZE,))
    chunks = tokens.reshape(num_chunks, CHUNK_SIZE)

    rng = np.random.default_rng(SHUFFLE_SEED)
    perm = rng.permutation(num_chunks)

    split_idx = int(num_chunks * TRAIN_SPLIT)
    train_chunks = split_idx
    eval_chunks = num_chunks - split_idx
    print(f"train: {train_chunks:,} chunks | eval: {eval_chunks:,} chunks")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n--- writing train.bin ---")
    train_path = OUT_DIR / "train.bin"
    with open(train_path, "wb") as f:
        for i in range(0, split_idx, WRITE_BATCH):
            batch_idx = perm[i:i + WRITE_BATCH]
            chunks[batch_idx].tofile(f)
            if (i // WRITE_BATCH) % 10 == 0:
                print(f"  {min(i + WRITE_BATCH, split_idx):,} / {split_idx:,}")

    print("--- writing eval.bin ---")
    eval_path = OUT_DIR / "eval.bin"
    with open(eval_path, "wb") as f:
        for i in range(0, eval_chunks, WRITE_BATCH):
            batch_idx = perm[split_idx + i:split_idx + i + WRITE_BATCH]
            chunks[batch_idx].tofile(f)
            if (i // WRITE_BATCH) % 10 == 0:
                print(f"  {min(i + WRITE_BATCH, eval_chunks):,} / {eval_chunks:,}")

    tmp_path.unlink()

    meta = {
        "train_shape": [train_chunks, CHUNK_SIZE],
        "eval_shape": [eval_chunks, CHUNK_SIZE],
        "dtype": "int32",
        "chunk_size": CHUNK_SIZE,
        "total_tokens": num_chunks * CHUNK_SIZE,
        "vocab_size": tok.vocab_size,
        "bos_id": bos,
        "eos_id": eos,
        "pad_id": tok.pad_token_id,
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"\ndone — {OUT_DIR}")


if __name__ == "__main__":
    main()
