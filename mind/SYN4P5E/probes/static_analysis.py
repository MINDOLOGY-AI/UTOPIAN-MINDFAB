# statically analyzes the properties of a layer:
# analyze both row and column order
# magitude: mean, std, centroid, distribution graph
# directions (study normalized version): mean, clusters?
# orthogonality: welsh ratio  

import torch
import torch.nn as nn
import json
from typing import Dict, Any


def _views(weight: torch.Tensor):
    """Return (row_view, col_view) for a weight tensor."""
    w = weight.detach().cpu().float()
    if w.dim() == 1:
        # 1D params (e.g. LayerNorm scale): each element is a row-neuron
        row = w.view(-1, 1)
        col = w.view(1, -1)
    else:
        # each output neuron / filter / embedding token is a row
        row = w.view(w.size(0), -1)
        # each input neuron is a row: swap axes 0 and 1, then flatten the rest
        col = w.transpose(0, 1).contiguous().view(w.size(1), -1)
    return row, col


def _stats(t: torch.Tensor) -> Dict[str, Any]:
    # t.shape = (num, dim)
    n = t.shape[0]
    d = t.shape[1]

    # magnitude stats
    mags = torch.norm(t, dim=1)
    mag_mean = float(mags.mean())
    mag_var = float(mags.var(correction=0))

    # normalized vectors and their centroid magnitude (direction centroid)
    norms = torch.norm(t, dim=1, keepdim=True)
    directions = torch.where(norms > 0, t / norms, torch.zeros_like(t))
    direction_centroid = directions.mean(dim=0)
    direction_centroid_norm = float(torch.norm(direction_centroid))

    # welch ratio via sampled pairwise coherence
    sample = min(n, 5000)
    if n <= 2:
        mean_sq = 0.0
    else:
        idx1 = torch.randint(0, n, (sample,))
        idx2 = torch.randint(0, n, (sample,))
        mask = idx1 != idx2
        idx1, idx2 = idx1[mask][:sample // 2], idx2[mask][:sample // 2]
        dots = (directions[idx1] * directions[idx2]).sum(dim=1)
        mean_sq = float((dots ** 2).mean()) if len(dots) > 0 else 0.0

    if n > d:
        bound = (n - d) / (d * (n - 1))
        welch_ratio = mean_sq / bound
    else:
        welch_ratio = None

    return {
        "n": n,
        "d": d,
        "mag_mean": round(mag_mean, 3),
        "mag_var": round(mag_var, 3),
        "direction_centroid_norm": round(direction_centroid_norm, 3),
        "mean_sq": round(mean_sq, 3),
        "welch_ratio": round(welch_ratio, 3) if welch_ratio is not None else None,
    }


def analyze_model(model: nn.Module, path:str) -> Dict[str, Any]:
    result = {}
    for name, module in model.named_modules():
        if not hasattr(module, "weight") or module.weight is None:
            continue
        row, col = _views(module.weight)
        result[name] = {
            "type": module.__class__.__name__,
            "shape": list(module.weight.shape),
            "row": _stats(row),
            "col": _stats(col),
        }

    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    return result


# usage:
# model = DummyModel()
# data = save_json(model, "analysis.json")
# print(json.dumps(data, indent=2))





# transform analysis
# how is the avenrage vector transformed. how much direction change / magnitude change  
# what directions are squashed in down projections  
# try to describe the space shift somehow. like passing uniformly spaced apart points in and seeing how they change? or is there some smart way to well i can precompute decision boundaries, and just figure out how each lhow the intersection points transform! and with a boundary just use a pure positive direction of ones and see the orientation it faces?  

# what subspaces does most activations reside in (need dataset)
