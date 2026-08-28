'''thoughtgraph REST api + static frontend. the hub mounts this at /thoughtgraph;
also runnable standalone (python -m fab.thoughtgraph.back.api) for testing.
no error handling anywhere: bad input raises and fastapi returns 500.
every route is per-user: the cookie resolves the user, storage.init(user) seeds their world on first touch.'''

import io
import json
import shutil
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from fab.config import udir
from fab.thoughtgraph.back import actions, storage
from fab.thoughtgraph.back.config import MAX_CONTENT_CHARS, MAX_UPLOAD_BYTES
from hub.back.auth import COOKIE_NAME, user_for_token

FRONT_DIR = Path.cwd() / "fab" / "thoughtgraph" / "front"
HUB_FRONT = Path.cwd() / "hub" / "front"

app = FastAPI()


# the one door: cookie -> user, and their thoughtgraph world gets seeded on first touch
def current_user(request: Request) -> str:
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="not logged in")
    storage.init(user)
    return user

User = Depends(current_user)


# board ids become folder paths
def _board(b: str) -> str:
    if not b or b in (".", "..") or "/" in b or "\\" in b or "\x00" in b:
        raise ValueError(f"invalid board id {b!r}")
    return b


# ---- boards ----

@app.get("/boards")
def get_boards(user: str = User):
    return {"boards": storage.list_boards(user)}


@app.post("/boards")
def create_board(payload: dict, user: str = User):
    storage.init_board(user, _board(payload["board_id"]))
    return {"id": payload["board_id"]}


@app.put("/boards/{board}")
def rename_board(board: str, payload: dict, user: str = User):
    storage.rename_board(user, _board(board), _board(payload["board_id"]))
    return {"id": payload["board_id"]}


@app.delete("/boards/{board}")
def delete_board(board: str, user: str = User):
    storage.delete_board(user, _board(board))
    return {"ok": True}


# ---- graph ----

@app.get("/boards/{board}/graph")
def get_graph(board: str, user: str = User):
    return storage.load_meta(user, _board(board))


@app.post("/boards/{board}/nodes")
def create_node(board: str, payload: dict, user: str = User):
    return actions.create_node(user, _board(board), payload["title"], payload["kind"],
                               payload.get("node_type", "doc"), parent=payload.get("parent"),
                               ref=payload.get("ref"), near=payload.get("near"),
                               x=payload.get("x"), y=payload.get("y"))


@app.put("/boards/{board}/nodes/{nid}")
def update_node(board: str, nid: str, payload: dict, user: str = User):
    fields = {k: payload[k] for k in
              ("title", "node_type", "x", "y", "parent", "expanded", "color", "width", "height")
              if k in payload}
    return actions.set_meta(user, _board(board), nid, **fields)


@app.delete("/boards/{board}/nodes/{nid}")
def delete_node(board: str, nid: str, user: str = User):
    return actions.destroy_node(user, _board(board), nid)


@app.get("/boards/{board}/nodes/{nid}/content")
def get_content(board: str, nid: str, user: str = User):
    meta = storage.load_meta(user, _board(board))
    return {"content": storage.read_content(user, board, meta, nid)}


@app.put("/boards/{board}/nodes/{nid}/content")
def put_content(board: str, nid: str, payload: dict, user: str = User):
    if len(payload["content"]) > MAX_CONTENT_CHARS:
        raise ValueError(f"content too large (max {MAX_CONTENT_CHARS} chars)")
    meta = storage.load_meta(user, _board(board))
    storage.write_content(user, board, meta, nid, payload["content"])
    return {"ok": True}


# ---- edges ----

@app.post("/boards/{board}/edges")
def create_edge(board: str, payload: dict, user: str = User):
    return actions.link(user, _board(board), payload["source"], payload["target"], payload["edge_type"])


@app.put("/boards/{board}/edges/{eid}")
def retype_edge(board: str, eid: str, payload: dict, user: str = User):
    meta = storage.load_meta(user, _board(board))
    e = meta["edges"][eid]
    return actions.link(user, board, e["source"], e["target"], payload["edge_type"])


@app.delete("/boards/{board}/edges/{eid}")
def delete_edge(board: str, eid: str, user: str = User):
    return actions.unlink_edge(user, _board(board), eid)


# ---- types + access (whole-file get/put, hand-editable on disk too) ----

@app.get("/types")
def get_types(user: str = User):
    return storage.load_types(user)


@app.put("/types")
def put_types(payload: dict, user: str = User):
    storage.save_types(user, payload)
    return payload


@app.get("/access")
def get_access(user: str = User):
    return storage.load_access(user)


@app.put("/access")
def put_access(payload: dict, user: str = User):
    storage.save_access(user, payload)
    return payload


# ---- agents + presets (the access panel's data) ----

# this user's corechat agents, read at file level — and every read garbage-collects
# access.json: entries whose agent no longer exists get deleted
@app.get("/agents")
def get_agents(user: str = User):
    names = set(storage.read_json(udir(user) / "agents.json", {}))
    agents_dir = udir(user) / "agents"
    if agents_dir.exists():
        names |= {p.name for p in agents_dir.iterdir()}
    access = storage.load_access(user)
    stale = [name for name in access if name not in names]
    if stale:
        for name in stale:
            del access[name]
        storage.save_access(user, access)
    return {"agents": sorted(names)}


@app.get("/presets")
def get_presets(user: str = User):
    return {"presets": storage.load_presets(user)}


@app.post("/presets/save")
def save_preset(payload: dict, user: str = User):
    presets = storage.load_presets(user)
    presets[payload["name"]] = storage.load_access(user).get(payload["agent"],
                                                             {"read": [], "write": []})
    storage.save_presets(user, presets)
    return {"ok": True}


@app.post("/presets/load")
def load_preset(payload: dict, user: str = User):
    preset = storage.load_presets(user)[payload["name"]]
    access = storage.load_access(user)
    access[payload["agent"]] = preset
    storage.save_access(user, access)
    return preset


# ---- board zip download / upload (the bridge to the user's own folders) ----

@app.get("/boards/{board}/download")
def download_board(board: str, user: str = User):
    board = _board(board)
    meta = storage.load_meta(user, board)
    meta["board"] = board  # the name travels inside meta.json
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, indent=2))
        tree = storage.tree_dir(user, board)
        for p in sorted(tree.rglob("*")):
            if p.is_file():
                z.write(p, f"tree/{p.relative_to(tree)}")
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{board}.zip"'})


@app.post("/boards/upload")
async def upload_board(request: Request, user: str = User):
    # raw zip body (no multipart); the board name travels inside meta.json ("board")
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("zip too large (max 50MB)")
    z = zipfile.ZipFile(io.BytesIO(data))
    meta = json.loads(z.read("meta.json"))
    board = _board(meta.get("board") or request.query_params.get("name", "board"))
    if board in storage.list_boards(user) and request.query_params.get("override") != "1":
        return JSONResponse(status_code=409, content={"detail": f"board '{board}' already exists"})
    storage.init_board(user, board)
    meta["board"] = board
    storage.save_meta(user, board, meta)
    tree = storage.tree_dir(user, board)
    if tree.exists():
        shutil.rmtree(tree)
    for name in z.namelist():
        if not name.startswith("tree/") or name.endswith("/"):
            continue
        dest = (storage.board_dir(user, board) / name).resolve()
        if not dest.is_relative_to(storage.board_dir(user, board).resolve()):  # zip slip
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(z.read(name))
    return {"id": board}


# ---- frontend ----
# absolute asset urls (/TechnoParadisal.css, /components/...) resolve at the hub root
# when mounted; these routes make the standalone server serve the same files

@app.get("/TechnoParadisal.css")
def techno_css():
    return FileResponse(HUB_FRONT / "TechnoParadisal.css")


app.mount("/components", StaticFiles(directory=HUB_FRONT / "components"))
app.mount("/", StaticFiles(directory=FRONT_DIR, html=True))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("fab.thoughtgraph.back.api:app", host="127.0.0.1", port=2323)
