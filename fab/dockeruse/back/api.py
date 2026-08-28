'''dockeruse REST api + vnc proxy + static frontend. the hub mounts this at /dockeruse;
also runnable standalone (python -m fab.dockeruse.back.api) for testing.
no websocket (except the vnc byte bridge): the watch page polls GET /containers.
every route is per-user: the cookie resolves the user, containers live under users/{user}/dockeruse/.'''

import asyncio
from pathlib import Path

import httpx
import websockets
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from fab.dockeruse.back import containers
from hub.back.auth import COOKIE_NAME, user_for_token

FRONT_DIR = Path.cwd() / "fab" / "dockeruse" / "front"
HUB_FRONT = Path.cwd() / "hub" / "front"

app = FastAPI()


# the one door: cookie -> user
def current_user(request: Request) -> str:
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="not logged in")
    return user

User = Depends(current_user)


# ---- containers (sync def = threadpool: create/start can block for minutes on a build) ----

@app.get("/containers")
def get_containers(user: str = User):
    return {"containers": containers.list_containers(user)}


@app.post("/containers")
def create_container(payload: dict, user: str = User):
    # the human's create: entry + port + first boot, so the container exists from now on
    return containers.create(user, payload["name"])


@app.delete("/containers/{name}")
def delete_container(name: str, workspace: str = "", user: str = User):
    containers.destroy(user, name, workspace=workspace == "1")
    return {"ok": True}


@app.post("/containers/{name}/start")
def start_container(name: str, user: str = User):
    containers.start(user, name)
    return {"ok": True}


@app.post("/containers/{name}/stop")
def stop_container(name: str, user: str = User):
    containers.stop(user, name)
    return {"ok": True}


@app.post("/containers/{name}/assign")
def assign_container(name: str, payload: dict, user: str = User):
    containers.assign(user, name, payload["agent"])
    return {"ok": True}


@app.post("/containers/{name}/unassign")
def unassign_container(name: str, user: str = User):
    containers.unassign(user, name)
    return {"ok": True}


# this user's corechat agents, read at file level — every read also garbage-collects
# assignments to agents that no longer exist
@app.get("/agents")
def get_agents(user: str = User):
    containers.gc_assignments(user)
    return {"agents": containers.agent_names(user)}


# ---- vnc proxy (near-verbatim copy from old_fab server.py; ownership is per-user now) ----

def _owned_vnc_port(user: str, port: str) -> int | None:
    """Return the port as int only if it belongs to one of THIS user's containers, else None."""
    # cybersec: only proxy numeric ports that appear in the user's containers.json — otherwise
    # anyone could reach arbitrary localhost services (or another user's desktop) through this proxy
    if not port.isdigit():
        return None
    port_num = int(port)
    for entry in containers.load(user).values():
        if entry["novnc_port"] == port_num:
            return port_num
    return None


@app.get("/vnc/{port}/{path:path}")
async def vnc_http_proxy(request: Request, port: str, path: str, user: str = User):
    """Proxy noVNC static assets (vnc.html, js, css) from the localhost-only container port."""
    port_num = _owned_vnc_port(user, port)
    if port_num is None:
        raise HTTPException(status_code=403, detail="unknown container port")
    client = httpx.AsyncClient()
    upstream = await client.send(
        client.build_request("GET", f"http://127.0.0.1:{port_num}/{path}", params=request.query_params),
        stream=True,
    )

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


@app.websocket("/vnc/{port}/websockify")
async def vnc_ws_proxy(ws: WebSocket, port: str):
    """Bridge the browser to the container's websockify (VNC over WebSocket), piping bytes both ways."""
    # ws upgrades skip the http middleware — the cookie check happens here
    user = user_for_token(ws.cookies.get(COOKIE_NAME))
    if not user:
        await ws.close(code=1008)
        return
    port_num = _owned_vnc_port(user, port)
    if port_num is None:
        # cybersec: reject before accept — this bridge gives full keyboard/mouse into the container
        await ws.close(code=1008)
        return
    # browser leg: noVNC offers no subprotocol by default — selecting one the client
    # didn't offer makes browsers abort the handshake. echo 'binary' only if offered.
    offered = ws.headers.get("sec-websocket-protocol", "")
    await ws.accept(subprotocol="binary" if "binary" in offered else None)
    # upstream leg: websockify requires the 'binary' subprotocol
    from websockets.typing import Subprotocol
    async with websockets.connect(
        f"ws://127.0.0.1:{port_num}/websockify", subprotocols=[Subprotocol("binary")], max_size=None
    ) as upstream:

        async def client_to_upstream():
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                data = msg.get("bytes")
                if data is not None:
                    await upstream.send(data)

        async def upstream_to_client():
            async for data in upstream:
                if isinstance(data, bytes):
                    await ws.send_bytes(data)
                else:
                    await ws.send_text(data)

        tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()


# ---- frontend ----
# absolute asset urls (/TechnoParadisal.css) resolve at the hub root when mounted;
# this route makes the standalone server serve the same file

@app.get("/TechnoParadisal.css")
def techno_css():
    return FileResponse(HUB_FRONT / "TechnoParadisal.css")


app.mount("/", StaticFiles(directory=FRONT_DIR, html=True))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("fab.dockeruse.back.api:app", host="127.0.0.1", port=2324)
