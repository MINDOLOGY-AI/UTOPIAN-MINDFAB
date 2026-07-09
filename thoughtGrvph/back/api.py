import re
import secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from thoughtGrvph.back.storage import (
    GRID_SIZE,
    init_storage,
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONT_DIR = PROJECT_ROOT / "thoughtGrvph" / "front"
DATA_DIR = PROJECT_ROOT / "thoughts" / "thoughtgrvph"
HUB_COMPONENTS_DIR = PROJECT_ROOT / "hub" / "components"
EDGE_COLORS = ("gray", "green", "red", "blue")

app = FastAPI()


@app.exception_handler(ValueError)
def _value_error_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.on_event("startup")
def _startup():
    init_storage()


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


class ContentUpdate(BaseModel):
    content: str


class EdgeCreate(BaseModel):
    source: str
    target: str


class EdgeUpdate(BaseModel):
    color: str  # "gray" | "green" | "red" | "blue"


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


def assert_unique_title(meta, node_id, title, ntype, parent):
    # disk paths are title-based, so sibling titles must be unique;
    # doc titles are globally unique so [[wikilinks]] resolve unambiguously
    for nid, n in meta["nodes"].items():
        if nid == node_id:
            continue
        if n["parent"] == parent:
            assert n["title"] != title
        if ntype == "file" and n["type"] == "file":
            assert n["title"] != title


def new_id(existing):
    nid = secrets.token_hex(4)
    while nid in existing:
        nid = secrets.token_hex(4)
    return nid


def snap_to_grid(value):
    return round(float(value) / GRID_SIZE) * GRID_SIZE


# ---- boards ----

@app.get("/boards")
def get_boards():
    return {"boards": list_boards()}


@app.post("/boards")
def create_board(payload: BoardCreate):
    board_id = validate_title(payload.board_id)
    init_board(board_id)
    return {"id": board_id}


@app.put("/boards/{board_id}")
def update_board(board_id: str, payload: BoardUpdate):
    if board_id not in list_boards():
        raise HTTPException(status_code=404, detail="board not found")
    new_board_id = validate_title(payload.board_id)
    if new_board_id in list_boards() and new_board_id != board_id:
        raise HTTPException(status_code=400, detail="board name already exists")
    rename_board(board_id, new_board_id)
    return {"id": new_board_id}


@app.delete("/boards/{board_id}")
def remove_board(board_id: str):
    if board_id not in list_boards():
        raise HTTPException(status_code=404, detail="board not found")
    delete_board(board_id)
    return {"ok": True}


# ---- nodes ----

@app.get("/boards/{board_id}/graph")
def get_graph(board_id: str):
    meta = load_meta(board_id)
    return meta


@app.post("/boards/{board_id}/nodes")
def create_node(board_id: str, payload: NodeCreate):
    assert payload.type in ("file", "folder")
    title = validate_title(payload.title)
    meta = load_meta(board_id)
    if payload.parent is not None:
        assert payload.parent in meta["nodes"]
        assert meta["nodes"][payload.parent]["type"] == "folder"
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
    create_on_disk(meta, nid, board_id)
    save_meta(board_id, meta)
    return node


@app.put("/boards/{board_id}/nodes/{node_id}")
def update_node(board_id: str, node_id: str, payload: NodeUpdate):
    meta = load_meta(board_id)
    assert node_id in meta["nodes"]
    updates = payload.model_dump(exclude_unset=True)
    if "x" in updates:
        updates["x"] = snap_to_grid(updates["x"])
    if "y" in updates:
        updates["y"] = snap_to_grid(updates["y"])
    if "title" in updates:
        updates["title"] = validate_title(updates["title"])
    if "parent" in updates and updates["parent"] is not None:
        assert updates["parent"] in meta["nodes"]
        assert meta["nodes"][updates["parent"]]["type"] == "folder"
        p = updates["parent"]
        while p is not None:
            assert p != node_id
            p = meta["nodes"][p]["parent"]
    node = meta["nodes"][node_id]
    if "title" in updates or "parent" in updates:
        new_title = updates.get("title", node["title"])
        new_parent = updates.get("parent", node["parent"])
        assert_unique_title(meta, node_id, new_title, node["type"], new_parent)
    old_title = node["title"]
    old_path = node_path(meta, node_id, board_id)
    node.update(updates)
    new_path = node_path(meta, node_id, board_id)
    if new_path != old_path:
        move_on_disk(old_path, new_path)
    if node["type"] == "file" and node["title"] != old_title:
        for nid, n in meta["nodes"].items():
            if n["type"] != "file":
                continue
            p = node_path(meta, nid, board_id)
            content = p.read_text()
            rewritten = content.replace(f"[[{old_title}]]", f"[[{node['title']}]]")
            if rewritten != content:
                p.write_text(rewritten)
    save_meta(board_id, meta)
    return node


@app.delete("/boards/{board_id}/nodes/{node_id}")
def delete_node(board_id: str, node_id: str):
    meta = load_meta(board_id)
    assert node_id in meta["nodes"]
    delete_on_disk(meta, node_id, board_id)
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
    save_meta(board_id, meta)
    return {"deleted": list(to_delete)}


@app.get("/boards/{board_id}/nodes/{node_id}/content")
def get_content(board_id: str, node_id: str):
    meta = load_meta(board_id)
    assert node_id in meta["nodes"]
    assert meta["nodes"][node_id]["type"] == "file"
    p = node_path(meta, node_id, board_id)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    return {"content": p.read_text()}


@app.put("/boards/{board_id}/nodes/{node_id}/content")
def put_content(board_id: str, node_id: str, payload: ContentUpdate):
    meta = load_meta(board_id)
    assert node_id in meta["nodes"]
    assert meta["nodes"][node_id]["type"] == "file"
    node_path(meta, node_id, board_id).write_text(payload.content)
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
        save_meta(board_id, meta)
    return {"ok": True, "edges": new_edges}


# ---- edges ----

@app.post("/boards/{board_id}/edges")
def create_edge(board_id: str, payload: EdgeCreate):
    meta = load_meta(board_id)
    assert payload.source in meta["nodes"]
    assert payload.target in meta["nodes"]
    assert payload.source != payload.target
    eid = new_id(meta["edges"])
    edge = {
        "id": eid,
        "source": payload.source,
        "target": payload.target,
        "color": "gray",
    }
    meta["edges"][eid] = edge
    save_meta(board_id, meta)
    return edge


@app.put("/boards/{board_id}/edges/{edge_id}")
def update_edge(board_id: str, edge_id: str, payload: EdgeUpdate):
    assert payload.color in EDGE_COLORS
    meta = load_meta(board_id)
    assert edge_id in meta["edges"]
    meta["edges"][edge_id]["color"] = payload.color
    save_meta(board_id, meta)
    return meta["edges"][edge_id]


@app.delete("/boards/{board_id}/edges/{edge_id}")
def delete_edge(board_id: str, edge_id: str):
    meta = load_meta(board_id)
    assert edge_id in meta["edges"]
    del meta["edges"][edge_id]
    save_meta(board_id, meta)
    return {"ok": True}


# ---- versions ----

@app.get("/boards/{board_id}/versions")
def get_versions(board_id: str):
    return {"versions": list_versions(board_id)}


@app.post("/boards/{board_id}/versions")
def post_version(board_id: str):
    return {"name": save_version(board_id)}


@app.delete("/boards/{board_id}/versions/{name}")
def remove_version(board_id: str, name: str):
    delete_version(board_id, name)
    return {"ok": True}


@app.post("/boards/{board_id}/versions/{name}/restore")
def post_restore(board_id: str, name: str):
    restore_version(board_id, name)
    return load_meta(board_id)


# ---- frontend ----

@app.get("/")
def index():
    return FileResponse(FRONT_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONT_DIR), name="static")
app.mount("/components", StaticFiles(directory=HUB_COMPONENTS_DIR), name="components")
app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")
