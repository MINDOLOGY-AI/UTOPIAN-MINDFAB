import shutil
import uuid
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from mind.interp_journey.function_approximator.back import config

# in-memory model store: session_id -> metadata dict (includes "model" key)
_SESSIONS: dict[str, dict] = {}


def register(session_id: str, meta: dict) -> None:
    _SESSIONS[session_id] = meta


def get(session_id: str) -> dict | None:
    return _SESSIONS.get(session_id)


def delete(session_id: str) -> None:
    if session_id in _SESSIONS:
        del _SESSIONS[session_id]
    session_dir = config.DATA_DIR / "*" / session_id
    for path in config.DATA_DIR.rglob(session_id):
        if path.is_dir():
            shutil.rmtree(path)


def predict(session_id: str, x: np.ndarray) -> np.ndarray:
    meta = _SESSIONS[session_id]
    model = meta["model"]
    model.eval()
    with torch.no_grad():
        xt = torch.as_tensor(x, dtype=config.DTYPE, device=config.DEVICE)
        out = model(xt)
    return out.cpu().numpy()


def _get_linear_layers(model: nn.Module) -> list[nn.Linear]:
    return [layer for layer in model.blocks if isinstance(layer, nn.Linear)]


def _linear_positions(model: nn.Module) -> list[int]:
    return [i for i, layer in enumerate(model.blocks) if isinstance(layer, nn.Linear)]


def literal_neurons(session_id: str) -> dict:
    """Return encoder rows (first linear layer) and decoder columns (last linear layer)."""
    meta = _SESSIONS[session_id]
    model = meta["model"]
    layers = _get_linear_layers(model)
    encoder = layers[0]
    decoder = layers[-1]
    return {
        "encoder": {
            "weight": encoder.weight.detach().cpu().numpy().tolist(),
            "bias": encoder.bias.detach().cpu().numpy().tolist(),
        },
        "decoder": {
            "weight": decoder.weight.detach().cpu().numpy().tolist(),
            "bias": decoder.bias.detach().cpu().numpy().tolist(),
        },
    }


def set_neuron_weights(session_id: str, layer: str, index: int, weights: list[float], bias: float | None = None) -> None:
    """
    Update one neuron vector and optionally its bias.

    layer: "encoder" or "decoder"
    index: row index for encoder, column index for decoder
    weights: list of 2 floats
    bias: optional neuron bias
    """
    meta = _SESSIONS[session_id]
    model = meta["model"]
    layers = _get_linear_layers(model)
    encoder = layers[0]
    decoder = layers[-1]

    with torch.no_grad():
        if layer == "encoder":
            encoder.weight[index, :] = torch.as_tensor(weights, dtype=config.DTYPE, device=config.DEVICE)
            if bias is not None:
                encoder.bias[index] = torch.as_tensor(bias, dtype=config.DTYPE, device=config.DEVICE)
        elif layer == "decoder":
            decoder.weight[:, index] = torch.as_tensor(weights, dtype=config.DTYPE, device=config.DEVICE)
        else:
            raise ValueError(f"unknown layer: {layer}")


def set_decoder_bias(session_id: str, index: int, bias: float) -> None:
    """Set the bias of one output neuron in the decoder layer."""
    meta = _SESSIONS[session_id]
    model = meta["model"]
    layers = _get_linear_layers(model)
    decoder = layers[-1]
    with torch.no_grad():
        decoder.bias[index] = torch.as_tensor(bias, dtype=config.DTYPE, device=config.DEVICE)


def hyperplane_sweep(
    session_id: str,
    neuron_layer: int,
    neuron_index: int,
    grid_res: int = 100,
    value_range: tuple[float, float] = (-3.0, 3.0),
) -> dict:
    """
    Sweep inputs and record the pre-activation of one neuron.

    For hidden layers the input is first propagated through all earlier
    layers so the hyperplane is always shown over the original input space,
    composing the network layer by layer.

    neuron_layer: 0 for first linear layer, 1 for second linear layer, ...
    neuron_index: which neuron in that layer
    """
    meta = _SESSIONS[session_id]
    model = meta["model"]
    task = meta["task"]
    layers = _get_linear_layers(model)
    positions = _linear_positions(model)

    if neuron_layer < 0 or neuron_layer >= len(layers):
        raise ValueError(f"invalid neuron_layer {neuron_layer}, model has {len(layers)} linear layers")
    if neuron_index < 0 or neuron_index >= layers[neuron_layer].out_features:
        raise ValueError(f"invalid neuron_index {neuron_index} for layer {neuron_layer}")

    lo, hi = value_range

    if task == "1d1d":
        xs = np.linspace(lo, hi, grid_res).reshape(-1, 1)
        xt = torch.as_tensor(xs, dtype=config.DTYPE, device=config.DEVICE)
        with torch.no_grad():
            pos = positions[neuron_layer]
            h = model.blocks[:pos](xt) if pos > 0 else xt
            pre = layers[neuron_layer](h)[:, neuron_index].cpu().numpy()
        # post-ReLU only if a ReLU follows this linear layer
        is_last_linear = neuron_layer == len(layers) - 1
        post = pre if is_last_linear else np.maximum(pre, 0)
        return {"x": xs.flatten().tolist(), "y": post.tolist()}

    elif task in ("2d3d", "2d3d2d"):
        xs = np.linspace(lo, hi, grid_res)
        ys = np.linspace(lo, hi, grid_res)
        xx, yy = np.meshgrid(xs, ys)
        points = np.stack([xx.ravel(), yy.ravel()], axis=1)
        xt = torch.as_tensor(points, dtype=config.DTYPE, device=config.DEVICE)
        with torch.no_grad():
            pos = positions[neuron_layer]
            h = model.blocks[:pos](xt) if pos > 0 else xt
            pre = layers[neuron_layer](h)[:, neuron_index].cpu().numpy()
        is_last_linear = neuron_layer == len(layers) - 1
        post = pre if is_last_linear else np.maximum(pre, 0)
        return {
            "x": xx.tolist(),
            "y": yy.tolist(),
            "z": post.reshape(grid_res, grid_res).tolist(),
        }
    else:
        raise ValueError(f"unsupported task: {task}")


def space_shift(
    session_id: str,
    grid_res: int = 20,
    value_range: tuple[float, float] = (-3.0, 3.0),
) -> dict:
    """
    Map a grid in input space to output space for 2d3d2d.

    Returns input grid points, corresponding output points, and the active
    ReLU mask of the first hidden layer for each grid point.
    """
    meta = _SESSIONS[session_id]
    model = meta["model"]
    task = meta["task"]

    lo, hi = value_range
    xs = np.linspace(lo, hi, grid_res)
    ys = np.linspace(lo, hi, grid_res)
    xx, yy = np.meshgrid(xs, ys)
    points = np.stack([xx.ravel(), yy.ravel()], axis=1)

    out = predict(session_id, points)
    ox = out[:, 0].reshape(grid_res, grid_res)
    oy = out[:, 1].reshape(grid_res, grid_res)

    result = {
        "input_x": xx.tolist(),
        "input_y": yy.tolist(),
        "output_x": ox.tolist(),
        "output_y": oy.tolist(),
    }

    if task == "2d3d2d":
        layers = _get_linear_layers(model)
        first_linear = layers[0]
        xt = torch.as_tensor(points, dtype=config.DTYPE, device=config.DEVICE)
        with torch.no_grad():
            pre = first_linear(xt)
            masks = (pre > 0).cpu().numpy().reshape(grid_res, grid_res, -1)
        result["masks"] = masks.astype(int).tolist()

    return result
