# helpers used across training


'''
weight saving, checkpointing, safe loading

losses: dict[str, list[float]] mapping loss name to values logged since last save.
the dict can contain multiple losses: train, eval, curriculum, etc.
always save in UTOPIAN_MINDFAB/mind/weights/project/model_name/epoch_x_batch_y.pt
save both model and optimizer, scheduler if provided
'''
import time
import json
import os.path
import math
from pathlib import Path

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
    clean_up: bool = True,
) -> None:
    assert_finite_weights(model)
    checkpoint = {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
    }
    if scheduler is not None:
        checkpoint["scheduler_state_dict"] = scheduler.state_dict()
    checkpoint_path = os.path.join(save_path, f"epoch_{epoch}_batch_{batch}.pt")
    torch.save(checkpoint, checkpoint_path)

    if clean_up:
        for old in Path(save_path).glob("*.pt"):
            if old.name != os.path.basename(checkpoint_path):
                old.unlink()

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

# safe saving: a NaN/Inf weight means training is already dead, so refuse to
# checkpoint a poisoned model instead of saving garbage
def assert_finite_weights(model) -> None:
    found_bad = False
    for name, tensor in model.state_dict().items():
        if not torch.isfinite(tensor).all():
            nan_count = torch.isnan(tensor).sum().item()
            inf_count = torch.isinf(tensor).sum().item()
            print(f"ERROR {name}: {nan_count} NaN, {inf_count} Inf")
            found_bad = True
    if found_bad:
        raise RuntimeError("model has NaN/Inf weights, refusing to save checkpoint")

def plot_losses(losses: dict[str, list[float]], out_path: str) -> None:
    names = list(losses.keys())
    n = len(names)
    if n == 0:
        return
    # fig: whole canvas. axes: individual subplots. subplots (row col, figsize (width, height))
    # n >= 1 so this always returns an ndarray of axes
    fig, axes = plt.subplots(1, n + 1, figsize=(4 * (n + 1), 4))

    colors = plt.cm.tab10
    # this x axis, a list of consecutive ints from 0 - batches_logged  
    min_len = min(len(v) for v in losses.values())
    x = list(range(min_len))

    # first plot showing all losses  
    ax_all = axes[0]
    for i, name in enumerate(names):
        ax_all.plot(x, losses[name][:min_len], marker="o", markersize=2, label=name, color=colors(i))
    ax_all.set_title("all losses")
    ax_all.legend()
    ax_all.set_xlabel("step")

    # individual loss plots  
    for i, name in enumerate(names):
        ax = axes[i + 1]
            ax.plot(x, losses[name][:min_len], marker="o", markersize=2, color=colors(i))
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
        losses,
        global_step = None,
        max_steps = None,
)->None:
    print (f"epoch {cur_epoch} batch {cur_batch} step {global_step}") 

    elapsed = time.time() - start_time
    if max_steps is not None and global_step is not None:
        total_batches_left = max(0, max_steps - global_step)
    else:
        total_batches_left = (epochs - cur_epoch - 1) * batches + (batches - cur_batch - 1)
    time_left_str = format_time(total_batches_left * elapsed)
    print (f"time left {time_left_str}")
    for key, value in losses.items():
        print (f"{key} : {value[-1]}")
