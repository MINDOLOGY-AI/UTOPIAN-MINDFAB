from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fab.TH0UGHTGR4PH.back import graph_actions as ga
from fab.TH0UGHTGR4PH.back import storage
from fab.TH0UGHTGR4PH.back.config import DATA_DIR
from fab.hub.auth.store import COOKIE_NAME, user_for_token

PROJECT_ROOT = Path.cwd()
FRONT_DIR = PROJECT_ROOT / "fab" / "TH0UGHTGR4PH" / "front"
HUB_COMPONENTS_DIR = PROJECT_ROOT / "fab" / "hub" / "components"
MAX_CONTENT_CHARS = 100_000

app = FastAPI()


def current_user(request: Request) -> str:
    # every route is per-user: the session user owns the board tree. lazily
    # creates fab/data/TH0UGHTGR4PH/{user}/ with a 'main' board on first touch.
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    storage.init_user_storage(user)
    return user


@app.exception_handler(ValueError)
def _value_error_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def validate_board_id(board_id: str) -> str:
    # cybersec: board ids (and version/template names) become folder paths — reject "..", "/", "\\"
    if not isinstance(board_id, str):
        raise HTTPException(status_code=400, detail="board id must be a string")
    board_id = board_id.strip()
    if not board_id or board_id in (".", "..") or "/" in board_id or "\\" in board_id or "\x00" in board_id:
        raise HTTPException(status_code=400, detail="invalid board id")
    return board_id

#---- models ----


class BoardCreate(BaseModel):
    board_id: str


class BoardUpdate(BaseModel):
    board_id: str


class NodeCreate(BaseModel):
    title: str
    kind: str  # "obj" | "func" | "folder"
    node_type: str = "doc"
    parent: str | None = None
    state: str | None = None
    ref: str | None = None
    near: str | None = None
    x: float | None = None
    y: float | None = None


class NodeUpdate(BaseModel):
    title: str | None = None
    node_type: str | None = None
    state: str | None = None
    x: float | None = None
    y: float | None = None
    parent: str | None = None
    expanded: bool | None = None
    width: float | None = None
    height: float | None = None
    color: str | None = None
    ref: str | None = None


class ContentUpdate(BaseModel):
    content: str


class EdgeCreate(BaseModel):
    source: str
    target: str


# ---- boards ----


@app.get("/boards")
def get_boards(user: str = Depends(current_user)):
    return {"boards": storage.list_boards(user)}


@app.post("/boards")
def create_board(payload: BoardCreate, user: str = Depends(current_user)):
    board_id = validate_board_id(payload.board_id)
    storage.init_board(user, board_id)
    return {"id": board_id}


@app.put("/boards/{board_id}")
def update_board(board_id: str, payload: BoardUpdate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    if board_id not in storage.list_boards(user):
        raise HTTPException(status_code=404, detail="board not found")
    new_board_id = validate_board_id(payload.board_id)
    if new_board_id in storage.list_boards(user) and new_board_id != board_id:
        raise HTTPException(status_code=400, detail="board name already exists")
    storage.rename_board(user, board_id, new_board_id)
    return {"id": new_board_id}


@app.delete("/boards/{board_id}")
def remove_board(board_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    if board_id not in storage.list_boards(user):
        raise HTTPException(status_code=404, detail="board not found")
    storage.delete_board(user, board_id)
    return {"ok": True}


# ---- graph ----


@app.get("/boards/{board_id}/graph")
def get_graph(board_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return storage.load_meta(user, board_id)


@app.post("/boards/{board_id}/nodes")
def create_node(board_id: str, payload: NodeCreate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return ga.create_node(
        user, board_id, payload.title, payload.kind, payload.node_type,
        parent=payload.parent, state=payload.state, ref=payload.ref,
        near=payload.near, x=payload.x, y=payload.y,
    )


@app.put("/boards/{board_id}/nodes/{node_id}")
def update_node(board_id: str, node_id: str, payload: NodeUpdate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = storage.load_meta(user, board_id)
    if node_id not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="node not found")
    updates = payload.model_dump(exclude_unset=True)
    node = meta["nodes"][node_id]

    # geometry/expand/color/ref go through graph_actions' move/update paths where applicable
    if any(k in updates for k in ("x", "y", "parent")):
        node = ga.move_node(
            user, board_id, node_id,
            x=updates.get("x"), y=updates.get("y"),
            parent=updates["parent"] if "parent" in updates else ...,
        )
        meta = storage.load_meta(user, board_id)
    if any(k in updates for k in ("title", "node_type")) or "state" in updates:
        node = ga.update_node(
            user, board_id, node_id,
            title=updates.get("title"),
            node_type=updates.get("node_type"),
            state=updates["state"] if "state" in updates else ...,
        )
        meta = storage.load_meta(user, board_id)
    for k in ("expanded", "width", "height", "color", "ref"):
        if k in updates:
            node[k] = updates[k]
    storage.save_meta(user, board_id, meta)
    return node


@app.delete("/boards/{board_id}/nodes/{node_id}")
def delete_node(board_id: str, node_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return ga.destroy_node(user, board_id, node_id)


@app.get("/boards/{board_id}/nodes/{node_id}/content")
def get_content(board_id: str, node_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = storage.load_meta(user, board_id)
    if node_id not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="node not found")
    return {"content": storage.read_content(user, board_id, node_id)}


@app.put("/boards/{board_id}/nodes/{node_id}/content")
def put_content(board_id: str, node_id: str, payload: ContentUpdate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = storage.load_meta(user, board_id)
    if node_id not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="node not found")
    if len(payload.content) > MAX_CONTENT_CHARS:
        raise HTTPException(status_code=413, detail=f"content too large (max {MAX_CONTENT_CHARS} chars)")
    storage.write_content(user, board_id, node_id, payload.content)
    return {"ok": True}


# ---- edges ----


@app.post("/boards/{board_id}/edges")
def create_edge(board_id: str, payload: EdgeCreate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return ga.link(user, board_id, payload.source, payload.target)


@app.delete("/boards/{board_id}/edges/{edge_id}")
def delete_edge(board_id: str, edge_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return ga.unlink(user, board_id, edge_id)


# ---- types ----


@app.get("/types")
def get_types(user: str = Depends(current_user)):
    return storage.load_types(user)


@app.put("/types")
def put_types(payload: dict, user: str = Depends(current_user)):
    # cybersec: type names become CSS classes/labels only — but keep them sane anyway
    for section in ("obj_types", "func_types"):
        if section in payload:
            for name, spec in payload[section].items():
                if not name or "/" in name or "\\" in name:
                    raise HTTPException(status_code=400, detail=f"invalid type name: {name!r}")
                color = spec.get("color", "")
                if color and not (color.startswith("#") and len(color) in (4, 7)):
                    raise HTTPException(status_code=400, detail=f"invalid color for {name!r}")
    storage.save_types(user, payload)
    return payload


# ---- versions ----


@app.get("/boards/{board_id}/versions")
def get_versions(board_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return {"versions": storage.list_versions(user, board_id)}


@app.post("/boards/{board_id}/versions")
def post_version(board_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return {"name": storage.save_version(user, board_id)}


@app.delete("/boards/{board_id}/versions/{name}")
def remove_version(board_id: str, name: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    name = validate_board_id(name)
    storage.delete_version(user, board_id, name)
    return {"ok": True}


@app.post("/boards/{board_id}/versions/{name}/restore")
def post_restore(board_id: str, name: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    name = validate_board_id(name)
    storage.restore_version(user, board_id, name)
    return storage.load_meta(user, board_id)


# ---- frontend ----


@app.get("/")
def index():
    return FileResponse(FRONT_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONT_DIR), name="static")
app.mount("/components", StaticFiles(directory=HUB_COMPONENTS_DIR), name="components")
