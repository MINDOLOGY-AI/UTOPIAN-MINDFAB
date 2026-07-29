from fab.TH0UGHTGR4PH.back.config import GRID_SIZE

# autoplacement for MODEL-created nodes only (graph actions without explicit x/y).
# left-to-right DAG style: a node goes one column right of the deepest node it
# follows (its `near` node, else the rightmost node on the board), at the first
# free y-lane. never touches existing node positions — user placement is sacred.


def _occupied(meta) -> set:
    # grid cells taken by existing nodes (collapsed footprint = 1 cell)
    cells = set()
    for n in meta["nodes"].values():
        cells.add((round(n["x"] / GRID_SIZE), round(n["y"] / GRID_SIZE)))
    return cells


def _first_free_lane(cells, col, start_lane=0):
    lane = start_lane
    while (col, lane) in cells:
        lane += 1
    return lane


def next_position(meta, near: str | None = None) -> dict:
    """Compute the next free (x, y) for a new node. `near` = id of the node it follows."""
    cells = _occupied(meta)
    if near and near in meta["nodes"]:
        base = meta["nodes"][near]
        col = round(base["x"] / GRID_SIZE) + 1
        lane = _first_free_lane(cells, col, round(base["y"] / GRID_SIZE))
        return {"x": col * GRID_SIZE, "y": lane * GRID_SIZE}
    if not cells:
        return {"x": 0, "y": 0}
    # no anchor: right of the rightmost column, first free lane
    rightmost = max(c[0] for c in cells)
    lane = _first_free_lane(cells, rightmost + 1)
    return {"x": (rightmost + 1) * GRID_SIZE, "y": lane * GRID_SIZE}
