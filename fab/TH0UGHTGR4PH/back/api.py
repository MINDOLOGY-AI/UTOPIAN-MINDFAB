import io
import json
import shutil
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
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
    kind: str  # "doc" | "folder"
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
    edge_type: str


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


# ---- board zip download / upload ----

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _validate_meta(meta, user: str):
    """Legality check for an uploaded board: structure, kinds, titles, refs, types."""
    if not isinstance(meta, dict) or not isinstance(meta.get("nodes"), dict) or not isinstance(meta.get("edges"), dict):
        raise ValueError("meta.json must be an object with nodes and edges")
    types = storage.load_types(user)
    titles = set()
    for nid, n in meta["nodes"].items():
        if not isinstance(n, dict) or n.get("id") != nid:
            raise ValueError(f"node id mismatch or malformed node: {nid}")
        kind = n.get("kind")
        if kind not in ("doc", "folder"):
            raise ValueError(f"bad kind for node {nid}: {kind!r}")
        storage.validate_title(str(n.get("title", "")))
        if n["title"] in titles:
            raise ValueError(f"duplicate title: {n['title']!r}")
        titles.add(n["title"])
        if n.get("state") is not None and n["state"] not in ("todo", "doing", "done"):
            raise ValueError(f"bad state for {n['title']!r}")
        if kind == "doc" and n.get("node_type") not in types["doc_types"]:
            raise ValueError(f"unknown doc type: {n.get('node_type')!r}")
        parent = n.get("parent")
        if parent is not None:
            if parent not in meta["nodes"]:
                raise ValueError(f"parent not found for {n['title']!r}")
            if meta["nodes"][parent]["kind"] != "folder":
                raise ValueError(f"parent of {n['title']!r} is not a folder")
    for eid, e in meta["edges"].items():
        if e.get("source") not in meta["nodes"] or e.get("target") not in meta["nodes"]:
            raise ValueError(f"edge {eid} references a missing node")
        if e.get("edge_type") not in types["edge_types"]:
            raise ValueError(f"unknown edge type: {e.get('edge_type')!r}")
        if meta["nodes"][e["source"]]["kind"] == "folder" or meta["nodes"][e["target"]]["kind"] == "folder":
            raise ValueError("edges cannot touch folders")


@app.get("/boards/{board_id}/download")
def download_board(board_id: str, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    d = storage._board_dir(user, board_id)
    if not d.exists():
        raise HTTPException(status_code=404, detail="board not found")
    meta = json.loads((d / "meta.json").read_text())
    meta["board"] = board_id  # the name travels inside meta.json
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, indent=2))
        tree = d / "tree"
        if tree.exists():
            for p in sorted(tree.rglob("*")):
                if p.is_file():
                    z.write(p, f"tree/{p.relative_to(tree)}")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{board_id}.zip"'},
    )


@app.post("/boards/upload")
async def upload_board(request: Request, user: str = Depends(current_user)):
    # raw zip body (no multipart) — the board name travels inside meta.json
    # ('board' field), or ?name= for foreign zips
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="zip too large (max 50MB)")
    override = request.query_params.get("override") == "1"
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        # tolerate a single wrapping directory around the payload
        prefix = ""
        if "meta.json" not in names:
            candidates = [n for n in names if n.endswith("/meta.json") and n.count("/") == 1]
            if len(candidates) != 1:
                raise ValueError("zip must contain meta.json")
            prefix = candidates[0][:-len("meta.json")]
        meta = json.loads(z.read(prefix + "meta.json"))
        board_name = meta.get("board")  # name travels inside meta.json
        if not board_name and prefix + "board.json" in names:
            # back-compat with zips from the manifest experiment
            board_name = json.loads(z.read(prefix + "board.json")).get("name")
        if not board_name:
            board_name = request.query_params.get("name", "board")
        board_id = validate_board_id(board_name)
        _validate_meta(meta, user)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="not a zip file")
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    replacing = board_id in storage.list_boards(user)
    if replacing and not override:
        return JSONResponse(status_code=409, content={"detail": f"board '{board_id}' already exists"})
    if replacing:
        # never wipe versions: snapshot the pre-upload state as the newest
        # version, THEN overwrite the live board. past versions stay untouched.
        storage.save_version(user, board_id)
    else:
        storage.init_board(user, board_id)

    d = storage._board_dir(user, board_id)
    meta["board"] = board_id
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    tree = d / "tree"
    if tree.exists():
        shutil.rmtree(tree)
    for name in names:
        if not name.startswith(prefix + "tree/") or name.endswith("/"):
            continue
        rel = name[len(prefix):]
        dest = (d / rel).resolve()
        if not dest.is_relative_to(d.resolve()):  # cybersec: zip slip
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(z.read(name))
    return {"id": board_id}


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

    # x/y/parent go through graph_actions' move path; title/node_type/state through
    # update_node (they validate + sync content paths); expand/color/ref are plain fields
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
    return {"content": storage.read_content(user, board_id, meta, node_id)}


@app.put("/boards/{board_id}/nodes/{node_id}/content")
def put_content(board_id: str, node_id: str, payload: ContentUpdate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    meta = storage.load_meta(user, board_id)
    if node_id not in meta["nodes"]:
        raise HTTPException(status_code=404, detail="node not found")
    if len(payload.content) > MAX_CONTENT_CHARS:
        raise HTTPException(status_code=413, detail=f"content too large (max {MAX_CONTENT_CHARS} chars)")
    storage.write_content(user, board_id, meta, node_id, payload.content)
    return {"ok": True}


# ---- edges ----


@app.post("/boards/{board_id}/edges")
def create_edge(board_id: str, payload: EdgeCreate, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return ga.link(user, board_id, payload.source, payload.target, payload.edge_type)


@app.put("/boards/{board_id}/edges/{edge_id}")
def update_edge(board_id: str, edge_id: str, payload: dict, user: str = Depends(current_user)):
    board_id = validate_board_id(board_id)
    return ga.retype_edge(user, board_id, edge_id, payload["edge_type"])


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
    for section in ("doc_types", "edge_types"):
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
