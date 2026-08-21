"""Model-callable graph actions — the layer INT3RF4CE agents use to operate F4B boards.

Host-side direct calls (no HTTP): agent.py dispatches G* commands here.
All functions raise ValueError on bad input; the agent turns that into a tool_result error.
"""

import copy
import math

from fab.TH0UGHTGR4PH.back.config import GRID_SIZE
from fab.TH0UGHTGR4PH.back.placement import next_position
from fab.TH0UGHTGR4PH.back import storage

KINDS = ("doc", "folder")
STATES = ("todo", "doing", "done")
MAX_CONTENT_CHARS = 100_000


def _validate_type(user: str, kind: str, node_type: str):
    types = storage.load_types(user)
    if kind != "folder" and node_type not in types["doc_types"]:
        raise ValueError(f"unknown {kind} type '{node_type}'. known: {sorted(types['doc_types'])}")


def _validate_edge_type(user: str, edge_type: str):
    types = storage.load_types(user)
    if edge_type not in types["edge_types"]:
        raise ValueError(f"unknown edge type '{edge_type}'. known: {sorted(types['edge_types'])}")


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
    title = storage.validate_title(title)
    _validate_type(user, kind, node_type)
    _validate_state(state)
    meta = storage.load_meta(user, board)
    storage.require_unique_title(meta, title)
    if parent is not None:
        parent = resolve_node(meta, parent)
        if meta["nodes"][parent]["kind"] != "folder":
            raise ValueError("parent must be a folder")
    if x is None or y is None:
        pos = next_position(meta, resolve_node(meta, near) if near else None, parent=parent)
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
        "title": title,
        "kind": kind,
        "node_type": node_type,
        "state": state,
        "assignee": None,  # who claimed the task — set while state == "doing"
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
        "content": storage.read_content(user, board, meta, nid),
        "connected": connected,
    }


def _apply_state(node: dict, new_state, actor: str | None):
    """Single-assignee task rules. todo -> doing claims the task for `actor`;
    only the assignee may move a task OUT of doing (complete, release, clear).
    Contention means the task should be split, not shared."""
    if actor is None:
        raise ValueError("changing state requires an actor (who is flipping it)")
    old = node.get("state")
    assignee = node.get("assignee")
    if old == "doing" and assignee and assignee != actor:
        # covers stealing, completing, releasing AND re-claiming someone else's task
        raise ValueError(f"'{node['title']}' is being done by {assignee} — only they can change its state")
    if new_state == old:
        return
    node["assignee"] = actor if new_state == "doing" else None
    node["state"] = new_state


def update_node(user: str, board: str, ref: str, title: str | None = None,
                node_type: str | None = None, state: str | None = ...,  # ... = leave unchanged
                content: str | None = None, expanded: bool | None = None,
                actor: str | None = None) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    old_meta = copy.deepcopy(meta)  # for content-path sync after rename
    nid = resolve_node(meta, ref)
    node = meta["nodes"][nid]
    if title is not None:
        title = storage.validate_title(title)
        storage.require_unique_title(meta, title, exclude_id=nid)
        node["title"] = title
    if node_type is not None:
        _validate_type(user, node["kind"], node_type)
        node["node_type"] = node_type
    if state is not ...:
        _validate_state(state)
        _apply_state(node, state, actor)
    if expanded is not None:
        node["expanded"] = bool(expanded)
    if content is not None:
        if len(content) > MAX_CONTENT_CHARS:
            raise ValueError(f"content too large (max {MAX_CONTENT_CHARS} chars)")
        storage.write_content(user, board, meta, nid, content)
    storage.save_meta(user, board, meta)
    storage.move_content(user, board, old_meta, meta, nid)
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
    # content paths resolve through the meta — delete files before dropping nodes
    for o_id in to_delete:
        storage.delete_content(user, board, meta, o_id)
    for o_id in to_delete:
        del meta["nodes"][o_id]
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
    old_meta = copy.deepcopy(meta)  # for content-path sync after reparenting
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
            # walk up the new parent chain: refuse to move a node into its own subtree
            p = parent
            while p is not None:
                if p == nid:
                    raise ValueError("cannot move a node into its own subtree")
                p = meta["nodes"][p]["parent"]
            node["parent"] = parent
    storage.save_meta(user, board, meta)
    storage.move_content(user, board, old_meta, meta, nid)
    return node


def link(user: str, board: str, source: str, target: str, edge_type: str) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    src = resolve_node(meta, source)
    tgt = resolve_node(meta, target)
    if src == tgt:
        raise ValueError("cannot link a node to itself")
    # edges are typed argument flow between docs — containment is folder parenting
    if meta["nodes"][src]["kind"] == "folder" or meta["nodes"][tgt]["kind"] == "folder":
        raise ValueError("edges connect doc nodes, not folders — use GMOVE parent for containment")
    _validate_edge_type(user, edge_type)
    for e in meta["edges"].values():
        if e["source"] == src and e["target"] == tgt:
            raise ValueError("edge already exists")
    eid = storage.new_id(meta["edges"])
    edge = {"id": eid, "source": src, "target": tgt, "edge_type": edge_type}
    meta["edges"][eid] = edge
    storage.save_meta(user, board, meta)
    return edge


def retype_edge(user: str, board: str, edge: str, edge_type: str) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    if edge not in meta["edges"]:
        raise ValueError(f"edge not found: {edge!r}")
    _validate_edge_type(user, edge_type)
    meta["edges"][edge]["edge_type"] = edge_type
    storage.save_meta(user, board, meta)
    return meta["edges"][edge]


def unlink(user: str, board: str, edge: str) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    if edge not in meta["edges"]:
        raise ValueError(f"edge not found: {edge!r}")
    del meta["edges"][edge]
    storage.save_meta(user, board, meta)
    return {"ok": True}


def node_path(meta: dict, nid: str) -> str:
    """Folder-joined title path, e.g. mind/mech interp/train SAE."""
    parts = []
    cur = nid
    while cur:
        n = meta["nodes"][cur]
        parts.append(n["title"])
        cur = n["parent"]
    return "/".join(reversed(parts))


def gmap(user: str, board: str, ref: str | None = None, visible: set | None = None) -> str:
    """Dry graph listing — the model's primary picture of the graph.
    nodes: one per line, `path (type) [state]`, sorted by path (folders carry a
    trailing /). edges: one per line, full `path (type) [state] -(type)-> ...`.
    ref scopes to a folder's subtree (edges shown when either endpoint is
    inside); visible scopes to an access set (edges need BOTH endpoints visible).
    """
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    nodes = meta["nodes"]
    scope = None
    label = f"board '{board}'"
    if ref is not None:
        nid = resolve_node(meta, ref)
        if nodes[nid]["kind"] != "folder":
            raise ValueError("map target must be a folder")
        scope = {nid}
        stack = [nid]
        while stack:
            cur = stack.pop()
            for o_id, n in nodes.items():
                if n["parent"] == cur and o_id not in scope:
                    scope.add(o_id)
                    stack.append(o_id)
        label = f'{nodes[nid]["title"]}/ on board \'{board}\''

    def path_of(nid):
        return node_path(meta, nid)

    def fmt(nid):
        n = nodes[nid]
        p = path_of(nid) + ("/" if n["kind"] == "folder" else "")
        s = n.get("state")
        bracket = f" [doing: {n['assignee']}]" if s == "doing" and n.get("assignee") else (f" [{s}]" if s else "")
        return f"{p} ({n['node_type']}){bracket}"

    shown = [nid for nid in nodes
             if (scope is None or nid in scope) and (visible is None or nid in visible)]
    edges = [e for e in meta["edges"].values()
             if e["source"] in nodes and e["target"] in nodes
             and (visible is None or (e["source"] in visible and e["target"] in visible))
             and (scope is None or e["source"] in scope or e["target"] in scope)]

    out = [f"{label} — {len(shown)} nodes, {len(edges)} edges"]
    out.append("nodes:")
    for nid in sorted(shown, key=lambda i: path_of(i).lower()):
        out.append(f"  {fmt(nid)}")
    out.append("edges:")
    for e in sorted(edges, key=lambda e: (path_of(e["source"]).lower(), path_of(e["target"]).lower())):
        out.append(f'  {fmt(e["source"])} -({e.get("edge_type", "?")})-> {fmt(e["target"])}')
    return "\n".join(out)


def ascii_map(user: str, board: str, ref: str | None = None) -> str:
    """ASCII 'screenshot' of a folder's contents (or the root level): boxes on a
    character canvas (─│ objs, ═║ folders, ( ) funcs), a legend with ids/coords
    for GMOVE, and the edge list. One level deep — nested folders render as boxes.
    """
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    nodes = meta["nodes"]
    if ref is not None:
        nid = resolve_node(meta, ref)
        if nodes[nid]["kind"] != "folder":
            raise ValueError("map target must be a folder")
        parent = nid
        label = f'folder "{nodes[nid]["title"]}"'
    else:
        parent = None
        label = "root"
    children = [n for n in nodes.values() if n["parent"] == parent]
    if not children:
        return f"{label} on board '{board}': empty"

    G = GRID_SIZE

    def cell_rect(n):
        # (x0, y0, x1, y1) in grid-cell units, relative to this map's parent.
        # folders always render as one cell — maps are one level deep; an
        # expanded folder's true span goes in the legend instead.
        x, y = round(n["x"] / G), round(n["y"] / G)
        if n["kind"] == "doc" and n["expanded"]:
            return (x, y, x + math.ceil(n.get("width", 560) / G), y + math.ceil(n.get("height", 360) / G))
        return (x, y, x + 1, y + 1)

    def span(n):
        # true cell span of an expanded folder's contents (for the legend)
        kids = [c for c in nodes.values() if c["parent"] == n["id"]]
        if not kids:
            return (1, 1)
        rs = [cell_rect(c) for c in kids]
        return (max(r[2] for r in rs) - min(r[0] for r in rs),
                max(r[3] for r in rs) - min(r[1] for r in rs))

    rects = {n["id"]: cell_rect(n) for n in children}
    offx = min(r[0] for r in rects.values())
    offy = min(r[1] for r in rects.values())
    rects = {nid: (r[0] - offx, r[1] - offy, r[2] - offx, r[3] - offy) for nid, r in rects.items()}
    cells_x = max(r[2] for r in rects.values())
    cells_y = max(r[3] for r in rects.values())

    cw = 14 if cells_x <= 20 else 8
    ch = 4 if cells_y <= 12 else 3
    W, H = cells_x * cw + 1, cells_y * ch + 1
    oversized = W * H > 120_000
    canvas = [[" "] * W for _ in range(H)] if not oversized else None

    def put(x, y, text):
        for i, c in enumerate(text):
            if 0 <= y < H and 0 <= x + i < W:
                canvas[y][x + i] = c

    def draw_box(x0, y0, x1, y1, double=False):
        hz, vt = ("═", "║") if double else ("─", "│")
        tl, tr, bl, br = ("╔", "╗", "╚", "╝") if double else ("┌", "┐", "└", "┘")
        for cx in range(x0 + 1, x1):
            put(cx, y0, hz)
            put(cx, y1, hz)
        for cy in range(y0 + 1, y1):
            put(x0, cy, vt)
            put(x1, cy, vt)
        put(x0, y0, tl)
        put(x1, y0, tr)
        put(x0, y1, bl)
        put(x1, y1, br)

    if not oversized:
        for n in children:
            x0, y0, x1, y1 = rects[n["id"]]
            px, py = x0 * cw, y0 * ch
            pw, ph = (x1 - x0) * cw, (y1 - y0) * ch
            title = n["title"]
            draw_box(px, py, px + pw, py + ph, double=n["kind"] == "folder")
            marker = "▾ " if n["expanded"] else ("▸ " if n["kind"] == "folder" else "")
            maxw = pw - 2
            lines, cur = [], ""
            for word in (marker + title).split(" "):
                if cur and len(cur) + len(word) + 1 > maxw:
                    lines.append(cur)
                    cur = word
                else:
                    cur = f"{cur} {word}".strip()
            if cur:
                lines.append(cur)
            for i, line in enumerate(lines[: ph - 1]):
                put(px + 1, py + 1 + i, line[:maxw])

    out = [f"{label} on board '{board}' — {len(children)} children, {cells_x}x{cells_y} cells"]
    if oversized:
        out.append("(canvas too large to draw — legend below is the full layout; map a subfolder for a picture)")
    else:
        out.append("\n".join("".join(row).rstrip() for row in canvas))
    out.append("legend: id kind type (x,y) title")
    for n in sorted(children, key=lambda n: (n["y"], n["x"])):
        extra = f" spans {span(n)[0]}x{span(n)[1]} cells" if n["kind"] == "folder" and n["expanded"] else ""
        out.append(f'  {n["id"]} {n["kind"]} {n["node_type"]} ({n["x"]},{n["y"]}) {n["title"]}{extra}')
    ids = {n["id"] for n in children}
    edges = [e for e in meta["edges"].values() if e["source"] in ids and e["target"] in ids]
    if edges:
        out.append("edges:")
        for e in edges:
            out.append(f'  {nodes[e["source"]]["title"]} -[{e.get("edge_type", "?")}]-> {nodes[e["target"]]["title"]} ({e["id"]})')
    return "\n".join(out)


# ---- surgical tools (replacing GUPDATE) ----


def write_node(user: str, board: str, ref: str, content: str, parent: str | None = None) -> str:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    title = storage.validate_title(ref)
    try:
        nid = resolve_node(meta, ref)
        node = meta["nodes"][nid]
        if node["kind"] != "doc":
            raise ValueError("GWRITE requires a doc node")
        if len(content) > MAX_CONTENT_CHARS:
            raise ValueError(f"content too large (max {MAX_CONTENT_CHARS} chars)")
        storage.write_content(user, board, meta, nid, content)
        return f"[GWRITE] '{node['title']}' updated ({len(content)} chars)"
    except ValueError as e:
        if "node not found" not in str(e):
            raise
    storage.require_unique_title(meta, title)
    if parent is None:
        raise ValueError("parent folder required for new docs — GWRITE board title content parent")
    pnid = resolve_node(meta, parent)
    if meta["nodes"][pnid]["kind"] != "folder":
        raise ValueError("parent must be a folder")
    pos = next_position(meta, None, parent=pnid)
    full_content = f"# {title}\n\n{content}"
    if len(full_content) > MAX_CONTENT_CHARS:
        raise ValueError(f"content too large (max {MAX_CONTENT_CHARS} chars)")
    node = create_node(user, board, title, "doc", "doc", parent=pnid, x=pos["x"], y=pos["y"])
    # create_node saved a fresh meta — reload or the new node is missing from ours
    meta = storage.load_meta(user, board)
    storage.write_content(user, board, meta, node["id"], full_content)
    return f"[GWRITE] '{title}' created ({len(full_content)} chars)"


def rename_node(user: str, board: str, ref: str, title: str) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    old_meta = copy.deepcopy(meta)
    nid = resolve_node(meta, ref)
    node = meta["nodes"][nid]
    title = storage.validate_title(title)
    storage.require_unique_title(meta, title, exclude_id=nid)
    node["title"] = title
    storage.save_meta(user, board, meta)
    storage.move_content(user, board, old_meta, meta, nid)
    return node


def update_meta(user: str, board: str, ref: str, node_type: str | None = None,
                expanded: bool | None = None) -> dict:
    _require_board(user, board)
    meta = storage.load_meta(user, board)
    nid = resolve_node(meta, ref)
    node = meta["nodes"][nid]
    if node_type is not None:
        _validate_type(user, node["kind"], node_type)
        node["node_type"] = node_type
    if expanded is not None:
        node["expanded"] = bool(expanded)
    storage.save_meta(user, board, meta)
    return node


def list_tasks(user: str, agent_name: str, time_entries: list[dict]) -> str:
    if not time_entries:
        return f"TODO — {agent_name}\n\n  (no tasks assigned)"

    tasks = []  # [{"board", "nid", "title", "state", "assignee"}]
    metas = {}  # {board: meta}

    for entry in time_entries:
        board, nid = entry["board"], entry["id"]
        if board not in metas:
            metas[board] = storage.load_meta(user, board)
        meta = metas[board]
        node = meta["nodes"].get(nid)
        if not node:
            continue
        tasks.append({
            "board": board,
            "nid": nid,
            "title": node["title"],
            "state": node.get("state"),
            "assignee": node.get("assignee"),
        })

    if not tasks:
        return f"TODO — {agent_name}\n\n  (no tasks found — assigned nodes may have been deleted)"

    task_ids = {(t["board"], t["nid"]) for t in tasks}
    board_task_nids = {}  # {board: {nid}}
    for t in tasks:
        board_task_nids.setdefault(t["board"], set()).add(t["nid"])

    edges = []  # [{"source_title", "target_title"}]
    for board, meta in metas.items():
        task_nids = board_task_nids.get(board, set())
        for e in meta["edges"].values():
            if e["source"] in task_nids and e["target"] in task_nids:
                src = meta["nodes"][e["source"]]
                tgt = meta["nodes"][e["target"]]
                edges.append({"source_title": src["title"], "target_title": tgt["title"]})

    done = [t for t in tasks if t["state"] == "done"]
    doing = [t for t in tasks if t["state"] == "doing"]
    todo = [t for t in tasks if t["state"] == "todo"]
    unset = [t for t in tasks if t["state"] not in ("done", "doing", "todo")]

    def sort_key(task):
        return next((i for i, e in enumerate(time_entries)
                     if e["board"] == task["board"] and e["id"] == task["nid"]), 999)

    for g in (done, doing, todo, unset):
        g.sort(key=sort_key)

    todo_titles = {t["title"] for t in todo}
    blocker_map = {}  # {title: [blocker_title]}
    for e in edges:
        if e["target_title"] in todo_titles:
            src_state = next((t["state"] for t in tasks if t["title"] == e["source_title"]), None)
            if src_state != "done":
                blocker_map.setdefault(e["target_title"], []).append(e["source_title"])

    out = [f"TODO — {agent_name}"]
    out.append("")

    state_order = [
        ("\u2713 done", done),
        ("\u25b6 doing", doing),
        ("  todo", todo),
    ]
    if unset:
        state_order.append(("  ----", unset))

    for label, group in state_order:
        for t in group:
            short_nid = t["nid"][:6]
            assignee = f" [{t['assignee']}]" if t["state"] == "doing" and t["assignee"] else ""
            line = f"  {label:<8} {t['title']:<40} (id={short_nid}, {t['board']}){assignee}"
            blockers = blocker_map.get(t["title"], [])
            if blockers:
                line += f"    \u2190 needs: {', '.join(blockers)}"
            out.append(line)

    if edges:
        out.append("")
        out.append("edges (A \u2192 B = A before B):")
        for e in sorted(edges, key=lambda e: (e["source_title"], e["target_title"])):
            out.append(f"  {e['source_title']} \u2192 {e['target_title']}")

    return "\n".join(out)


def flip_task_state(user: str, board: str, ref: str, state: str, actor: str) -> dict:
    return update_node(user, board, ref, state=state, actor=actor)
