import asyncio
import json
import os
import shutil
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from fab.config import FAB_DIR
from fab.corechat.back.agent import Agent
from fab.corechat.back.modelserver import KimiModelServer
from fab.corechat.back.websocket import broadcast, clients, start_broadcaster

# start background tasks once the event loop exists
@asynccontextmanager
async def lifespan(app):
    start_broadcaster()
    yield

app = FastAPI(lifespan=lifespan)

agents: dict[str, Agent] = {}

# per-agent metadata: {"created": unix ts, "pinned": bool} — lives outside the agents dir so it never shows up as an agent
AGENTS_JSON = FAB_DIR/"agents.json"

def load_meta() -> dict:
    return json.loads(AGENTS_JSON.read_text()) if AGENTS_JSON.exists() else {}

def save_meta(meta: dict):
    AGENTS_JSON.write_text(json.dumps(meta))

# TODO: model selector. dont hardcode models.  
def new_kimi() -> KimiModelServer:
    # key comes from env at the server level
    return KimiModelServer("kimi-k3", 8192, "high", os.environ["MOONSHOT_API_KEY"])

# resume an existing on-disk agent into memory — never creates, creation only happens via the create cmd
def get_agent(name: str) -> Agent:
    if name not in agents:
        assert (FAB_DIR/"agents"/name).exists(), f"no agent named {name}"
        agents[name] = Agent(name, new_kimi())
    return agents[name]

# the only path meant to make a new agent, used by the create cmd
def create_agent(name: str) -> Agent:
    agents[name] = Agent(name, new_kimi())
    meta = load_meta()
    meta[name] = {"created": time.time(), "pinned": False}
    save_meta(meta)
    return agents[name]

def rename_agent(name: str, new_name: str):
    (FAB_DIR/"agents"/name).rename(FAB_DIR/"agents"/new_name)
    agent = agents.pop(name, None)
    if agent:
        agent.name = new_name
        agent.working_context_path = FAB_DIR/"agents"/new_name
        agents[new_name] = agent
    meta = load_meta()
    meta[new_name] = meta.pop(name)
    save_meta(meta)

def delete_agent(name: str):
    agents.pop(name, None)
    shutil.rmtree(FAB_DIR/"agents"/name)
    meta = load_meta()
    meta.pop(name, None)
    save_meta(meta)

def pin_agent(name: str, pinned: bool):
    meta = load_meta()
    meta[name]["pinned"] = pinned
    save_meta(meta)

# pinned first, then newest first; agents predating agents.json get created=0 and sink to the bottom
def agents_payload() -> dict:
    meta = load_meta()
    names = [p.name for p in (FAB_DIR/"agents").iterdir()]
    names.sort(key=lambda n: meta.get(n, {}).get("created", 0), reverse=True)
    names.sort(key=lambda n: meta.get(n, {}).get("pinned", False), reverse=True)
    return {"type": "agents", "agents": [{"name": n, "pinned": meta.get(n, {}).get("pinned", False)} for n in names]}

#send full context every time — the frontend owns incremental rendering and compression detection
def messages_payload(name: str) -> dict:
    return {"type": "messages", "name": name, "messages": get_agent(name).working_context}

# cmd dispatch, mirrors the frontend's handleMessage
async def handle_message(msg: dict, ws: WebSocket):
    cmd = msg.get("cmd")

    if cmd == "list_agents":
        await ws.send_text(json.dumps(agents_payload()))

    elif cmd == "create":
        create_agent(msg["name"])
        broadcast(agents_payload())

    elif cmd == "rename":
        rename_agent(msg["name"], msg["new_name"])
        broadcast(agents_payload())

    elif cmd == "delete":
        delete_agent(msg["name"])
        broadcast(agents_payload())

    elif cmd == "pin":
        pin_agent(msg["name"], msg["pinned"])
        broadcast(agents_payload())

    elif cmd == "get_messages":
        await ws.send_text(json.dumps(messages_payload(msg["name"])))

    elif cmd == "chat":
        agent = get_agent(msg["name"])
        agent.inbox.append({"role": "user", "content": msg["content"]})
        # set the flag synchronously — two chats in the same tick must not both start a turn
        if not agent.in_a_turn:
            agent.in_a_turn = True
            asyncio.create_task(agent.turn())

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_text(json.dumps(agents_payload()))
    try:
        while True:
            await handle_message(json.loads(await ws.receive_text()), ws)
    except WebSocketDisconnect:
        clients.discard(ws)

app.mount("/", StaticFiles(directory="fab/corechat/front", html=True))
