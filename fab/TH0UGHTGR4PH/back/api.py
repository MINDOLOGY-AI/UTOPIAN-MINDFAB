import re
import secrets
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fab.TH0UGHTGR4PH.back.storage import (
    GRID_SIZE,
    DATA_DIR,
    init_user_storage,
    init_board,
    list_boards,
    load_meta,
    rename_board,
    delete_board,
    save_meta,
    node_path,
    create_on_disk,
    move_on_disk,
    delete_on_disk,
    list_versions,
    save_version,
    delete_version,
    restore_version,
)
from fab.hub.auth.store import COOKIE_NAME, user_for_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONT_DIR = PROJECT_ROOT / "TH0UGHTGR4PH" / "front"
HUB_COMPONENTS_DIR = PROJECT_ROOT / "hub" / "components"
EDGE_COLORS = ("gray", "green", "red", "blue")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
# cybersec: cap note writes at 5 MB — without this any logged-in user could fill the disk with huge bodies
MAX_CONTENT_BYTES = 5 * 1024 * 1024

app = FastAPI()


def current_user(request: Request) -> str:
    # every route is per-user: the session user owns the board tree. lazily
    # creates fab/data/TH0UGHTGR4PH/{user}/ with a 'main' board on first touch.
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    init_user_storage(user)
    return user


@app.exception_handler(ValueError)
def _value_error_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---- models ----

class BoardCreate(BaseModel):
    board_id: str


class BoardUpdate(BaseModel):
    board_id: str


class NodeCreate(BaseModel):
    title: str
    type: str  # "file" | "folder"
    parent: str | None = None
    x: float = 0
    y: float = 0


class NodeUpdate(BaseModel):
    title: str | None = None
    x: float | None = None
    y: float | None = None
    parent: str | None = None
    expanded: bool | None = None
    width: float | None = None
    height: float | None = None
    color: str | None = None


class ContentUpdate(BaseModel):
    content: str


class EdgeCreate(BaseModel):
    source: str
    target: str


class EdgeUpdate(BaseModel):
    color: str  # named color or "#RRGGBB"


def validate_title(title: str) -> str:
    # Titles become filesystem paths in data/, so reject characters that would
    # create nested dirs, escape the data directory, or are invalid in filenames.
    if not isinstance(title, str):
        raise ValueError("title must be a string")
    title = title.strip()
    if not title:
        raise ValueError("title cannot be empty")
    if title in (".", ".."):
        raise ValueError("title cannot be '.' or '..'")
    if "/" in title or "\\" in title or "\x00" in title:
        raise ValueError("title cannot contain /, \\, or null bytes")
    return title


def validate_board_id(board_id: str) -> str:
    # cybersec: board ids (and version names) become folder paths, so reject "..", "/", "\\" —
    # without this curl --path-as-is '/boards/../versions/x/restore' could copy or wipe the whole data tree
    try:
        return validate_title(board_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def assert_unique_title(meta, node_id, title, ntype, parent):
    # disk paths are title-based, so sibling titles must be unique;
    # doc titles are globally unique so [[wikilinks]] resolve unambiguously
    for nid, n in meta["nodes"].items():
        if nid == node_id:
            continue
        if n["parent"] == parent and n["title"] == title:
            raise ValueError(f"a node named '{title}' already exists in this folder")
        if ntype == "file" and n["type"] == "file" and n["title"] == title:
            raise ValueError(f"a file named '{title}' already exists on this board")


def new_id(existing):
    nid = secrets.token_hex(4)
    while nid in existing:
        nid = secrets.token_hex(4)
    return nid


def snap_to_grid(value):
    return round(float(value) / GRID_SIZE) * GRID_SIZE


# ---- boards ----

@app.get("/boards")
def get_boards(user: str = Depends(current_user)):
    return {"boards": list_boards(user)}


@app.post("/boards")
def create_board(payload: BoardCreate, user: str = Depends(current_user)):
    board_id = validate_title(payload.board_id)
    init_board(user, board_id)
    return {"id": board_id}


@app.put("/boards/{board_id}")
def update_board(board_id: str, payload: BoardUpdate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    if board_id not in list_boards(user):
        raise HTTPException(status_code=404, detail="board not found")
    new_board_id = validate_title(payload.board_id)
    if new_board_id in list_boards(user) and new_board_id != board_id:
        raise HTTPException(status_code=400, detail="board name already exists")
    rename_board(user, board_id, new_board_id)
    return {"id": new_board_id}


@app.delete("/boards/{board_id}")
def remove_board(board_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    if board_id not in list_boards(user):
        raise HTTPException(status_code=404, detail="board not found")
    delete_board(user, board_id)
    return {"ok": True}


# ---- nodes ----

@app.get("/boards/{board_id}/graph")
def get_graph(board_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = load_meta(user, board_id)
    return meta


@app.post("/boards/{board_id}/nodes")
def create_node(board_id: str, payload: NodeCreate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    # cybersec: bad input gets a 400, not a bare assert — asserts return 500 and vanish under python -O
    if payload.type not in ("file", "folder"):
        raise HTTPException(status_code=400, detail="type must be 'file' or 'folder'")
    title = validate_title(payload.title)
    meta = load_meta(user, board_id)
    if payload.parent is not None:
        if payload.parent not in meta["nodes"]:
            raise HTTPException(status_code=400, detail="parent node not found")
        if meta["nodes"][payload.parent]["type"] != "folder":
            raise HTTPException(status_code=400, detail="parent must be a folder")
    assert_unique_title(meta, None, title, payload.type, payload.parent)
    nid = new_id(meta["nodes"])
    node = {
        "id": nid,
        "title": title,
        "type": payload.type,
        "x": snap_to_grid(payload.x),
        "y": snap_to_grid(payload.y),
        "parent": payload.parent,
        "expanded": False,
        "width": 560,
        "height": 360,
    }
    meta["nodes"][nid] = node
    create_on_disk(user, meta, nid, board_id)
    save_meta(user, board_id, meta)
    return node


@app.put("/boards/{board_id}/nodes/{node_id}")
def update_node(board_id: str, node_id: str, payload: NodeUpdate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = load_meta(user, board_id)
    # cybersec: unknown ids get 404/400, not a bare assert — asserts return 500 and vanish under python -O
    if node_id not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="node not found")
    updates = payload.model_dump(exclude_unset=True)
    if "x" in updates:
        updates["x"] = snap_to_grid(updates["x"])
    if "y" in updates:
        updates["y"] = snap_to_grid(updates["y"])
    if "title" in updates:
        updates["title"] = validate_title(updates["title"])
    if "color" in updates and updates["color"] is not None:
        if updates["color"] not in EDGE_COLORS and not HEX_COLOR_RE.match(updates["color"]):
            raise HTTPException(status_code=400, detail="invalid node color")
    if "parent" in updates and updates["parent"] is not None:
        if updates["parent"] not in meta["nodes"]:
            raise HTTPException(status_code=400, detail="parent node not found")
        if meta["nodes"][updates["parent"]]["type"] != "folder":
            raise HTTPException(status_code=400, detail="parent must be a folder")
        p = updates["parent"]
        while p is not None:
            if p == node_id:
                raise HTTPException(status_code=400, detail="cannot move a node into its own subtree")
            p = meta["nodes"][p]["parent"]
    node = meta["nodes"][node_id]
    if "title" in updates or "parent" in updates:
        new_title = updates.get("title", node["title"])
        new_parent = updates.get("parent", node["parent"])
        assert_unique_title(meta, node_id, new_title, node["type"], new_parent)
    old_title = node["title"]
    old_path = node_path(user, meta, node_id, board_id)
    node.update(updates)
    new_path = node_path(user, meta, node_id, board_id)
    if new_path != old_path:
        move_on_disk(old_path, new_path)
    if node["type"] == "file" and node["title"] != old_title:
        for nid, n in meta["nodes"].items():
            if n["type"] != "file":
                continue
            p = node_path(user, meta, nid, board_id)
            content = p.read_text()
            rewritten = content.replace(f"[[{old_title}]]", f"[[{node['title']}]]")
            if rewritten != content:
                p.write_text(rewritten)
    save_meta(user, board_id, meta)
    return node


@app.delete("/boards/{board_id}/nodes/{node_id}")
def delete_node(board_id: str, node_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = load_meta(user, board_id)
    # cybersec: unknown node id gets 404, not a bare assert — asserts return 500 and vanish under python -O
    if node_id not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="node not found")
    delete_on_disk(user, meta, node_id, board_id)
    to_delete = {node_id}
    stack = [node_id]
    while stack:
        cur = stack.pop()
        for nid, n in meta["nodes"].items():
            if n["parent"] == cur and nid not in to_delete:
                to_delete.add(nid)
                stack.append(nid)
    for nid in to_delete:
        del meta["nodes"][nid]
    meta["edges"] = {
        eid: e for eid, e in meta["edges"].items()
        if e["source"] not in to_delete and e["target"] not in to_delete
    }
    save_meta(user, board_id, meta)
    return {"deleted": list(to_delete)}


@app.get("/boards/{board_id}/nodes/{node_id}/content")
def get_content(board_id: str, node_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = load_meta(user, board_id)
    # cybersec: unknown ids get 404/400, not a bare assert — asserts return 500 and vanish under python -O
    if node_id not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="node not found")
    if meta["nodes"][node_id]["type"] != "file":
        raise HTTPException(status_code=400, detail="node is not a file")
    p = node_path(user, meta, node_id, board_id)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    return {"content": p.read_text()}


@app.put("/boards/{board_id}/nodes/{node_id}/content")
def put_content(board_id: str, node_id: str, payload: ContentUpdate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = load_meta(user, board_id)
    # cybersec: unknown ids get 404/400, not a bare assert — asserts return 500 and vanish under python -O
    if node_id not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="node not found")
    if meta["nodes"][node_id]["type"] != "file":
        raise HTTPException(status_code=400, detail="node is not a file")
    # cybersec: reject bodies over 5 MB with 413 — without this any user could fill the disk with one huge note
    if len(payload.content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise HTTPException(status_code=413, detail="content too large (max 5 MB)")
    node_path(user, meta, node_id, board_id).write_text(payload.content)
    titles = set(re.findall(r"\[\[([^\]]+)\]\]", payload.content))
    title_to_id = {n["title"]: nid for nid, n in meta["nodes"].items() if n["type"] == "file"}
    new_edges = {}
    for t in titles:
        tid = title_to_id.get(t)
        if tid is None or tid == node_id:
            continue
        linked = any(
            {e["source"], e["target"]} == {node_id, tid}
            for e in meta["edges"].values()
        )
        if linked:
            continue
        eid = new_id(meta["edges"])
        edge = {"id": eid, "source": node_id, "target": tid, "color": "gray"}
        meta["edges"][eid] = edge
        new_edges[eid] = edge
    if new_edges:
        save_meta(user, board_id, meta)
    return {"ok": True, "edges": new_edges}


# ---- edges ----

@app.post("/boards/{board_id}/edges")
def create_edge(board_id: str, payload: EdgeCreate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = load_meta(user, board_id)
    # cybersec: bad edge input gets 404/400, not a bare assert — asserts return 500 and vanish under python -O
    if payload.source not in meta["nodes"] or payload.target not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="edge endpoint node not found")
    if payload.source == payload.target:
        raise HTTPException(status_code=400, detail="cannot connect a node to itself")
    eid = new_id(meta["edges"])
    edge = {
        "id": eid,
        "source": payload.source,
        "target": payload.target,
        "color": "gray",
    }
    meta["edges"][eid] = edge
    save_meta(user, board_id, meta)
    return edge


@app.put("/boards/{board_id}/edges/{edge_id}")
def update_edge(board_id: str, edge_id: str, payload: EdgeUpdate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    if payload.color not in EDGE_COLORS and not HEX_COLOR_RE.match(payload.color):
        raise HTTPException(status_code=400, detail="invalid edge color")
    meta = load_meta(user, board_id)
    # cybersec: unknown edge id gets 404, not a bare assert — asserts return 500 and vanish under python -O
    if edge_id not in meta["edges"]:
        raise HTTPException(status_code=404, detail="edge not found")
    meta["edges"][edge_id]["color"] = payload.color
    save_meta(user, board_id, meta)
    return meta["edges"][edge_id]


@app.delete("/boards/{board_id}/edges/{edge_id}")
def delete_edge(board_id: str, edge_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = load_meta(user, board_id)
    # cybersec: unknown edge id gets 404, not a bare assert — asserts return 500 and vanish under python -O
    if edge_id not in meta["edges"]:
        raise HTTPException(status_code=404, detail="edge not found")
    del meta["edges"][edge_id]
    save_meta(user, board_id, meta)
    return {"ok": True}


# ---- versions ----

@app.get("/boards/{board_id}/versions")
def get_versions(board_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return {"versions": list_versions(user, board_id)}


@app.post("/boards/{board_id}/versions")
def post_version(board_id: str, user: str = Depends(current_user)):
    # cybersec: board_id='..' would snapshot the whole data tree (disk fill) — blocked by validation
    board_id = validate_board_id(board_id)
    return {"name": save_version(user, board_id)}


@app.delete("/boards/{board_id}/versions/{name}")
def remove_version(board_id: str, name: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    # cybersec: version names are folder paths too — '..' would rmtree the board dir above versions/
    name = validate_board_id(name)
    delete_version(user, board_id, name)
    return {"ok": True}


@app.post("/boards/{board_id}/versions/{name}/restore")
def post_restore(board_id: str, name: str, user: str = Depends(current_user)):
    # cybersec: board_id='..' would rmtree every user's board data on restore — blocked by validation
    board_id = validate_board_id(board_id)
    name = validate_board_id(name)
    restore_version(user, board_id, name)
    return load_meta(user, board_id)


# ---- data files (raw .md on disk) ----

@app.get("/data/{path:path}")
def get_data_file(path: str, user: str = Depends(current_user)):
    # serves only the requesting user's own files; no cross-user reads
    root = (DATA_DIR / user).resolve()
    p = (root / path).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p)


# ---- frontend ----

@app.get("/")
def index():
    return FileResponse(FRONT_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONT_DIR), name="static")
app.mount("/components", StaticFiles(directory=HUB_COMPONENTS_DIR), name="components")
