import json
import time
import uuid
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn

from torch.utils.data import DataLoader

from mind.SYN4P5E.algorithms.basic.MLP import MLP
from mind.SYN4P5E.train.data_to_loaders import NumpySupervisedDataset
from mind.interp_journey.function_approximator.back import config


def _plot_losses(losses: list[float], out_path: Path) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(6, 4))
    ax.plot(range(len(losses)), losses, color="#B8A0FF", linewidth=1.5)
    ax.set_title("train loss")
    ax.set_xlabel("step")
    ax.set_ylabel("loss")
    ax.set_facecolor("none")
    fig.patch.set_alpha(0)
    ax.tick_params(colors="white")
    ax.xaxis.label.set_color("white")
    ax.yaxis.label.set_color("white")
    ax.title.set_color("white")
    ax.spines["bottom"].set_color("white")
    ax.spines["top"].set_color("white")
    ax.spines["left"].set_color("white")
    ax.spines["right"].set_color("white")
    plt.tight_layout()
    plt.savefig(out_path, transparent=True)
    plt.close(fig)


def train_model(
    task: str,
    dims: tuple[int, ...],
    epochs: int,
    lr: float,
    batch_size: int,
    x: np.ndarray,
    y: np.ndarray,
) -> dict:
    """
    Train an MLP on the provided (x, y) data.

    Returns dict with session_id, loss_curve, loss_image_path, final_loss.
    """
    session_id = str(uuid.uuid4())
    save_dir = config.DATA_DIR / task / session_id
    save_dir.mkdir(parents=True, exist_ok=True)

    model = MLP(dims).to(config.DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    dataset = NumpySupervisedDataset(x, y)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=False)

    losses_log: list[float] = []
    model.train()

    for cur_epoch in range(epochs):
        if len(dataloader) == 0:
            continue
        for batch_x, batch_y in dataloader:
            batch_x = batch_x.to(config.DEVICE, dtype=config.DTYPE)
            batch_y = batch_y.to(config.DEVICE, dtype=config.DTYPE)

            pred = model(batch_x)
            loss = loss_fn(pred, batch_y)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            losses_log.append(loss.item())

    # save losses.json and plot
    with open(save_dir / "losses.json", "w") as f:
        json.dump({"train": losses_log}, f)

    loss_image_path = save_dir / "losses.png"
    if losses_log:
        _plot_losses(losses_log, loss_image_path)

    final_loss = losses_log[-1] if losses_log else float("inf")

    return {
        "session_id": session_id,
        "task": task,
        "dims": dims,
        "loss_curve": losses_log,
        "loss_image_path": str(loss_image_path),
        "final_loss": final_loss,
        "model": model,
        "x_range": (float(x.min()), float(x.max())),
        "y_range": (float(y.min()), float(y.max())),
    }
