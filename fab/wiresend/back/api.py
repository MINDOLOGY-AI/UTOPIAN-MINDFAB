'''wiresend api + static frontend. the hub mounts this at /wiresend;
also runnable standalone (python -m fab.wiresend.back.api) for testing.
WS for events (the chat page), HTTP for file bytes — the house rule.
per user: the cookie resolves the user (http via the User dep, ws at upgrade);
channels live under users/{user}/wiresend/, nothing crosses users.'''

import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fab.config import udir
from fab.wiresend.back import chat, notify
from hub.back.auth import COOKIE_NAME, user_for_token

FRONT_DIR = Path.cwd() / "fab" / "wiresend" / "front"
HUB_FRONT = Path.cwd() / "hub" / "front"

app = FastAPI()


# the one door for http: cookie -> user
def current_user(request: Request) -> str:
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="not logged in")
    return user

User = Depends(current_user)


def _channels_payload(user: str) -> dict:
    return {"type": "channels", "channels": [
        {"id": c["id"], "name": c["name"], "members": c["members"],
         "readonly": c.get("readonly", []), "dm": c["dm"]}
        for c in chat.load_channels(user).values()]}


# the user touches a dm channel -> it materializes (lazy DM creation)
def _ensure_dm_if_touched(user: str, channel: str):
    if isinstance(channel, str) and channel.startswith("dm-"):
        chat.ensure_dm(user, channel[3:])


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # ws upgrades skip the http middleware — the cookie check happens here
    user = user_for_token(ws.cookies.get(COOKIE_NAME))
    if not user:
        await ws.close(code=1008)
        return
    await ws.accept()
    notify.clients.setdefault(user, set()).add(ws)
    notify.start_broadcaster()
    await ws.send_text(json.dumps(_channels_payload(user)))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            cmd = msg.get("cmd")

            if cmd == "list_channels":
                await ws.send_text(json.dumps(_channels_payload(user)))

            elif cmd == "create_channel":
                name = (msg.get("name") or "").strip()
                if not name:
                    await ws.send_text(json.dumps({"type": "error", "msg": "channel name required"}))
                    continue
                chat.create_channel(user, name, [chat.USER_SENDER] + msg.get("agents", []))
                notify.broadcast(_channels_payload(user), user=user)

            elif cmd == "set_members":
                channel = msg.get("channel")
                chat.set_members(user, channel, [chat.USER_SENDER] + msg.get("agents", []))
                notify.broadcast(_channels_payload(user), user=user)

            elif cmd == "set_readonly":
                chat.set_readonly(user, msg.get("channel"), msg.get("agent"), bool(msg.get("readonly")))
                notify.broadcast(_channels_payload(user), user=user)

            elif cmd == "rename_channel":
                chat.rename_channel(user, msg.get("channel"), msg.get("name") or "")
                notify.broadcast(_channels_payload(user), user=user)

            elif cmd == "delete_channel":
                chat.delete_channel(user, msg.get("channel"))
                notify.broadcast(_channels_payload(user), user=user)

            elif cmd == "get_messages":
                channel = msg.get("channel")
                _ensure_dm_if_touched(user, channel)
                msgs = chat.read_messages(user, channel, limit=int(msg.get("limit", 100)))
                await ws.send_text(json.dumps({"type": "messages", "channel": channel, "messages": msgs}))

            elif cmd == "chat_send":
                channel = msg.get("channel")
                text = msg.get("text", "")
                _ensure_dm_if_touched(user, channel)
                if text.strip():
                    m = chat.append_message(user, channel, chat.USER_SENDER, "text", text=text)
                    notify.message_posted(user, channel, m)

            else:
                await ws.send_text(json.dumps({"type": "error", "msg": f"unknown command: {cmd}"}))

    except WebSocketDisconnect:
        clients = notify.clients.get(user)
        if clients:
            clients.discard(ws)


# ---- this user's corechat agents, read at file level (same precedent as thoughtgraph/dockeruse) ----

@app.get("/agents")
def get_agents(user: str = User):
    names = set()
    agents_json = udir(user) / "agents.json"
    if agents_json.exists():
        names |= set(json.loads(agents_json.read_text()))
    agents_dir = udir(user) / "agents"
    if agents_dir.exists():
        names |= {p.name for p in agents_dir.iterdir()}
    return {"agents": sorted(names)}


# ---- channel files (HTTP for bytes) ----

@app.post("/chat/{channel_id}/files")
async def upload_chat_file(channel_id: str, request: Request, user: str = User):
    _ensure_dm_if_touched(user, channel_id)
    data = await request.body()
    if not data:
        raise ValueError("empty file")
    # relative path from query param — supports subdirectories (e.g. ?name=weights/model.pt)
    rel_path = request.query_params.get("name", "file")
    ref = chat.store_file(user, channel_id, rel_path, data)
    msg = chat.append_message(user, channel_id, chat.USER_SENDER, "file", file=ref)
    notify.message_posted(user, channel_id, msg)
    return msg


@app.get("/chat/{channel_id}/files-list")
def list_chat_files(channel_id: str, request: Request, user: str = User):
    return {"files": chat.list_file_tree(user, channel_id, request.query_params.get("path", ""))}


@app.post("/chat/{channel_id}/mkdir")
async def mkdir_channel(channel_id: str, request: Request, user: str = User):
    body = await request.json()
    dir_name = body.get("dir_name", "").strip()
    if not dir_name:
        raise ValueError("dir_name required")
    chat.mkdir_channel(user, channel_id, dir_name)
    return {"ok": True}


@app.put("/chat/{channel_id}/files/{path:path}")
async def rename_channel_file(channel_id: str, path: str, request: Request, user: str = User):
    body = await request.json()
    new_name = body.get("new_name", "").strip()
    if not new_name:
        raise ValueError("new_name required")
    chat.rename_file(user, channel_id, path, new_name)
    return {"ok": True}


@app.delete("/chat/{channel_id}/files/{path:path}")
def delete_channel_file(channel_id: str, path: str, user: str = User):
    chat.delete_file(user, channel_id, path)
    return {"ok": True}


@app.get("/chat/{channel_id}/files/{path:path}")
def download_chat_file(channel_id: str, path: str, user: str = User):
    p = chat.channel_file(user, channel_id, path)
    if not p.is_file():
        raise ValueError("file not found")
    return FileResponse(p, filename=p.name)


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
    uvicorn.run("fab.wiresend.back.api:app", host="127.0.0.1", port=2325)
