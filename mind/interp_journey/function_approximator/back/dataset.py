import numpy as np
import torch


def grid_to_line_function(grid: list[list[list[int]]], value_range: tuple[float, float] = (-3.0, 3.0)):
    """
    Convert a drawn line on a canvas grid into (x, y) samples.

    grid: rows x cols x 3 (rgb) drawn intensity from FreeDrawCanvas.
    For each column x, take the topmost drawn pixel as the function value y.
    Returns numpy arrays x: (N, 1), y: (N, 1).
    """
    grid = np.asarray(grid, dtype=np.float32)
    # intensity = max channel value / 255
    intensity = grid.max(axis=-1) / 255.0
    rows, cols = intensity.shape

    # find topmost drawn row per column
    ys = []
    xs = []
    for col in range(cols):
        drawn_rows = np.where(intensity[:, col] > 0.1)[0]
        if len(drawn_rows) == 0:
            continue
        # topmost = smallest row index (canvas y increases downward)
        row = drawn_rows[0]
        xs.append(col)
        ys.append(row)

    if len(xs) == 0:
        # fallback: identity line
        xs = np.linspace(0, cols - 1, cols)
        ys = np.linspace(0, rows - 1, cols)

    xs = np.asarray(xs, dtype=np.float32)
    ys = np.asarray(ys, dtype=np.float32)

    # map pixel coords to value_range
    lo, hi = value_range
    x_vals = lo + (xs / (cols - 1)) * (hi - lo)
    # y is inverted: row 0 -> hi, row rows-1 -> lo
    y_vals = hi - (ys / (rows - 1)) * (hi - lo)

    return x_vals.reshape(-1, 1), y_vals.reshape(-1, 1)


def grid_to_2d_rgb_samples(grid: list[list[list[int]]], value_range: tuple[float, float] = (-3.0, 3.0)):
    """
    Convert a 2d drawing grid into (x, y) samples for 2d -> 3d rgb.

    grid: rows x cols x 4 (rgba) from FreeDrawCanvas.
    Returns x: (N, 2), y: (N, 3) where y is the drawn rgb color in [0, 1].
    """
    grid = np.asarray(grid, dtype=np.float32)
    rows, cols = grid.shape[:2]
    lo, hi = value_range

    xs = []
    ys = []
    for row in range(rows):
        for col in range(cols):
            x = lo + (col / (cols - 1)) * (hi - lo)
            y = hi - (row / (rows - 1)) * (hi - lo)
            xs.append([x, y])
            # rgba -> rgb normalized to [0, 1]
            ys.append(grid[row, col, :3] / 255.0)

    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32)


def pairs_to_2d3d2d(
    inputs: list[tuple[float, float]],
    outputs: list[tuple[float, float]],
    value_range: tuple[float, float] = (-3.0, 3.0),
):
    """
    Convert input/output pairs into training arrays for 2d -> 3d -> 2d.

    inputs: list of (x1, x2)
    outputs: list of (y1, y2)
    Returns x: (N, 2), y: (N, 2).
    """
    x = np.asarray(inputs, dtype=np.float32)
    y = np.asarray(outputs, dtype=np.float32)
    assert x.shape[1] == 2, f"inputs must be 2d, got shape {x.shape}"
    assert y.shape[1] == 2, f"outputs must be 2d, got shape {y.shape}"
    return x, y


def make_tensors(x: np.ndarray, y: np.ndarray, device, dtype):
    return torch.as_tensor(x, dtype=dtype, device=device), torch.as_tensor(y, dtype=dtype, device=device)
