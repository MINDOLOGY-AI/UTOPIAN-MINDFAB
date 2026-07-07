'''
helpers used across training
'''


'''
weight saving, checkpointing, safe loading

losses: dict[str, list[float]] mapping loss name to values logged since last save.
the dict can contain multiple losses: train, eval, curriculum, etc.
always save in UTOPIAN_MINDFAB/weights/project/model_name/epoch_x_batch_y.pt
save both model and optimizer, scheduler if provided
'''
import time
import json
import os.path
import math

import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from torch.utils.data import Dataset, DataLoader, Subset

def save_checkpoint(
    save_path: str,
    model,
    optimizer,
    scheduler,
    epoch: int,
    batch: int,
    losses: dict[str, list[float]],
) -> None:
    checkpoint = {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
    }
    if scheduler is not None:
        checkpoint["scheduler_state_dict"] = scheduler.state_dict()
    checkpoint_path = os.path.join(save_path, f"epoch_{epoch}_batch_{batch}.pt")
    torch.save(checkpoint, checkpoint_path)

    losses_json_path = os.path.join(save_path, "losses.json")
    if os.path.exists(losses_json_path):
        with open(losses_json_path, "r") as f:
            existing = json.load(f)
        for name, values in losses.items():
            existing.setdefault(name, []).extend(values)
        all_losses = existing
    else:
        all_losses = losses

    with open(losses_json_path, "w") as f:
        json.dump(all_losses, f)

    # plot losses
    plot_losses(all_losses, os.path.join(save_path, "losses.png"))

def plot_losses(losses: dict[str, list[float]], out_path: str) -> None:
    names = list(losses.keys())
    n = len(names)
    if n == 0:
        return
    # fig: whole canvas. axes: individual subplots. subplots (row col, figsize (width, height))
    fig, axes = plt.subplots(1, n + 1, figsize=(4 * (n + 1), 4))
    if n == 1:
        axes = [axes]

    colors = plt.cm.tab10
    # this x axis, a list of consecutive ints from 0 - batches_logged  
    x = list(range(len(losses[names[0]])))

    # first plot showing all losses  
    ax_all = axes[0]
    for i, name in enumerate(names):
        ax_all.plot(x, losses[name], marker="o", markersize=2, label=name, color=colors(i))
    ax_all.set_title("all losses")
    ax_all.legend()
    ax_all.set_xlabel("step")

    # individual loss plots  
    for i, name in enumerate(names):
        ax = axes[i + 1]
        ax.plot(x, losses[name], marker="o", markersize=2, color=colors(i))
        ax.set_title(name)
        ax.set_xlabel("step")

    plt.tight_layout()
    plt.savefig(out_path)
    plt.close(fig)


# time formatting, logging, estimating unused time
def format_time(seconds):
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    parts = []
    if d: parts.append(f"{d}d ")
    if h: parts.append(f"{h}h ")
    if m: parts.append(f"{m}m ")
    parts.append(f"{s}s")
    return " ".join(parts)


# logging losses and estimate time
# assume losses is already appeneded in training function

def log_batch(
        start_time: float,
        cur_epoch,
        cur_batch,
        epochs,
        batches,
        losses
)->None:
    print (f"epoch {cur_epoch} batch {cur_batch}") 

    elapsed = time.time() - start_time
    total_batches_left = (epochs - cur_epoch - 1) * batches + (batches - cur_batch - 1)
    time_left_str = format_time(total_batches_left * elapsed)
    print (f"time left {time_left_str}")
    for key, value in losses.items():
        print (f"{key} : {value[-1]}")



# Deterministic per-epoch shuffle with fast resume by skipping batches.
# Use pin_memory to move data from RAM to VRAM faster during training.
# num_workers > 0 fetches multiple batches ahead in parapllel
# set to num_workers to (time_to_load / time_to_train). want training and loading rates to be equal  
def dataset_to_dataloader(
    dataset: Dataset,
    batch_size: int,
    cur_epoch: int = 0,
    start_batch: int = 0,
    num_workers: int = 2,
) -> DataLoader:
    seed = 21 # hard code seed = 21
    generator = torch.Generator().manual_seed(seed + cur_epoch)
    # use set generator to ensure the same results when we pause and resume
    indices = torch.randperm(len(dataset), generator=generator).tolist() #type: ignore  

    # fast skip. if normal iterate through skip then it's very slow because it actually loads everything.  
    start_idx = start_batch * batch_size
    if start_idx > 0:
        indices = indices[start_idx:]

    subset = Subset(dataset, indices)
    return DataLoader(
        subset,
        batch_size=batch_size,
        shuffle=False, # we already shuffled
        num_workers=num_workers,
        prefetch_factor=2, # how much each worker loads
        pin_memory=True, #  makes moving to vram faster
        drop_last=True, #  drops last incomplete batch.
    )

class NumpySupervisedDataset(Dataset):
    # x: (N, ...) and y: (N, ...) kept in RAM.
    def __init__(self, x: np.ndarray, y: np.ndarray):
        assert len(x) == len(y), f"x and y must have same length, got {len(x)} and {len(y)}"
        self.x = x
        self.y = y

    def __len__(self) -> int:
        return len(self.x)

    def __getitem__(self, idx: int):
        # workers read from the same numpy array; as_tensor handles both ndarray slices and scalars.
        return torch.as_tensor(self.x[idx]), torch.as_tensor(self.y[idx])


class BinUnsupervisedDataset(Dataset):
    # streams each sample from a flat binary file on disk.
    # shape includes N first, e.g. (N, seq_len) for token ids.
    def __init__(self, path: str, dtype: torch.dtype, shape: tuple[int, ...]):
        assert len(shape) >= 1, "shape must include the sample count dimension"

        self.path = path
        self.dtype = dtype
        self.shape = shape
        self.num_samples = shape[0]
        self.sample_shape = shape[1:]
        self.sample_numel = math.prod(self.sample_shape)
        self.sample_bytes = self.sample_numel * torch.empty(0, dtype=dtype).element_size()

        expected_size = self.num_samples * self.sample_bytes
        actual_size = os.path.getsize(path)
        assert actual_size == expected_size, (
            f"file size mismatch: {path} is {actual_size} bytes, expected {expected_size} "
            f"for shape {shape} and dtype {dtype}"
        )

    def __len__(self) -> int:
        return self.num_samples

    def __getitem__(self, idx: int):
        assert 0 <= idx < self.num_samples
        offset = idx * self.sample_bytes
        with open(self.path, "rb") as f:
            f.seek(offset)
            raw = f.read(self.sample_bytes)
        # frombuffer views immutable bytes, so clone into writable tensor memory.
        return torch.frombuffer(raw, dtype=self.dtype).reshape(self.sample_shape).clone()
