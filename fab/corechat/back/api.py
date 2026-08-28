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
from fab.corechat.back.modelserver import ModelServer, KimiModelServer, DeepSeekModelServer
from fab.corechat.back.websocket import broadcast, clients, start_broadcaster

# start background tasks once the event loop exists
@asynccontextmanager
async def lifespan(app):
    start_broadcaster()
    yield

app = FastAPI(lifespan=lifespan)

agents: dict[str, Agent] = {}

# per-agent metadata: {"created": ts, "pinned": bool, "model_server_name": str, "model_name": str, "reasoning_effort": str, "context_limit": int}
# lives outside the agents dir so it never shows up as an agent
AGENTS_JSON = FAB_DIR/"agents.json"

# model settings for agents created before agents.json had them
DEFAULT_MODEL_META = {"model_server_name": "kimi", "model_name": "kimi-k3", "reasoning_effort": "high", "context_limit": 300_000}

def load_meta() -> dict:
    return json.loads(AGENTS_JSON.read_text()) if AGENTS_JSON.exists() else {}

def save_meta(meta: dict):
    AGENTS_JSON.write_text(json.dumps(meta))

# build a model server from an agent's meta entry; keys come from env at the server level
def new_modelserver(model_meta: dict) -> ModelServer:
    if model_meta["model_server_name"] == "deepseek":
        return DeepSeekModelServer(model_meta["model_name"], 8192, model_meta["reasoning_effort"], os.environ["DEEPSEEK_API_KEY"])
    return KimiModelServer(model_meta["model_name"], 8192, model_meta["reasoning_effort"], os.environ["MOONSHOT_API_KEY"])

def model_meta_of(name: str) -> dict:
    return load_meta().get(name, DEFAULT_MODEL_META)

# resume an existing on-disk agent into memory — never creates, creation only happens via the create cmd
def get_agent(name: str) -> Agent:
    if name not in agents:
        assert (FAB_DIR/"agents"/name).exists(), f"no agent named {name}"
        meta = model_meta_of(name)
        agents[name] = Agent(name, new_modelserver(meta), meta["context_limit"])
        asyncio.create_task(agents[name].run())
    return agents[name]

# the only path meant to make a new agent, used by the create cmd
def create_agent(name: str) -> Agent:
    meta = load_meta()
    meta[name] = {"created": time.time(), "pinned": False, **DEFAULT_MODEL_META}
    save_meta(meta)
    agents[name] = Agent(name, new_modelserver(meta[name]), meta[name]["context_limit"])
    asyncio.create_task(agents[name].run())
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

# switch an agent's model live: persist to meta, rebuild the in-memory server if the agent is loaded
def set_model(name: str, model_server_name: str, model_name: str):
    meta = load_meta()
    meta[name]["model_server_name"] = model_server_name
    meta[name]["model_name"] = model_name
    save_meta(meta)
    if name in agents:
        agents[name].model_server = new_modelserver(meta[name])

def set_reasoning_effort(name: str, reasoning_effort: str):
    meta = load_meta()
    meta[name]["reasoning_effort"] = reasoning_effort
    save_meta(meta)
    if name in agents:
        agents[name].model_server = new_modelserver(meta[name])

def set_context_limit(name: str, context_limit: int):
    meta = load_meta()
    meta[name]["context_limit"] = context_limit
    save_meta(meta)
    if name in agents:
        agents[name].context_limit = context_limit

# the one toggle: on = agent mode + wake (starts working immediately), off = cancel the live turn and park it
def toggle_run(name: str):
    agent = get_agent(name)
    if agent.agent_mode:
        agent.agent_mode = False
        if agent.current_turn:
            agent.current_turn.cancel()
    else:
        agent.agent_mode = True
        agent.wake.set()

# pinned first, then newest first; agents predating agents.json get created=0 and sink to the bottom
def agents_payload() -> dict:
    meta = load_meta()
    names = [p.name for p in (FAB_DIR/"agents").iterdir()]
    names.sort(key=lambda n: meta.get(n, {}).get("created", 0), reverse=True)
    names.sort(key=lambda n: meta.get(n, {}).get("pinned", False), reverse=True)
    infos = []
    for n in names:
        m = {**DEFAULT_MODEL_META, **meta.get(n, {})}
        infos.append({"name": n, "pinned": m.get("pinned", False),
                      "model_server_name": m["model_server_name"],
                      "model_name": m["model_name"],
                      "reasoning_effort": m["reasoning_effort"],
                      "context_limit": m["context_limit"],
                      "agent_mode": agents[n].agent_mode if n in agents else False})
    return {"type": "agents", "agents": infos}

#send full context every time — the frontend owns incremental rendering and compression detection
def messages_payload(name: str) -> dict:
    agent = get_agent(name)
    return {"type": "messages", "name": name, "messages": agent.working_context, "words": agent.count_context_words()}

# cmd dispatch, mirrors the frontend's handleMessage
def handle_message(msg: dict, ws: WebSocket):
    cmd = msg.get("cmd")

    if cmd == "list_agents":
        broadcast(agents_payload(), ws)

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

    elif cmd == "set_model":
        set_model(msg["name"], msg["model_server_name"], msg["model_name"])
        broadcast(agents_payload())

    elif cmd == "set_reasoning_effort":
        set_reasoning_effort(msg["name"], msg["reasoning_effort"])
        broadcast(agents_payload())

    elif cmd == "set_context_limit":
        set_context_limit(msg["name"], msg["context_limit"])
        broadcast(agents_payload())

    elif cmd == "toggle_run":
        toggle_run(msg["name"])
        broadcast(agents_payload())

    elif cmd == "get_messages":
        broadcast(messages_payload(msg["name"]), ws)

    elif cmd == "chat":
        agent = get_agent(msg["name"])
        agent.inbox.append({"role": "user", "content": msg["content"]})
        # new input interrupts an in-flight turn — the re-turn sees both messages
        if agent.current_turn:
            agent.current_turn.cancel()
        agent.wake.set()

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    broadcast(agents_payload(), ws)
    try:
        while True:
            handle_message(json.loads(await ws.receive_text()), ws)
    except WebSocketDisconnect:
        clients.discard(ws)

app.mount("/", StaticFiles(directory="fab/corechat/front", html=True))
