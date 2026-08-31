import asyncio
import json
import os
import shutil
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from fab.config import udir
from fab.corechat.back.agent import Agent
from fab.dockeruse.back import containers
from fab.corechat.back.modelserver import ModelServer, KimiModelServer, DeepSeekModelServer
from fab.corechat.back.websocket import broadcast, clients, start_broadcaster
from hub.back.auth import COOKIE_NAME, user_for_token

# start background tasks once the event loop exists
@asynccontextmanager
async def lifespan(app):
    start_broadcaster()
    yield

app = FastAPI(lifespan=lifespan)

# in-memory agents: user -> name -> Agent (loaded on demand, created only via the create cmd)
agents: dict[str, dict[str, Agent]] = {}

# per-agent metadata: {"created": ts, "pinned": bool, "model_server_name": str, "model_name": str, "reasoning_effort": str, "context_limit": int}
# lives at users/{user}/agents.json, outside the agents dir so it never shows up as an agent
def agents_json(user: str):
    return udir(user)/"agents.json"

def agents_dir(user: str):
    return udir(user)/"agents"

DEFAULT_MODEL_META = {"model_server_name": "kimi", "model_name": "kimi-k3", "reasoning_effort": "high", "context_limit": 300_000}

def load_meta(user: str) -> dict:
    p = agents_json(user)
    return json.loads(p.read_text()) if p.exists() else {}

def save_meta(user: str, meta: dict):
    p = agents_json(user)
    p.parent.mkdir(parents=True, exist_ok=True)  # a user's first agent creates their dir
    p.write_text(json.dumps(meta))

# build a model server from an agent's meta entry; keys come from env at the server level
def new_modelserver(model_meta: dict) -> ModelServer:
    if model_meta["model_server_name"] == "deepseek":
        return DeepSeekModelServer(model_meta["model_name"], 8192, model_meta["reasoning_effort"], os.environ["DEEPSEEK_API_KEY"])
    return KimiModelServer(model_meta["model_name"], 8192, model_meta["reasoning_effort"], os.environ["MOONSHOT_API_KEY"])

# resume an existing on-disk agent into memory — never creates, creation only happens via the create cmd
def get_agent(user: str, name: str) -> Agent:
    mine = agents.setdefault(user, {})
    if name not in mine:
        assert (agents_dir(user)/name).exists(), f"no agent named {name}"
        meta = load_meta(user)[name]
        mine[name] = Agent(user, name, new_modelserver(meta), meta["context_limit"])
        asyncio.create_task(mine[name].run())
    return mine[name]

# the only path meant to make a new agent, used by the create cmd
def create_agent(user: str, name: str) -> Agent:
    meta = load_meta(user)
    meta[name] = {"created": time.time(), "pinned": False, **DEFAULT_MODEL_META}
    save_meta(user, meta)
    mine = agents.setdefault(user, {})
    mine[name] = Agent(user, name, new_modelserver(meta[name]), meta[name]["context_limit"])
    asyncio.create_task(mine[name].run())
    return mine[name]

# the create cmd's docker add-on: same-named container, assigned to the new agent. the agent stands either way
def _create_assigned_docker(user: str, name: str):
    try:
        containers.create(user, name)
        containers.assign(user, name, name)
    except Exception as e:
        broadcast({"type": "error", "name": name, "msg": f"docker setup failed: {e}"}, user=user)

def rename_agent(user: str, name: str, new_name: str):
    (agents_dir(user)/name).rename(agents_dir(user)/new_name)
    mine = agents.setdefault(user, {})
    agent = mine.pop(name, None)
    if agent:
        agent.name = new_name
        agent.working_context_path = agents_dir(user)/new_name
        mine[new_name] = agent
    meta = load_meta(user)
    meta[new_name] = meta.pop(name)
    save_meta(user, meta)

def delete_agent(user: str, name: str):
    agents.setdefault(user, {}).pop(name, None)
    shutil.rmtree(agents_dir(user)/name)
    meta = load_meta(user)
    meta.pop(name, None)
    save_meta(user, meta)

def pin_agent(user: str, name: str, pinned: bool):
    meta = load_meta(user)
    meta[name]["pinned"] = pinned
    save_meta(user, meta)

# switch an agent's model live: persist to meta, rebuild the in-memory server if the agent is loaded
def set_model(user: str, name: str, model_server_name: str, model_name: str):
    meta = load_meta(user)
    meta[name]["model_server_name"] = model_server_name
    meta[name]["model_name"] = model_name
    save_meta(user, meta)
    if name in agents.setdefault(user, {}):
        agents[user][name].model_server = new_modelserver(meta[name])

def set_reasoning_effort(user: str, name: str, reasoning_effort: str):
    meta = load_meta(user)
    meta[name]["reasoning_effort"] = reasoning_effort
    save_meta(user, meta)
    if name in agents.setdefault(user, {}):
        agents[user][name].model_server = new_modelserver(meta[name])

def set_context_limit(user: str, name: str, context_limit: int):
    meta = load_meta(user)
    meta[name]["context_limit"] = context_limit
    save_meta(user, meta)
    if name in agents.setdefault(user, {}):
        agents[user][name].context_limit = context_limit

# the one toggle: on arms agent mode (the next message you send starts the working loop — no api call on its own), off cancels the live turn and parks it
def toggle_run(user: str, name: str):
    agent = get_agent(user, name)
    if agent.agent_mode:
        agent.agent_mode = False
        if agent.current_turn:
            agent.current_turn.cancel()
    else:
        agent.agent_mode = True

# pinned first, then newest first
def agents_payload(user: str) -> dict:
    meta = load_meta(user)
    adir = agents_dir(user)
    names = [p.name for p in adir.iterdir()] if adir.exists() else []
    names.sort(key=lambda n: meta[n]["created"], reverse=True)
    names.sort(key=lambda n: meta[n]["pinned"], reverse=True)
    mine = agents.setdefault(user, {})
    infos = [{"name": n, "pinned": meta[n]["pinned"],
              "model_server_name": meta[n]["model_server_name"],
              "model_name": meta[n]["model_name"],
              "reasoning_effort": meta[n]["reasoning_effort"],
              "context_limit": meta[n]["context_limit"],
              "agent_mode": mine[n].agent_mode if n in mine else False} for n in names]
    return {"type": "agents", "agents": infos}

# turns broadcast the full context (the frontend owns incremental rendering and compression detection);
# opening a chat sends only the tail — older history is pulled via the history cmd as it backfills
def messages_payload(user: str, name: str, tail: bool = False) -> dict:
    agent = get_agent(user, name)
    ctx = agent.working_context
    start = max(0, len(ctx) - 20) if tail else 0
    return {"type": "messages", "name": name, "messages": ctx[start:], "words": agent.count_context_words(),
            "start": start, "total": len(ctx)}

# cmd dispatch, mirrors the frontend's handleMessage
def handle_message(msg: dict, ws: WebSocket, user: str):
    cmd = msg.get("cmd")

    if cmd == "list_agents":
        broadcast(agents_payload(user), client=ws)

    elif cmd == "create":
        create_agent(user, msg["name"])
        broadcast(agents_payload(user), user=user)
        # optional: a same-named docker, assigned to the new agent — first boot is slow, so thread it
        if msg.get("with_docker"):
            asyncio.create_task(asyncio.to_thread(_create_assigned_docker, user, msg["name"]))

    elif cmd == "rename":
        rename_agent(user, msg["name"], msg["new_name"])
        broadcast(agents_payload(user), user=user)

    elif cmd == "delete":
        delete_agent(user, msg["name"])
        broadcast(agents_payload(user), user=user)

    elif cmd == "pin":
        pin_agent(user, msg["name"], msg["pinned"])
        broadcast(agents_payload(user), user=user)

    elif cmd == "set_model":
        set_model(user, msg["name"], msg["model_server_name"], msg["model_name"])
        broadcast(agents_payload(user), user=user)

    elif cmd == "set_reasoning_effort":
        set_reasoning_effort(user, msg["name"], msg["reasoning_effort"])
        broadcast(agents_payload(user), user=user)

    elif cmd == "set_context_limit":
        set_context_limit(user, msg["name"], msg["context_limit"])
        broadcast(agents_payload(user), user=user)

    elif cmd == "toggle_run":
        toggle_run(user, msg["name"])
        broadcast(agents_payload(user), user=user)

    elif cmd == "get_messages":
        # a stale tab asking about a deleted agent is a normal race (deleted in another tab), not a bug —
        # don't answer; the agents payload already tells the page it's gone and it redirects itself
        if (agents_dir(user)/msg["name"]).exists():
            broadcast(messages_payload(user, msg["name"], tail=True), client=ws)

    elif cmd == "history":
        # backfill pull: the 20 messages before the index the page has drawn so far
        agent = get_agent(user, msg["name"])
        before = min(msg["before"], len(agent.working_context))
        start = max(0, before - 20)
        broadcast({"type": "history", "name": msg["name"], "start": start,
                   "messages": agent.working_context[start:before]}, client=ws)

    elif cmd == "chat":
        agent = get_agent(user, msg["name"])
        agent.inbox.append({"role": "user", "content": msg["content"]})
        # new input interrupts an in-flight turn — the re-turn sees both messages
        if agent.current_turn:
            agent.current_turn.cancel()
        agent.wake.set()

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # ws upgrades skip the http middleware — the cookie check happens here
    user = user_for_token(ws.cookies.get(COOKIE_NAME))
    if not user:
        await ws.close(code=1008)
        return
    await ws.accept()
    clients.setdefault(user, set()).add(ws)
    broadcast(agents_payload(user), client=ws)
    try:
        while True:
            handle_message(json.loads(await ws.receive_text()), ws, user)
    except WebSocketDisconnect:
        clients[user].discard(ws)

app.mount("/", StaticFiles(directory="fab/corechat/front", html=True))
