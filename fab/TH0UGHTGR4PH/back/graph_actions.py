"""Model-callable graph actions — the layer INT3RF4CE agents use to operate F4B boards.

Host-side direct calls (no HTTP): agent.py dispatches G* commands here.
All functions raise ValueError on bad input; the agent turns that into a tool_result error.
"""

from fab.TH0UGHTGR4PH.back.config import GRID_SIZE
from fab.TH0UGHTGR4PH.back.placement import next_position
from fab.TH0UGHTGR4PH.back import storage

KINDS = ("obj", "func", "folder")
STATES = ("todo", "doing", "done")
MAX_CONTENT_CHARS = 100_000


def _validate_type(user: str, kind: str, node_type: str):
    types = storage.load_types(user)
    registry = types["obj_types"] if kind == "obj" else types["func_types"]
    if kind != "folder" and node_type not in registry:
        raise ValueError(f"unknown {kind} type '{node_type}'. known: {sorted(registry)}")


def _validate_state(state):
    if state is not None and state not in STATES:
        raise ValueError(f"state must be one of {STATES} or null")


def resolve_node(meta, ref: str) -> str:
    """Resolve a node reference (id, or unique title) to a node id."""
    if ref in meta["nodes"]:
        return ref
    matches = [nid for nid, n in meta["nodes"].items() if n["title"] == ref]
    if not matches:
        raise ValueError(f"node not found: {ref!r}")
    if len(matches) > 1:
        raise ValueError(f"ambiguous node title {ref!r} ({len(matches)} matches) — use the id")
    return matches[0]


def _require_board(user: str, board: str):
    if board not in storage.list_boards(user):
        raise ValueError(f"board not found: {board!r}")


def create_node(user: str, board: str, title: str, kind: str, node_type: str,
                parent: str | None = None, state: str | None = None,
                ref: str | None = None, near: str | None = None,
                x: float | None = None, y: float | None = None) -> dict:
    _require_board(user, board)
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not title or not title.strip():
        raise ValueError("title cannot be empty")
    _validate_type(user, kind, node_type)
    _validate_state(state)
    meta = storage.load_meta(user, board)
    if parent is not None:
        parent = resolve_node(meta, parent)
        if meta["nodes"][parent]["kind"] != "folder":
            raise ValueError("parent must be a folder")
    if x is None or y is None:
        pos = next_position(meta, resolve_node(meta, near) if near else None)
        x, y = pos["x"], pos["y"]
    nid = storage.new_id(meta["nodes"])
    # root nodes snap to the grid; child coordinates are relative to their folder
    if parent is None:
        x = round(float(x) / GRID_SIZE) * GRID_SIZE
        y = round(float(y) / GRID_SIZE) * GRID_SIZE
    else:
        x = int(round(float(x)))
        y = int(round(float(y)))
    node = {
        "id": nid,
        "title": title.strip(),
        "kind": kind,
        "node_type": node_type,
        "state": state,
        "ref": ref,
        "x": x,
        "y": y,
        "width": 560,
        "height": 360,
        "parent": parent,
        "expanded": False,
        "color": None,
    }
    meta["nodes"][nid] = node
    storage.save_meta(user, board, meta)
    return node


def read_node(user: str, board: str, ref: str) -> dict:
    """Return the node, its content, and its directly connected nodes."""
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    nid = resolve_node(meta, ref)
    node = meta["nodes"][nid]
    connected = []
    for e in meta["edges"].values():
        other = None
        direction = None
        if e["source"] == nid:
            other, direction = e["target"], "out"
        elif e["target"] == nid:
            other, direction = e["source"], "in"
        if other and other in meta["nodes"]:
            o = meta["nodes"][other]
            connected.append({
                "edge_id": e["id"], "direction": direction, "id": o["id"],
                "title": o["title"], "kind": o["kind"], "node_type": o["node_type"],
                "state": o["state"],
            })
    return {
        "node": node,
        "content": storage.read_content(user, board, nid),
        "connected": connected,
    }


def update_node(user: str, board: str, ref: str, title: str | None = None,
                node_type: str | None = None, state: str | None = ...,  # ... = leave unchanged
                content: str | None = None) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    nid = resolve_node(meta, ref)
    node = meta["nodes"][nid]
    if title is not None:
        if not title.strip():
            raise ValueError("title cannot be empty")
        node["title"] = title.strip()
    if node_type is not None:
        _validate_type(user, node["kind"], node_type)
        node["node_type"] = node_type
    if state is not ...:
        _validate_state(state)
        node["state"] = state
    if content is not None:
        if len(content) > MAX_CONTENT_CHARS:
            raise ValueError(f"content too large (max {MAX_CONTENT_CHARS} chars)")
        storage.write_content(user, board, nid, content)
    storage.save_meta(user, board, meta)
    return node


def destroy_node(user: str, board: str, ref: str) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    nid = resolve_node(meta, ref)
    to_delete = {nid}
    stack = [nid]
    while stack:
        cur = stack.pop()
        for o_id, n in meta["nodes"].items():
            if n["parent"] == cur and o_id not in to_delete:
                to_delete.add(o_id)
                stack.append(o_id)
    for o_id in to_delete:
        del meta["nodes"][o_id]
        storage.delete_content(user, board, o_id)
    meta["edges"] = {
        eid: e for eid, e in meta["edges"].items()
        if e["source"] not in to_delete and e["target"] not in to_delete
    }
    storage.save_meta(user, board, meta)
    return {"deleted": sorted(to_delete)}


def move_node(user: str, board: str, ref: str, x: float | None = None,
              y: float | None = None, parent: str | None = ...) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    nid = resolve_node(meta, ref)
    node = meta["nodes"][nid]
    if x is not None:
        # root nodes snap to grid; children use relative coords inside the folder
        if node["parent"] is None:
            node["x"] = round(float(x) / GRID_SIZE) * GRID_SIZE
        else:
            node["x"] = int(round(float(x)))
    if y is not None:
        if node["parent"] is None:
            node["y"] = round(float(y) / GRID_SIZE) * GRID_SIZE
        else:
            node["y"] = int(round(float(y)))
    if parent is not ...:
        if parent is None:
            node["parent"] = None
        else:
            parent = resolve_node(meta, parent)
            if meta["nodes"][parent]["kind"] != "folder":
                raise ValueError("parent must be a folder")
            p = parent
            while p is not None:
                if p == nid:
                    raise ValueError("cannot move a node into its own subtree")
                p = meta["nodes"][p]["parent"]
            node["parent"] = parent
    storage.save_meta(user, board, meta)
    return node


def link(user: str, board: str, source: str, target: str) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    src = resolve_node(meta, source)
    tgt = resolve_node(meta, target)
    if src == tgt:
        raise ValueError("cannot link a node to itself")
    for e in meta["edges"].values():
        if e["source"] == src and e["target"] == tgt:
            raise ValueError("edge already exists")
    eid = storage.new_id(meta["edges"])
    edge = {"id": eid, "source": src, "target": tgt}
    meta["edges"][eid] = edge
    storage.save_meta(user, board, meta)
    return edge


def unlink(user: str, board: str, edge: str) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    if edge not in meta["edges"]:
        raise ValueError(f"edge not found: {edge!r}")
    del meta["edges"][edge]
    storage.save_meta(user, board, meta)
    return {"ok": True}


def list_board(user: str, board: str) -> dict:
    """Compact board summary for a model: every node (no content) + edge count."""
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    nodes = [
        {k: n[k] for k in ("id", "title", "kind", "node_type", "state", "parent")}
        for n in meta["nodes"].values()
    ]
    nodes.sort(key=lambda n: (n["kind"], n["title"]))
    return {"board": board, "nodes": nodes, "edges": len(meta["edges"])}
