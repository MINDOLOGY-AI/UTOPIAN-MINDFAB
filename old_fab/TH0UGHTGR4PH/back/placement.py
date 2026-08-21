from fab.TH0UGHTGR4PH.back.config import GRID_SIZE

# autoplacement for MODEL-created nodes only (graph actions without explicit x/y).
# placement is per-PARENT: root nodes go right of the rightmost root column
# (left-to-right DAG style), folder children stack down the folder's first
# column (matching the frontend's freeChildPosition). never touches existing
# node positions — user placement is sacred.


def _occupied(meta, parent) -> set:
    # grid cells taken by the nodes in this placement space (one parent)
    cells = set()
    for n in meta["nodes"].values():
        if n["parent"] == parent:
            cells.add((round(n["x"] / GRID_SIZE), round(n["y"] / GRID_SIZE)))
    return cells


def _first_free_lane(cells, col, start_lane=0):
    lane = start_lane
    while (col, lane) in cells:
        lane += 1
    return lane


def next_position(meta, near: str | None = None, parent: str | None = None) -> dict:
    """Compute the next free (x, y) for a new node, in the coordinate space of
    `parent` (folder-relative when parent is a folder id, root-absolute when None).
    `near` = id of the node it follows (only meaningful in the same space)."""
    cells = _occupied(meta, parent)
    if near and near in meta["nodes"]:
        base = meta["nodes"][near]
        if base["parent"] == parent:
            col = round(base["x"] / GRID_SIZE) + 1
            lane = _first_free_lane(cells, col, round(base["y"] / GRID_SIZE))
            return {"x": col * GRID_SIZE, "y": lane * GRID_SIZE}
    if not cells:
        return {"x": 0, "y": 0}
    if parent is not None:
        # folder children stack down the first column
        lane = _first_free_lane(cells, 0)
        return {"x": 0, "y": lane * GRID_SIZE}
    # root: right of the rightmost column, first free lane
    rightmost = max(c[0] for c in cells)
    lane = _first_free_lane(cells, rightmost + 1)
    return {"x": (rightmost + 1) * GRID_SIZE, "y": lane * GRID_SIZE}
