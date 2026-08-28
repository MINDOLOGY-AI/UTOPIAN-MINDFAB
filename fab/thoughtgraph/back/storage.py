'''storage: everything on disk, per user. one meta.json per board, a tree/ of real .md files,
types.json + access.json at the user's thoughtgraph root.
load_meta reconciles the tree into the graph: orphan .md files get adopted as nodes,
nodes whose file vanished get dropped — so hand-editing the tree in any editor works.'''

import json
import secrets
import shutil
from pathlib import Path

from fab.thoughtgraph.back.config import (
    tg_dir, GRID_SIZE, EXPANDED_W, EXPANDED_H, MAX_TITLE_CHARS,
    DEFAULT_DOC_TYPES, DEFAULT_EDGE_TYPES,
)


def board_dir(user: str, board: str) -> Path:
    return tg_dir(user) / board


def meta_file(user: str, board: str) -> Path:
    return board_dir(user, board) / "meta.json"


def tree_dir(user: str, board: str) -> Path:
    return board_dir(user, board) / "tree"


# atomic write so a kill mid-write never leaves a half json
def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def read_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def new_id(existing) -> str:
    nid = secrets.token_hex(4)
    while nid in existing:
        nid = secrets.token_hex(4)
    return nid


# ---- init / boards ----

def init(user: str):
    tg_dir(user).mkdir(parents=True, exist_ok=True)
    if not (tg_dir(user) / "types.json").exists():
        save_types(user, {"doc_types": DEFAULT_DOC_TYPES, "edge_types": DEFAULT_EDGE_TYPES})
    if not list_boards(user):
        init_board(user, "main")


def init_board(user: str, board: str):
    tree_dir(user, board).mkdir(parents=True, exist_ok=True)
    if not meta_file(user, board).exists():
        save_meta(user, board, {"nodes": {}, "edges": {}})


def list_boards(user: str) -> list:
    return sorted(p.name for p in tg_dir(user).iterdir() if p.is_dir()) if tg_dir(user).exists() else []


def rename_board(user: str, board: str, new_board: str):
    assert board_dir(user, board).exists() and not board_dir(user, new_board).exists()
    board_dir(user, board).rename(board_dir(user, new_board))


def delete_board(user: str, board: str):
    shutil.rmtree(board_dir(user, board))


# ---- meta (load reconciles the tree into the graph) ----

def load_meta(user: str, board: str) -> dict:
    meta = read_json(meta_file(user, board), {"nodes": {}, "edges": {}})
    if reconcile(user, board, meta):
        save_meta(user, board, meta)
    return meta


def save_meta(user: str, board: str, meta: dict):
    write_json(meta_file(user, board), meta)


# ---- titles: the title IS the file path component, so unique per board and path-safe ----

def validate_title(title: str) -> str:
    t = title.strip()
    if not t:
        raise ValueError("title cannot be empty")
    if len(t) > MAX_TITLE_CHARS:
        raise ValueError(f"title too long (max {MAX_TITLE_CHARS} chars)")
    if t.startswith("."):
        raise ValueError("title cannot start with '.'")
    if "/" in t or "\\" in t:
        raise ValueError("title cannot contain '/' or '\\' (titles become file paths)")
    if any(ord(c) < 32 for c in t):
        raise ValueError("title cannot contain control characters")
    return t


def require_unique_title(meta: dict, title: str, exclude_id: str | None = None):
    for nid, n in meta["nodes"].items():
        if nid != exclude_id and n["title"] == title:
            raise ValueError(f"title already exists: {title!r} (titles must be unique — they become file paths)")


# ---- content: docs at tree/<folder titles...>/<title>.md, folders are plain dirs ----

def content_path(user: str, board: str, meta: dict, nid: str) -> Path:
    node = meta["nodes"][nid]
    parts = [node["title"]]
    cur = node
    while cur["parent"]:
        cur = meta["nodes"][cur["parent"]]
        parts.append(cur["title"])
    p = tree_dir(user, board)
    for part in reversed(parts):
        p = p / part
    return p if node["kind"] == "folder" else p.with_suffix(".md")


def read_content(user: str, board: str, meta: dict, nid: str) -> str:
    p = content_path(user, board, meta, nid)
    return p.read_text() if p.exists() else ""


def write_content(user: str, board: str, meta: dict, nid: str, content: str):
    p = content_path(user, board, meta, nid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


# remove empty dirs upward from a deleted file's parent, never past the tree root
def _rmdir_empty_ancestors(p: Path, stop: Path):
    cur = p.parent
    while cur != stop and cur.is_dir():
        try:
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def delete_content(user: str, board: str, meta: dict, nid: str):
    p = content_path(user, board, meta, nid)
    if meta["nodes"][nid]["kind"] == "folder":
        if p.exists():
            shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    _rmdir_empty_ancestors(p, tree_dir(user, board))


# old_meta = the pre-mutation meta (same node, old title/parent chain)
def move_content(user: str, board: str, old_meta: dict, meta: dict, nid: str):
    old_p = content_path(user, board, old_meta, nid)
    new_p = content_path(user, board, meta, nid)
    if old_p == new_p or not old_p.exists():
        return
    new_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_p), str(new_p))
    _rmdir_empty_ancestors(old_p, tree_dir(user, board))


# ---- autoplacement (model-created + adopted nodes only — user placement is sacred) ----
# per-parent occupied grid cells: near -> one column right of it; folder children
# stack down the first column; root nodes go right of the rightmost column

def next_position(meta: dict, near: str | None = None, parent: str | None = None) -> dict[str, int]:
    cells = {(round(n["x"] / GRID_SIZE), round(n["y"] / GRID_SIZE))
             for n in meta["nodes"].values() if n["parent"] == parent}
    if near and near in meta["nodes"] and meta["nodes"][near]["parent"] == parent:
        base = meta["nodes"][near]
        col, lane = round(base["x"] / GRID_SIZE) + 1, round(base["y"] / GRID_SIZE)
        while (col, lane) in cells:
            lane += 1
        return {"x": col * GRID_SIZE, "y": lane * GRID_SIZE}
    if not cells:
        return {"x": 0, "y": 0}
    if parent is not None:
        lane = 0
        while (0, lane) in cells:
            lane += 1
        return {"x": 0, "y": lane * GRID_SIZE}
    col = max(c[0] for c in cells) + 1
    lane = 0
    while (col, lane) in cells:
        lane += 1
    return {"x": col * GRID_SIZE, "y": lane * GRID_SIZE}


# ---- reconcile: fold hand-made disk edits back into the graph ----

def _new_node(meta: dict, title: str, kind: str, parent: str | None) -> dict:
    pos = next_position(meta, parent=parent)
    node = {"id": new_id(meta["nodes"]), "title": title, "kind": kind,
            "node_type": "folder" if kind == "folder" else "doc",
            "ref": None, "x": pos["x"], "y": pos["y"],
            "width": EXPANDED_W, "height": EXPANDED_H,
            "parent": parent, "expanded": False, "color": None}
    meta["nodes"][node["id"]] = node
    return node


def _drop_node(meta: dict, nid: str):
    del meta["nodes"][nid]
    meta["edges"] = {eid: e for eid, e in meta["edges"].items()
                     if e["source"] != nid and e["target"] != nid}


def reconcile(user: str, board: str, meta: dict) -> bool:
    changed = False
    nodes = meta["nodes"]
    # doc nodes whose file vanished are gone (hand-deleted/moved); a hand-rename
    # shows up as a drop here + an adoption below — fresh id, edges lost, by design
    for nid in [i for i, n in nodes.items()
                if n["kind"] == "doc" and not content_path(user, board, meta, i).exists()]:
        _drop_node(meta, nid)
        changed = True
    tree = tree_dir(user, board)
    if not tree.exists():
        return changed
    known = {content_path(user, board, meta, i) for i, n in nodes.items() if n["kind"] == "doc"}
    for f in sorted(tree.rglob("*.md")):
        if f in known:
            continue
        try:
            title = validate_title(f.stem)
            require_unique_title(meta, title)
        except ValueError:
            continue  # filename the graph can't represent — not adoptable
        # walk the dir chain from the root, adopting missing folders on the way
        parent = None
        for part in f.relative_to(tree).parts[:-1]:
            node = next((n for n in nodes.values()
                         if n["kind"] == "folder" and n["title"] == part and n["parent"] == parent), None)
            if node is None:
                node = _new_node(meta, part, "folder", parent)
            parent = node["id"]
        _new_node(meta, title, "doc", parent)
        # every adopted doc already has its file — that's the point
        changed = True
    return changed


# ---- types registry (defaults can be recolored but never permanently deleted) ----

def load_types(user: str) -> dict:
    types = read_json(tg_dir(user) / "types.json", {})
    types["doc_types"] = {**DEFAULT_DOC_TYPES, **types.get("doc_types", {})}
    types["edge_types"] = {**DEFAULT_EDGE_TYPES, **types.get("edge_types", {})}
    return types


def save_types(user: str, types: dict):
    write_json(tg_dir(user) / "types.json", types)


# ---- access: {agent_name: {read, write}} — enforced by the G* tools ----

def load_access(user: str) -> dict:
    return read_json(tg_dir(user) / "access.json", {})


def save_access(user: str, access: dict):
    write_json(tg_dir(user) / "access.json", access)


# ---- presets: {preset_name: access entry} — stamp a standard access pattern onto agents ----

def load_presets(user: str) -> dict:
    return read_json(tg_dir(user) / "presets.json", {})


def save_presets(user: str, presets: dict):
    write_json(tg_dir(user) / "presets.json", presets)
