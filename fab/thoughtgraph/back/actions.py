'''actions: the graph operations. one implementation, two front doors — the REST api
for the board UI and the G* tools for agents. no error handling: bad input raises,
the caller (fastapi / commands.dispatch) turns it into an error result.'''

import copy
from types import EllipsisType

from fab.thoughtgraph.back import storage
from fab.thoughtgraph.back.config import GRID_SIZE, EXPANDED_W, EXPANDED_H, MAX_CONTENT_CHARS


# a node reference is an id or a (unique-per-board) title
def resolve_node(meta: dict, ref: str) -> str:
    if ref in meta["nodes"]:
        return ref
    matches = [nid for nid, n in meta["nodes"].items() if n["title"] == ref]
    if not matches:
        raise ValueError(f"node not found: {ref!r}")
    assert len(matches) == 1, f"duplicate title {ref!r} — titles are unique per board"
    return matches[0]


# folder-joined title path, e.g. mind/mech interp/train SAE
def node_path(meta: dict, nid: str) -> str:
    parts = []
    cur = nid
    while cur:
        parts.append(meta["nodes"][cur]["title"])
        cur = meta["nodes"][cur]["parent"]
    return "/".join(reversed(parts))


def create_node(user: str, board: str, title: str, kind: str, node_type: str = "doc",
                parent: str | None = None, ref: str | None = None,
                near: str | None = None, x: float | None = None, y: float | None = None) -> dict:
    if kind not in ("doc", "folder"):
        raise ValueError(f"kind must be doc or folder, got {kind!r}")
    title = storage.validate_title(title)
    meta = storage.load_meta(user, board)
    storage.require_unique_title(meta, title)
    if kind == "doc" and node_type not in storage.load_types(user)["doc_types"]:
        raise ValueError(f"unknown doc type {node_type!r}")
    if parent is not None:
        parent = resolve_node(meta, parent)
        if meta["nodes"][parent]["kind"] != "folder":
            raise ValueError("parent must be a folder")
    if x is None or y is None:
        pos = storage.next_position(meta, near=resolve_node(meta, near) if near else None, parent=parent)
        x, y = pos["x"], pos["y"]
    # root nodes snap to the grid; child coordinates are relative to their folder
    if parent is None:
        x = round(float(x) / GRID_SIZE) * GRID_SIZE
        y = round(float(y) / GRID_SIZE) * GRID_SIZE
    else:
        x, y = int(round(float(x))), int(round(float(y)))
    node = {"id": storage.new_id(meta["nodes"]), "title": title, "kind": kind,
            "node_type": "folder" if kind == "folder" else node_type,
            "ref": ref, "x": x, "y": y, "width": EXPANDED_W, "height": EXPANDED_H,
            "parent": parent, "expanded": False, "color": None}
    meta["nodes"][node["id"]] = node
    storage.save_meta(user, board, meta)
    if kind == "doc":
        # every doc has a file — reconcile drops fileless docs as hand-deleted
        storage.write_content(user, board, meta, node["id"], "")
    return node


def read_node(user: str, board: str, ref: str) -> dict:
    meta = storage.load_meta(user, board)
    nid = resolve_node(meta, ref)
    connected = []
    for e in meta["edges"].values():
        if e["source"] == nid:
            other, direction = e["target"], "out"
        elif e["target"] == nid:
            other, direction = e["source"], "in"
        else:
            continue
        if other in meta["nodes"]:
            o = meta["nodes"][other]
            connected.append({"edge_id": e["id"], "direction": direction, "id": other,
                              "title": o["title"], "kind": o["kind"], "node_type": o["node_type"]})
    return {"node": meta["nodes"][nid],
            "content": storage.read_content(user, board, meta, nid),
            "connected": connected}


# GEDIT: single-occurrence search/replace inside a doc — ambiguous edits are the model's bug.
# bootstrap: agents can never CREATE docs, but old == "" on an empty doc fills it
def edit_node(user: str, board: str, ref: str, old: str, new: str) -> dict:
    meta = storage.load_meta(user, board)
    nid = resolve_node(meta, ref)
    if meta["nodes"][nid]["kind"] != "doc":
        raise ValueError("GEDIT requires a doc node")
    if len(new) > MAX_CONTENT_CHARS:
        raise ValueError(f"content too large (max {MAX_CONTENT_CHARS} chars)")
    content = storage.read_content(user, board, meta, nid)
    if content == "" and old == "":
        storage.write_content(user, board, meta, nid, new)
        return meta["nodes"][nid]
    n = content.count(old)
    if n == 0:
        raise ValueError("old string not found")
    if n > 1:
        raise ValueError(f"old string occurs {n} times — make it more specific")
    storage.write_content(user, board, meta, nid, content.replace(old, new))
    return meta["nodes"][nid]


# GMETA: everything about a node that isn't content — rename, retype, move, expand, color, resize
def set_meta(user: str, board: str, ref: str, title: str | None = None, node_type: str | None = None,
             x: float | None = None, y: float | None = None, parent: str | None | EllipsisType = ...,
             expanded: bool | None = None, color: str | None = None,
             width: float | None = None, height: float | None = None) -> dict:
    meta = storage.load_meta(user, board)
    old_meta = copy.deepcopy(meta)  # for content-path sync after rename/reparent
    nid = resolve_node(meta, ref)
    node = meta["nodes"][nid]
    if title is not None:
        title = storage.validate_title(title)
        storage.require_unique_title(meta, title, exclude_id=nid)
        node["title"] = title
    if node_type is not None:
        if node["kind"] == "folder":
            raise ValueError("folders have no type")
        if node_type not in storage.load_types(user)["doc_types"]:
            raise ValueError(f"unknown doc type {node_type!r}")
        node["node_type"] = node_type
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
    # root coords snap to the grid, child coords are folder-relative ints — by final parent
    if x is not None:
        node["x"] = round(float(x) / GRID_SIZE) * GRID_SIZE if node["parent"] is None else int(round(float(x)))
    if y is not None:
        node["y"] = round(float(y) / GRID_SIZE) * GRID_SIZE if node["parent"] is None else int(round(float(y)))
    if expanded is not None:
        node["expanded"] = bool(expanded)
    if color is not None:
        node["color"] = color
    if width is not None:
        node["width"] = width
    if height is not None:
        node["height"] = height
    storage.save_meta(user, board, meta)
    storage.move_content(user, board, old_meta, meta, nid)
    return node


# deletes the whole subtree: files first (their paths resolve through meta), then nodes, then edges
def destroy_node(user: str, board: str, ref: str) -> dict:
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
        storage.delete_content(user, board, meta, o_id)
    for o_id in to_delete:
        del meta["nodes"][o_id]
    meta["edges"] = {eid: e for eid, e in meta["edges"].items()
                     if e["source"] not in to_delete and e["target"] not in to_delete}
    storage.save_meta(user, board, meta)
    return {"deleted": sorted(to_delete)}


# typed edge between two docs; an existing (source, target) pair gets retyped
def link(user: str, board: str, source: str, target: str, edge_type: str) -> dict:
    meta = storage.load_meta(user, board)
    src, tgt = resolve_node(meta, source), resolve_node(meta, target)
    if src == tgt:
        raise ValueError("cannot link a node to itself")
    if meta["nodes"][src]["kind"] == "folder" or meta["nodes"][tgt]["kind"] == "folder":
        raise ValueError("edges connect doc nodes, not folders")
    if edge_type not in storage.load_types(user)["edge_types"]:
        raise ValueError(f"unknown edge type {edge_type!r}")
    for e in meta["edges"].values():
        if e["source"] == src and e["target"] == tgt:
            e["edge_type"] = edge_type
            storage.save_meta(user, board, meta)
            return e
    edge = {"id": storage.new_id(meta["edges"]), "source": src, "target": tgt, "edge_type": edge_type}
    meta["edges"][edge["id"]] = edge
    storage.save_meta(user, board, meta)
    return edge


# tool form: the model thinks in (source, target) pairs, not edge ids
def unlink(user: str, board: str, source: str, target: str) -> dict:
    meta = storage.load_meta(user, board)
    src, tgt = resolve_node(meta, source), resolve_node(meta, target)
    eid = next((i for i, e in meta["edges"].items() if e["source"] == src and e["target"] == tgt), None)
    if eid is None:
        raise ValueError(f"no edge from {source!r} to {target!r}")
    del meta["edges"][eid]
    storage.save_meta(user, board, meta)
    return {"ok": True}


def unlink_edge(user: str, board: str, edge_id: str) -> dict:
    meta = storage.load_meta(user, board)
    if edge_id not in meta["edges"]:
        raise ValueError(f"edge not found: {edge_id!r}")
    del meta["edges"][edge_id]
    storage.save_meta(user, board, meta)
    return {"ok": True}


# the model's primary picture of the graph: one line per node `path (type)`,
# then one line per edge. ref scopes to a folder's subtree (edges shown when
# either endpoint is inside); visible scopes to an access set (edges need BOTH)
def gmap(user: str, board: str, ref: str | None = None, visible: set | None = None) -> str:
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
        label = f"{nodes[nid]['title']}/ on board '{board}'"

    def fmt(nid):
        n = nodes[nid]
        return f"{node_path(meta, nid)}{'/' if n['kind'] == 'folder' else ''} ({n['node_type']})"

    shown = [nid for nid in nodes
             if (scope is None or nid in scope) and (visible is None or nid in visible)]
    edges = [e for e in meta["edges"].values()
             if e["source"] in nodes and e["target"] in nodes
             and (visible is None or (e["source"] in visible and e["target"] in visible))
             and (scope is None or e["source"] in scope or e["target"] in scope)]
    out = [f"{label} — {len(shown)} nodes, {len(edges)} edges", "nodes:"]
    for nid in sorted(shown, key=lambda i: node_path(meta, i).lower()):
        out.append(f"  {fmt(nid)}")
    out.append("edges:")
    for e in sorted(edges, key=lambda e: (node_path(meta, e["source"]).lower(), node_path(meta, e["target"]).lower())):
        out.append(f"  {fmt(e['source'])} -({e['edge_type']})-> {fmt(e['target'])}")
    return "\n".join(out)
