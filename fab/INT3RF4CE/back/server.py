"""
WebSocket server for agent management. Multi-user: every connection is bound to the
session user; agents, data folders, and broadcasts are all scoped per-user.

Commands (client -> server):
    {"cmd": "list"}
    {"cmd": "create", "name": "agent_1", "model": "kimi-k3"}
    {"cmd": "start", "name": "agent_1"}        work loop on (chat_mode off); also un-stops a STOPped agent
    {"cmd": "pause", "name": "agent_1"}        halt work loop / chat turn; container keeps running
    {"cmd": "kill", "name": "agent_1"}         halt + destroy container (alias: "docker_stop")
    {"cmd": "docker_start", "name": "agent_1"} container only, no work loop
    {"cmd": "delete", "name": "agent_1"}       destroy container + workspace + context
    {"cmd": "rename", "name": "agent_1", "new_name": "agent_2"}
    {"cmd": "chat", "name": "agent_1", "text": "do this task"}
    {"cmd": "chat_mode", "name": "agent_1", "enabled": true}
    {"cmd": "get_context", "name": "agent_1"}
    {"cmd": "list_models"} / {"cmd": "set_model", "name", "model"}
    channels:
    {"cmd": "list_channels"} / {"cmd": "create_channel", "name", "agents": [...]}
    {"cmd": "set_members", "channel", "agents": [...]} / {"cmd": "rename_channel", "channel", "name"}
    {"cmd": "delete_channel", "channel"}
    {"cmd": "get_messages", "channel", "limit"} / {"cmd": "chat_send", "channel", "text"}
    thoughtgraph access (per agent):
    {"cmd": "get_graph_settings", "name"} / {"cmd": "set_graph_settings", "name", "settings": {...}}
    {"cmd": "list_settings_files"} / {"cmd": "save_settings_file", "name", "file_name"}
    {"cmd": "load_settings_file", "name", "file_name"}
    secrets:
    {"cmd": "list_secrets"} / {"cmd": "set_secret", "key", "value", "cat"} / {"cmd": "delete_secret", "key"}
    {"cmd": "get_secret_grants", "name"} / {"cmd": "set_secret_grants", "name", "grants": [...]}
    compute:
    {"cmd": "list_computes"} / {"cmd": "add_compute", "name", "ssh_command", "password"}
    {"cmd": "delete_compute", "name"} / {"cmd": "claim_compute", "name"} / {"cmd": "release_compute", "name"}

Responses (server -> client):
    {"type": "agents", "agents": {...}}
    {"type": "context", "name": "agent_1", "messages": [...]}
    {"type": "models", "models": {...}}
    {"type": "status", "name": "agent_1", "phase": "api_call", "state": "started"}
    {"type": "channels", ...} / {"type": "messages", ...} / {"type": "chat_message", ...}
    {"type": "graph_settings", ...} / {"type": "settings_files", ...}
    {"type": "secrets", ...} / {"type": "secret_grants", ...}
    {"type": "auth_required"} / {"type": "error", "msg": "..."}

"""

import base64
import json
import re
import asyncio
import logging
import subprocess
import shutil
from pathlib import Path
from urllib.parse import urlparse

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from fab.TH0UGHTGR4PH.back import storage as tg_storage
from fab.TH0UGHTGR4PH.back import graph_actions as tg_actions
from fab.INT3RF4CE.back import chat as chatmod
from fab.INT3RF4CE.back import secrets as secretsmod
from fab.INT3RF4CE.back import compute as computemod
from fab.INT3RF4CE.back.agent import Agent
from fab.INT3RF4CE.back.model import Model, MODEL_PROVIDERS, list_available_models, get_model_class, list_model_capabilities
from fab.INT3RF4CE.back.models.kimi import Kimi  # registers the kimi provider
from fab.INT3RF4CE.back.models.deepseek import DeepSeek  # registers the deepseek provider
from fab.INT3RF4CE.back.model import HierarchyModel  # registers the hierarchy provider
from fab.INT3RF4CE.back.config import DATA_DIR
from fab.hub.auth.store import COOKIE_NAME, user_for_token

app = FastAPI()

BASE_PORT = 6080

# cybersec: names become folder paths and docker container names, so only allow plain safe characters
NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_name(name: str):
    # cybersec: reject '..' and slashes in names — without this an attacker could delete or write files outside their own folder
    if not name or not NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail=f"invalid name: {name!r}")

# users: {username: {agent_name: {"agent": Agent, "novnc_port": int, "model": str,
#           "container_on": bool, "working": bool}}}
users: dict[str, dict[str, dict]] = {}

# ---- channel chat files (per-channel store; replaces the shared-folder design) ----

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".css",
             ".log", ".yaml", ".yml", ".toml", ".xml", ".svg", ".sh", ".c", ".cpp", ".h"}
MAX_ATTACH_CHARS = 20_000
# agent-view attachments ride base64 inside a WS message — big files belong in channel upload
MAX_WS_ATTACH_BYTES = 25 * 1024 * 1024


def _block_for_file(p: Path) -> dict | None:
    """One-turn content block for a file: image block for images, inline text
    for text-like files, None for anything else."""
    from fab.INT3RF4CE.back.context import Context
    ext = p.suffix.lower()
    if ext in IMAGE_EXTS:
        return Context.image_block(p.read_bytes())
    if ext in TEXT_EXTS:
        text = p.read_text(errors="replace")[:MAX_ATTACH_CHARS]
        return {"type": "text", "text": f"[attached file: {p.name}]\n{text}"}
    return None


def inject_pending(user: str, name: str, info: dict):
    """Deliver the agent's unread channel messages into its next turn:
    a user text block summarizing them + one-turn attachment blocks for files."""
    agent = info["agent"]
    pend = chatmod.pending_messages(user, name)
    if not pend:
        return
    lines, blocks = [], []
    for cid, msgs in pend.items():
        ch = chatmod.channel_of(user, cid)
        latest = 0.0
        for m in msgs:
            latest = max(latest, m["ts"])
            who = "you" if m["sender"] == chatmod.USER_SENDER else m["sender"]
            if m["type"] == "file":
                lines.append(f"[chat #{ch['name']} from {who}] file: {m['file']['name']} ({m['file']['size']} bytes)")
                p = chatmod.channel_file(user, cid, m["file"]["path"])
                if p.is_file():
                    b = _block_for_file(p)
                    if b:
                        blocks.append(b)
                    else:
                        lines[-1] += " (not inlined)"
            else:
                lines.append(f"[chat #{ch['name']} from {who}] {m.get('text', '')}")
        chatmod.mark_read(user, name, cid, latest)
    agent.context.add_user_text("\n".join(lines))
    if blocks:
        agent.context.pending_attachments = blocks


@app.post("/chat/{channel_id}/files")
async def upload_chat_file(channel_id: str, request: Request):
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    if channel_id.startswith("dm-") and channel_id[3:] in users.get(user, {}):
        chatmod.ensure_dm(user, channel_id[3:])
    if not chatmod.is_member(user, channel_id, chatmod.USER_SENDER):
        raise HTTPException(status_code=404, detail="channel not found")
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    # relative path from query param — supports subdirectories (e.g. ?name=weights/model.pt)
    rel_path = request.query_params.get("name", "file")
    try:
        ref = chatmod.store_file(user, channel_id, rel_path, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    msg = chatmod.append_message(user, channel_id, chatmod.USER_SENDER, "file", file=ref)
    await broadcast(user, {"type": "chat_message", "channel": channel_id, "message": msg})
    return msg


@app.get("/chat/{channel_id}/files-list")
def list_chat_files(channel_id: str, request: Request):
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    if not chatmod.is_member(user, channel_id, chatmod.USER_SENDER):
        raise HTTPException(status_code=404, detail="channel not found")
    entries = chatmod.list_file_tree(user, channel_id, request.query_params.get("path", ""))
    return {"files": entries}


@app.post("/chat/{channel_id}/mkdir")
async def mkdir_channel(channel_id: str, request: Request):
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    if not chatmod.is_member(user, channel_id, chatmod.USER_SENDER):
        raise HTTPException(status_code=404, detail="channel not found")
    body = await request.json()
    dir_name = body.get("dir_name", "").strip()
    if not dir_name:
        raise HTTPException(status_code=400, detail="dir_name required")
    try:
        chatmod.mkdir_channel(user, channel_id, dir_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.put("/chat/{channel_id}/files/{path:path}")
async def rename_channel_file(channel_id: str, path: str, request: Request):
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    if not chatmod.is_member(user, channel_id, chatmod.USER_SENDER):
        raise HTTPException(status_code=404, detail="channel not found")
    body = await request.json()
    new_name = body.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name required")
    try:
        chatmod.rename_file(user, channel_id, path, new_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.delete("/chat/{channel_id}/files/{path:path}")
async def delete_channel_file(channel_id: str, path: str, request: Request):
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    if not chatmod.is_member(user, channel_id, chatmod.USER_SENDER):
        raise HTTPException(status_code=404, detail="channel not found")
    try:
        chatmod.delete_file(user, channel_id, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.get("/chat/{channel_id}/files/{path:path}")
def download_chat_file(channel_id: str, path: str, request: Request):
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    try:
        p = chatmod.channel_file(user, channel_id, path)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad path")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(p, filename=p.name)


@app.get("/chat/")
def chat_page():
    return FileResponse(FRONT_DIR / "chat.html")


@app.get("/secrets/")
def secrets_page():
    return FileResponse(FRONT_DIR / "secrets.html")


@app.get("/compute/")
def compute_page():
    return FileResponse(FRONT_DIR / "compute.html")

# connected websocket clients: ws -> username
clients: dict[WebSocket, str] = {}


def agents_file(user: str) -> Path:
    # persisted per user: fab/data/INT3RF4CE/{user}/agents.json — {"agent_name": {"novnc_port": int, "model": str}, ...}
    return DATA_DIR / user / "agents.json"


def save_agents(user: str):
    """Save a user's agent configs to disk."""
    path = agents_file(user)
    path.parent.mkdir(parents=True, exist_ok=True)
    configs = {
        name: {
            "novnc_port": info["novnc_port"],
            "model": info.get("model", "kimi-k3"),
            "chat_mode": info["agent"].chat_mode,
        }
        for name, info in users.get(user, {}).items()
    }
    path.write_text(json.dumps(configs))


def next_port() -> int:
    # ports are allocated across ALL users' agents
    used = {info["novnc_port"] for agents in users.values() for info in agents.values()}
    port = BASE_PORT
    while port in used:
        port += 1
    return port


def is_container_running(docker_name: str) -> bool:
    """Check if a docker container is actually running."""
    result = subprocess.run(
        ["docker", "ps", "-q", "-f", f"name=^{docker_name}$"],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def _make_model(user: str, model_name: str) -> Model:
    provider = get_model_class(model_name)
    if provider is None:
        raise ValueError(f"unknown model {model_name}")
    # API keys resolve from the user's secrets store first; providers fall back to env vars
    return provider.make(model_name, get_key=lambda name: secretsmod.resolve(user, name))


def _all_model_ids() -> set[str]:
    return {model_id for provider in list_available_models().values() for model_id in provider.values()}


def _attach_status_handler(user: str, name: str, agent: Agent):
    """Wire the agent's status callback to broadcast + drive state.

    The agent is self-driving: DOCKER_START/STOP flip chat_mode and container
    state, and these notifications start/stop the work loop accordingly.
    """
    def handler(status: dict):
        info = users.get(user, {}).get(name)
        if info:
            if status.get("phase") == "chat_mode":
                if status.get("state") == "off" and not info["working"]:
                    info["working"] = True
                    info["work_loop"] = asyncio.create_task(work_loop(user, name, info))
                    logger.info("[chat_mode off] %s/%s work loop started by agent", user, name)
                elif status.get("state") == "on" and info["working"]:
                    info["working"] = False
                    if info.get("work_loop") and not info["work_loop"].done():
                        info["work_loop"].cancel()
                        info["work_loop"] = None
                    logger.info("[chat_mode on] %s/%s work loop stopped by agent", user, name)
            elif status.get("phase") == "container":
                info["container_on"] = status.get("state") == "started"
        asyncio.create_task(broadcast(user, {"type": "status", "name": name, **status}))
    agent.on_status = handler

    def on_stop():
        # the agent called STOP: halt the work loop. it cannot restart itself —
        # only a user "start"/"chat_mode off" clears agent.stopped.
        info = users.get(user, {}).get(name)
        if not info:
            return
        info["working"] = False
        # no cancel: STOP arrives mid-turn inside the loop; the loop exits
        # cleanly on its own after this turn's tool results are saved
        logger.info("[STOP] %s/%s stopped itself", user, name)
        asyncio.create_task(broadcast(user, {"type": "agents", "agents": get_agents_info(user)}))
    agent.on_stop = on_stop


def load_agents():
    """Load every user's agent configs from disk on startup."""
    for path in sorted(DATA_DIR.glob("*/agents.json")):
        user = path.parent.name
        configs = json.loads(path.read_text())
        user_agents = users.setdefault(user, {})
        for name, cfg in configs.items():
            # cybersec: skip invalid names from disk — they flow into the docker ps name filter and folder paths
            try:
                validate_name(name)
            except HTTPException:
                continue
            novnc_port = cfg["novnc_port"]
            model_name = cfg.get("model", "kimi-k3")
            model = _make_model(user, model_name)
            agent = Agent(user, name, model, use_container=True, novnc_port=novnc_port,
                          chat_mode=cfg.get("chat_mode", True))
            _attach_status_handler(user, name, agent)
            chatmod.ensure_dm(user, name)
            container_on = is_container_running(agent.container.name)
            if container_on:
                agent.container._running = True
            user_agents[name] = {
                "agent": agent,
                "novnc_port": novnc_port,
                "model": model_name,
                "container_on": container_on,
                "working": False,
            }


load_agents()


async def broadcast(user: str, msg: dict):
    """Send message to all of one user's connected clients."""
    text = json.dumps(msg)
    for client, client_user in clients.items():
        if client_user != user:
            continue
        try:
            await client.send_text(text)
        except Exception:
            pass


def _computes_payload(user: str) -> dict:
    usage = computemod.usage_map(user)
    return {"type": "computes", "computes": [
        {"name": c["name"], "ssh_command": c["ssh_command"], "password": c["password"], "used_by": usage.get(c["name"])}
        for c in computemod.list_computers(user)
    ]}


# any compute mutation (page actions AND agent-side USE_COMPUTER/RELEASE_COMPUTER,
# which run in this process via agent.py) refreshes every open compute page
computemod.set_on_change(lambda user: asyncio.create_task(broadcast(user, _computes_payload(user))))


def get_agents_info(user: str) -> dict:
    return {
        name: {
            "container_on": info["container_on"],
            "working": info["working"],
            "novnc_port": info["novnc_port"],
            "model": info.get("model", "kimi-k3"),
            "chat_mode": info["agent"].chat_mode,
        }
        for name, info in users.get(user, {}).items()
    }


async def work_loop(user: str, name: str, info: dict):
    logger.info("[work_loop] %s/%s started", user, name)
    agent = info["agent"]
    if not agent.context.messages:
        agent.context.add_user_text("start working")
    while info["working"]:
        try:
            inject_pending(user, name, info)
            await agent.turn()
            await broadcast(user, {"type": "context", "name": name, "messages": agent.context.messages})
        except asyncio.CancelledError:
            logger.info("[work_loop] %s/%s cancelled", user, name)
            break
        except asyncio.TimeoutError:
            logger.warning("[work_loop] %s/%s API TIMEOUT — retrying in 5s", user, name)
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception("[work_loop] %s/%s error: %s", user, name, e)
            await asyncio.sleep(5)
    logger.info("[work_loop] %s/%s stopped", user, name)


async def cancel_and_settle(info: dict, key: str):
    """Cancel a running task (work loop / chat turn) and WAIT for it to settle.
    task.cancel() only schedules the CancelledError — touching the agent's
    context before the task actually stops would race its final writes."""
    task = info.get(key)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    info[key] = None


def reconcile_task_assignment(user: str, agent_name: str, old_settings: dict | None, new_settings: dict):
    """The to-do (time) list IS the agent's task queue: dragging a node in assigns
    it, taking one out unassigns it. Assigning a node already marked 'doing'
    transfers the claim to the agent; unassigning releases the agent's doing
    task back to todo. Runs as the owner — no transition guard needed here."""
    old_time = {(e["board"], e["id"]) for e in (old_settings or {}).get("time", [])}
    new_time = {(e["board"], e["id"]) for e in new_settings.get("time", [])}
    for board in {b for b, _ in old_time | new_time}:
        meta = tg_storage.load_meta(user, board)
        dirty = False
        for b, nid in new_time - old_time:
            if b != board:
                continue
            node = meta["nodes"].get(nid)
            if node and node.get("state") == "doing" and node.get("assignee") != agent_name:
                node["assignee"] = agent_name
                dirty = True
        for b, nid in old_time - new_time:
            if b != board:
                continue
            node = meta["nodes"].get(nid)
            if node and node.get("state") == "doing" and node.get("assignee") == agent_name:
                node["state"] = "todo"
                node["assignee"] = None
                dirty = True
        if dirty:
            tg_storage.save_meta(user, board, meta)


def agent_task_list(user: str, agent_name: str) -> list[dict]:
    """One agent's task queue for the chat popup: stateful nodes from its to-do
    (time) list, plus stateful nodes inside its total-control folders (folder
    total implies time). doing first, then todo, then done; sorted by path."""
    path = DATA_DIR / user / "config" / "specific" / agent_name / "graph.json"
    if not path.exists():
        return []
    try:
        settings = json.loads(path.read_text())
    except Exception:
        return []
    time_entries = settings.get("time", [])
    folder_entries = settings.get("folders", [])
    metas = {}
    for b in {e["board"] for e in time_entries + folder_entries}:
        try:
            metas[b] = tg_storage.load_meta(user, b)
        except Exception:
            pass
    tasks, seen = [], set()

    def add(board, nid):
        node = metas[board]["nodes"].get(nid)
        if not node or not node.get("state") or (board, nid) in seen:
            return
        seen.add((board, nid))
        tasks.append({"board": board, "path": tg_actions.node_path(metas[board], nid),
                      "state": node["state"], "assignee": node.get("assignee")})

    for e in time_entries:
        if e["board"] in metas:
            add(e["board"], e["id"])
    for e in folder_entries:
        meta = metas.get(e["board"])
        if not meta:
            continue
        for nid in meta["nodes"]:
            cur = nid
            while cur:  # walk up: is nid inside the controlled folder?
                if cur == e["id"]:
                    add(e["board"], nid)
                    break
                parent = meta["nodes"].get(cur)
                cur = parent["parent"] if parent else None
    order = {"doing": 0, "todo": 1, "done": 2}
    tasks.sort(key=lambda t: (order.get(t["state"], 3), t["path"].lower()))
    return tasks


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # cybersec: block cross-site WebSocket hijacking — browsers send Origin, and if it doesn't match our Host another site is driving the victim's session. closing before accept makes the handshake fail with 403
    origin = ws.headers.get("origin")
    if origin is not None and urlparse(origin).netloc != ws.headers.get("host"):
        await ws.close(code=1008)
        return

    # auth gate: INT3RF4CE requires a site login. reject before any state is touched.
    user = user_for_token(ws.cookies.get(COOKIE_NAME))
    if not user:
        await ws.accept()
        await ws.send_text(json.dumps({"type": "auth_required"}))
        await ws.close()
        return

    await ws.accept()
    clients[ws] = user
    user_agents = users.setdefault(user, {})

    await ws.send_text(json.dumps({"type": "agents", "agents": get_agents_info(user)}))

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            cmd = msg.get("cmd")

            if cmd == "list":
                await ws.send_text(json.dumps({"type": "agents", "agents": get_agents_info(user)}))

            elif cmd == "create":
                name = msg.get("name")
                novnc_port = next_port()
                model_name = msg.get("model", "kimi-k3")

                if not name:
                    await ws.send_text(json.dumps({"type": "error", "msg": "name required"}))
                    continue

                # cybersec: the name becomes a folder path and docker name — allowlist it before anything touches disk
                try:
                    validate_name(name)
                except HTTPException as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": e.detail}))
                    continue

                if name in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} already exists"}))
                    continue

                if model_name not in _all_model_ids():
                    await ws.send_text(json.dumps({"type": "error", "msg": f"unknown model {model_name}"}))
                    continue

                model = _make_model(user, model_name)
                agent = Agent(user, name, model, use_container=True, novnc_port=novnc_port)
                _attach_status_handler(user, name, agent)

                user_agents[name] = {
                    "agent": agent,
                    "novnc_port": novnc_port,
                    "model": model_name,
                    "container_on": False,
                    "working": False,
                }
                chatmod.ensure_dm(user, name)

                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            # ---- channels (user-managed; agents talk via CHAT_* tools) ----
            elif cmd == "list_channels":
                chans = [{"id": c["id"], "name": c["name"], "members": c["members"], "dm": c["dm"]}
                         for c in chatmod.load_channels(user).values()]
                await ws.send_text(json.dumps({"type": "channels", "channels": chans}))

            elif cmd == "create_channel":
                chan_name = (msg.get("name") or "").strip()
                members = [chatmod.USER_SENDER] + [a for a in msg.get("agents", []) if a in user_agents]
                if not chan_name:
                    await ws.send_text(json.dumps({"type": "error", "msg": "channel name required"}))
                    continue
                chatmod.create_channel(user, chan_name, members)
                chans = [{"id": c["id"], "name": c["name"], "members": c["members"], "dm": c["dm"]}
                         for c in chatmod.load_channels(user).values()]
                await broadcast(user, {"type": "channels", "channels": chans})

            elif cmd == "set_members":
                channel = msg.get("channel")
                agents = [a for a in msg.get("agents", []) if a in user_agents]
                if not chatmod.is_member(user, channel, chatmod.USER_SENDER):
                    await ws.send_text(json.dumps({"type": "error", "msg": "channel not found"}))
                    continue
                chatmod.set_members(user, channel, [chatmod.USER_SENDER] + agents)
                chans = [{"id": c["id"], "name": c["name"], "members": c["members"], "dm": c["dm"]}
                         for c in chatmod.load_channels(user).values()]
                await broadcast(user, {"type": "channels", "channels": chans})

            elif cmd == "rename_channel":
                channel = msg.get("channel")
                new_name = (msg.get("name") or "").strip()
                if not chatmod.is_member(user, channel, chatmod.USER_SENDER):
                    await ws.send_text(json.dumps({"type": "error", "msg": "channel not found"}))
                    continue
                try:
                    chatmod.rename_channel(user, channel, new_name)
                except ValueError as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": str(e)}))
                    continue
                chans = [{"id": c["id"], "name": c["name"], "members": c["members"], "dm": c["dm"]}
                         for c in chatmod.load_channels(user).values()]
                await broadcast(user, {"type": "channels", "channels": chans})

            elif cmd == "delete_channel":
                channel = msg.get("channel")
                if not chatmod.is_member(user, channel, chatmod.USER_SENDER):
                    await ws.send_text(json.dumps({"type": "error", "msg": "channel not found"}))
                    continue
                chatmod.delete_channel(user, channel)
                chans = [{"id": c["id"], "name": c["name"], "members": c["members"], "dm": c["dm"]}
                         for c in chatmod.load_channels(user).values()]
                await broadcast(user, {"type": "channels", "channels": chans})

            elif cmd == "get_messages":
                channel = msg.get("channel")
                # a deleted dm auto-recreates: the agent view always expects one
                if isinstance(channel, str) and channel.startswith("dm-") and channel[3:] in user_agents:
                    chatmod.ensure_dm(user, channel[3:])
                if not chatmod.is_member(user, channel, chatmod.USER_SENDER):
                    await ws.send_text(json.dumps({"type": "error", "msg": "channel not found"}))
                    continue
                msgs = chatmod.read_messages(user, channel, limit=int(msg.get("limit", 100)))
                await ws.send_text(json.dumps({"type": "messages", "channel": channel, "messages": msgs}))

            elif cmd == "chat_send":
                channel = msg.get("channel")
                text = msg.get("text", "")
                if isinstance(channel, str) and channel.startswith("dm-") and channel[3:] in user_agents:
                    chatmod.ensure_dm(user, channel[3:])
                if not chatmod.is_member(user, channel, chatmod.USER_SENDER):
                    await ws.send_text(json.dumps({"type": "error", "msg": "channel not found"}))
                    continue
                if text.strip():
                    m = chatmod.append_message(user, channel, chatmod.USER_SENDER, "text", text=text)
                    await broadcast(user, {"type": "chat_message", "channel": channel, "message": m})

            # ---- agent lifecycle ----
            elif cmd == "start":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                info = user_agents[name]
                # start = the model is ON. in single-turn mode it answers one turn
                # per message; otherwise the work loop runs turns back-to-back.
                # also the one way back from an agent's own STOP.
                info["agent"].stopped = False
                if not info["working"]:
                    info["working"] = True
                    if not info["agent"].chat_mode:
                        info["work_loop"] = asyncio.create_task(work_loop(user, name, info))
                        logger.info("[start] %s/%s work loop created", user, name)

                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "docker_start":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue
                info = user_agents[name]
                # container only — the user wants the machine, not necessarily the model
                agent = info["agent"]
                if agent.container and not agent.container._running:
                    await asyncio.to_thread(agent.container.start)
                info["container_on"] = True
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "pause":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                info = user_agents[name]
                if info["working"]:
                    info["working"] = False
                    if info.get("work_loop") and not info["work_loop"].done():
                        logger.info("[pause] %s/%s work loop cancelled", user, name)
                    await cancel_and_settle(info, "work_loop")
                    agent = info["agent"]
                    # a cancelled turn can leave dangling tool_use — close them or
                    # every later API call rejects the context (silent failure)
                    agent.context.close_dangling_tool_calls()
                    await broadcast(user, {"type": "context", "name": name, "messages": agent.context.messages})
                # stop also halts an in-flight chat-mode turn
                if info.get("chat_task") and not info["chat_task"].done():
                    logger.info("[pause] %s/%s chat turn cancelled", user, name)
                await cancel_and_settle(info, "chat_task")
                if not info["working"]:
                    info["agent"].context.close_dangling_tool_calls()

                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd in ("kill", "docker_stop"):
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                info = user_agents[name]
                info["working"] = False
                if info.get("work_loop") and not info["work_loop"].done():
                    info["work_loop"].cancel()
                    info["work_loop"] = None

                if info["agent"].container:
                    await asyncio.to_thread(info["agent"].container.destroy)
                info["container_on"] = False

                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "delete":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                # cybersec: the name is used in rmtree paths below — allowlist it so a delete can never wipe folders outside the user's own directory
                try:
                    validate_name(name)
                except HTTPException as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": e.detail}))
                    continue

                info = user_agents[name]
                info["working"] = False
                if info.get("work_loop") and not info["work_loop"].done():
                    info["work_loop"].cancel()
                    info["work_loop"] = None

                if info["agent"].container:
                    await asyncio.to_thread(info["agent"].container.destroy)

                # remove workspace and context
                workspace = DATA_DIR / user / "workspace" / name
                context = DATA_DIR / user / "context" / name
                if workspace.exists():
                    image = info["agent"].container.image if info["agent"].container else "int3rf4ce_sandbox"
                    _rmtree_even_root_owned(workspace, image)
                if context.exists():
                    shutil.rmtree(context)

                # strip the agent from all channels; delete channels left empty of agents
                chatmod.remove_agent_everywhere(user, name)
                # free any compute targets it had claimed
                computemod.release_all(user, name)

                del user_agents[name]
                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "rename":
                old_name = msg.get("name")
                new_name = msg.get("new_name")

                if old_name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {old_name} not found"}))
                    continue
                if not new_name or new_name in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"name {new_name} invalid or taken"}))
                    continue

                # cybersec: the new name is used in folder rename paths below — allowlist it so a rename can never move folders outside the user's own directory
                try:
                    validate_name(new_name)
                except HTTPException as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": e.detail}))
                    continue

                info = user_agents[old_name]
                info["working"] = False
                if info.get("work_loop") and not info["work_loop"].done():
                    info["work_loop"].cancel()
                    info["work_loop"] = None

                if info["agent"].container:
                    await asyncio.to_thread(info["agent"].container.destroy)
                info["container_on"] = False

                # rename workspace and context folders
                old_workspace = DATA_DIR / user / "workspace" / old_name
                new_workspace = DATA_DIR / user / "workspace" / new_name
                old_context = DATA_DIR / user / "context" / old_name
                new_context = DATA_DIR / user / "context" / new_name
                if old_workspace.exists():
                    old_workspace.rename(new_workspace)
                if old_context.exists():
                    old_context.rename(new_context)

                # recreate agent with new name but same port/model
                model = _make_model(user, info.get("model", "kimi-k3"))
                agent = Agent(user, new_name, model, use_container=True, novnc_port=info["novnc_port"])
                _attach_status_handler(user, new_name, agent)

                user_agents[new_name] = {
                    "agent": agent,
                    "novnc_port": info["novnc_port"],
                    "model": info.get("model", "kimi-k3"),
                    "container_on": False,
                    "working": False,
                }
                del user_agents[old_name]
                chatmod.remove_agent_everywhere(user, old_name)
                chatmod.ensure_dm(user, new_name)
                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "chat_mode":
                name = msg.get("name")
                enabled = msg["enabled"]

                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                info = user_agents[name]
                # single turn is a MODE, not an on/off switch: it only changes how a
                # running model answers (one turn per message vs continuous work loop)
                info["agent"].chat_mode = enabled
                if enabled:
                    # settle the work loop before sanitizing, then close any
                    # dangling tool calls the interrupted turn left behind —
                    # otherwise the next single-turn reply dies on a rejected context
                    await cancel_and_settle(info, "work_loop")
                    info["agent"].context.close_dangling_tool_calls()
                else:
                    if info["working"] and not info.get("work_loop"):
                        info["work_loop"] = asyncio.create_task(work_loop(user, name, info))

                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "chat":
                name = msg.get("name")
                text = msg.get("text", "")
                attachments = msg.get("attachments") or []  # [{name, media_type, data}]

                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                info = user_agents[name]
                # agent-view text + attachments go DIRECTLY into context — no chat detour.
                # pending channel messages inject first to keep chronological order.
                inject_pending(user, name, info)

                blocks = []
                if text.strip():
                    blocks.append({"type": "text", "text": text})
                images = {"image/png", "image/jpeg", "image/gif", "image/webp"}
                for att in attachments:
                    media_type = att.get("media_type", "application/octet-stream")
                    data = att.get("data", "")
                    approx_bytes = len(data) * 3 // 4  # approximate bytes from base64
                    if approx_bytes > MAX_WS_ATTACH_BYTES:
                        await ws.send_text(json.dumps({"type": "error",
                            "msg": f"attachment too large: {att['name']} — upload it to the channel files instead"}))
                        continue
                    if media_type in images:
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": data},
                        })
                    elif Path(att.get("name", "")).suffix.lower() in TEXT_EXTS:
                        # text files inline their content so the model actually sees it
                        content = base64.b64decode(data).decode("utf-8", errors="replace")[:MAX_ATTACH_CHARS]
                        blocks.append({"type": "text", "text": f"[attached file: {att['name']}]\n{content}"})
                    else:
                        blocks.append({"type": "text", "text": f"[attached file: {att['name']} ({approx_bytes:,} bytes)]"})
                if blocks:
                    info["agent"].context.add_message("user", blocks)
                await broadcast(user, {"type": "context", "name": name, "messages": info["agent"].context.messages})

                if info["working"] and not info["agent"].chat_mode:
                    continue  # the work loop picks the text up next turn

                if info["agent"].chat_mode and info["working"]:
                    agent = info["agent"]
                    async def do_chat_turn(_name=name, _agent=agent):
                        try:
                            print(f"[chat_mode] calling turn for {_name}")
                            # chat mode = single-turn mode: the reply shows in the
                            # agent view's context stream; the DM channel only gets
                            # what the agent explicitly CHAT_SENDs
                            await _agent.turn()
                            await broadcast(user, {"type": "context", "name": _name, "messages": _agent.context.messages})
                        except Exception as e:
                            print(f"[chat_mode] ERROR: {e}")
                    info["chat_task"] = asyncio.create_task(do_chat_turn())

            elif cmd == "get_context":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                messages = user_agents[name]["agent"].context.messages
                await ws.send_text(json.dumps({"type": "context", "name": name, "messages": messages}))

            elif cmd == "list_models":
                # flat {display_name: model_id} for frontend compatibility
                flat_models = {}
                for provider_models in list_available_models().values():
                    flat_models.update(provider_models)
                await ws.send_text(json.dumps({
                    "type": "models",
                    "models": flat_models,
                    "capabilities": list_model_capabilities(),
                }))

            elif cmd == "set_model":
                name = msg.get("name")
                model_name = msg.get("model")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue
                if model_name not in _all_model_ids():
                    await ws.send_text(json.dumps({"type": "error", "msg": f"unknown model {model_name}"}))
                    continue
                user_agents[name]["model"] = model_name
                user_agents[name]["agent"].model = _make_model(user, model_name)
                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            # ---- thoughtgraph access settings (per agent) ----
            elif cmd == "get_graph_settings":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue
                path = DATA_DIR / user / "config" / "specific" / name / "graph.json"
                settings = json.loads(path.read_text()) if path.exists() else None
                await ws.send_text(json.dumps({"type": "graph_settings", "name": name, "settings": settings}))

            elif cmd == "set_graph_settings":
                name = msg.get("name")
                settings = msg.get("settings")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue
                if not isinstance(settings, dict):
                    await ws.send_text(json.dumps({"type": "error", "msg": "settings must be an object"}))
                    continue
                # entries are {"board": b, "id": nid} — validate every board exists and every id is on it
                bad = None
                for key in ("prompt_docs", "read", "write", "time", "folders"):
                    for e in settings.get(key) or []:
                        try:
                            meta = tg_storage.load_meta(user, e["board"])
                        except Exception:
                            bad = f"board not found: {e.get('board')}"
                            break
                        node = meta["nodes"].get(e.get("id"))
                        if not node:
                            bad = f"node {e.get('id')} not on board {e['board']}"
                            break
                        if key == "folders" and node["kind"] != "folder":
                            bad = f"folder total control entries must be folders: {node['title']}"
                            break
                    if bad:
                        break
                if bad:
                    await ws.send_text(json.dumps({"type": "error", "msg": bad}))
                    continue
                specific = DATA_DIR / user / "config" / "specific" / name
                specific.mkdir(parents=True, exist_ok=True)
                graph_path = specific / "graph.json"
                old_settings = json.loads(graph_path.read_text()) if graph_path.exists() else None
                # the to-do list is the agent's task queue: dragging nodes in/out
                # assigns/unassigns them BEFORE the new settings land
                reconcile_task_assignment(user, name, old_settings, settings)
                graph_path.write_text(json.dumps({
                    "prompt_docs": settings.get("prompt_docs", []),
                    "read": settings.get("read", []),
                    "write": settings.get("write", []),
                    "time": settings.get("time", []),
                    "folders": settings.get("folders", []),
                }))
                await ws.send_text(json.dumps({"type": "graph_settings", "name": name, "settings": settings}))

            elif cmd == "get_agent_tasks":
                # the chat popup's view of every agent's task queue
                tasks = {}
                for agent_name in user_agents:
                    t = agent_task_list(user, agent_name)
                    if t:
                        tasks[agent_name] = t
                await ws.send_text(json.dumps({"type": "agent_tasks", "tasks": tasks}))

            elif cmd == "list_settings_files":
                files_dir = DATA_DIR / user / "config" / "settings_files"
                files_dir.mkdir(parents=True, exist_ok=True)
                files = sorted(p.stem for p in files_dir.glob("*.json"))
                await ws.send_text(json.dumps({"type": "settings_files", "files": files}))

            elif cmd == "save_settings_file":
                name = msg.get("name")
                file_name = msg.get("file_name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue
                try:
                    validate_name(file_name)
                except HTTPException as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": e.detail}))
                    continue
                src = DATA_DIR / user / "config" / "specific" / name / "graph.json"
                if not src.exists():
                    await ws.send_text(json.dumps({"type": "error", "msg": "no settings to save"}))
                    continue
                files_dir = DATA_DIR / user / "config" / "settings_files"
                files_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, files_dir / f"{file_name}.json")
                files = sorted(p.stem for p in files_dir.glob("*.json"))
                await ws.send_text(json.dumps({"type": "settings_files", "files": files}))

            elif cmd == "load_settings_file":
                name = msg.get("name")
                file_name = msg.get("file_name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue
                try:
                    validate_name(file_name)
                except HTTPException as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": e.detail}))
                    continue
                src = DATA_DIR / user / "config" / "settings_files" / f"{file_name}.json"
                if not src.exists():
                    await ws.send_text(json.dumps({"type": "error", "msg": "settings file not found"}))
                    continue
                settings = json.loads(src.read_text())
                specific = DATA_DIR / user / "config" / "specific" / name
                specific.mkdir(parents=True, exist_ok=True)
                (specific / "graph.json").write_text(json.dumps(settings))
                await ws.send_text(json.dumps({"type": "graph_settings", "name": name, "settings": settings}))

            # ---- secrets (values never leave the host; grants are per agent) ----
            elif cmd == "list_secrets":
                # names + categories only — values never leave the host over the wire
                await ws.send_text(json.dumps({"type": "secrets", "secrets": secretsmod.items(user)}))

            elif cmd == "set_secret":
                key = msg.get("key", "")
                cat = msg.get("cat", "account")
                # llm keys are hardset: the backend resolves them by name, so only
                # registered provider secret names are valid (moonshot, deepseek, ...)
                if cat == "llm":
                    valid = {p.secret_name for p in MODEL_PROVIDERS.values() if p.secret_name}
                    if key not in valid:
                        await ws.send_text(json.dumps({"type": "error", "msg": f"llm secret must be one of: {', '.join(sorted(valid))}"}))
                        continue
                try:
                    # value is a string for most cats, a forced {"account","key"} dict for git
                    secretsmod.set_secret(user, key, msg.get("value"), cat=cat)
                except ValueError as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": str(e)}))
                    continue
                await broadcast(user, {"type": "secrets", "secrets": secretsmod.items(user)})

            elif cmd == "delete_secret":
                try:
                    secretsmod.delete_secret(user, msg.get("key", ""))
                except ValueError as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": str(e)}))
                    continue
                await broadcast(user, {"type": "secrets", "secrets": secretsmod.items(user)})

            elif cmd == "get_secret_grants":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue
                await ws.send_text(json.dumps({"type": "secret_grants", "name": name,
                                               "grants": secretsmod.load_grants(user, name)}))

            elif cmd == "set_secret_grants":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue
                grants = msg.get("grants", [])
                if not isinstance(grants, list):
                    await ws.send_text(json.dumps({"type": "error", "msg": "grants must be a list"}))
                    continue
                existing = set(secretsmod.names(user))
                bad = [g for g in grants if g not in existing]
                if bad:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"unknown secrets: {', '.join(bad)}"}))
                    continue
                secretsmod.save_grants(user, name, grants)
                await ws.send_text(json.dumps({"type": "secret_grants", "name": name, "grants": grants}))

            # ---- compute (ssh targets, usage tracking) ----
            elif cmd == "list_computes":
                await ws.send_text(json.dumps(_computes_payload(user)))

            elif cmd == "add_compute":
                name = msg.get("name", "").strip()
                ssh_command = msg.get("ssh_command", "").strip()
                password = msg.get("password", "")
                if not name or not ssh_command:
                    await ws.send_text(json.dumps({"type": "error", "msg": "name and ssh_command required"}))
                    continue
                try:
                    computemod.add_computer(user, name, ssh_command, password)
                except ValueError as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": str(e)}))
                    continue
                # the compute.py on-change hook broadcasts the fresh list to all sessions

            elif cmd == "delete_compute":
                try:
                    computemod.delete_computer(user, msg.get("name", ""))
                except ValueError as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": str(e)}))
                    continue

            elif cmd == "claim_compute":
                try:
                    computemod.claim(user, user, msg.get("name", ""))
                except ValueError as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": str(e)}))
                    continue

            elif cmd == "release_compute":
                try:
                    computemod.release(user, user, msg.get("name", ""))
                except ValueError as e:
                    await ws.send_text(json.dumps({"type": "error", "msg": str(e)}))
                    continue

            else:
                await ws.send_text(json.dumps({"type": "error", "msg": f"unknown command: {cmd}"}))

    except WebSocketDisconnect:
        clients.pop(ws, None)
    except Exception as e:
        clients.pop(ws, None)
        print(f"WebSocket error: {e}")


def _owned_vnc_port(user: str, port: str) -> int | None:
    """Return the port as int only if it belongs to one of the user's own agents, else None."""
    # cybersec: only proxy numeric ports that belong to the requesting user's own containers — otherwise anyone could reach arbitrary localhost services through this proxy
    if not port.isdigit():
        return None
    port_num = int(port)
    for info in users.get(user, {}).values():
        if info["novnc_port"] == port_num:
            return port_num
    return None


def _rmtree_even_root_owned(path: Path, image: str):
    """Remove a workspace tree; files created by root inside the container are wiped via a root container."""
    try:
        shutil.rmtree(path)
    except PermissionError:
        # container files are root-owned — a throwaway root container deletes what the host user can't
        subprocess.run(
            ["docker", "run", "--rm", "-v", f"{path.parent.absolute()}:/parent", image,
             "rm", "-rf", f"/parent/{path.name}"],
            check=True,
        )


@app.get("/vnc/{port}/{path:path}")
async def vnc_http_proxy(request: Request, port: str, path: str):
    """Proxy noVNC static assets (vnc.html, js, css) from the localhost-only container port."""
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    port_num = _owned_vnc_port(user, port) if user else None
    if port_num is None:
        raise HTTPException(status_code=403, detail="not logged in or not your container")
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
    user = user_for_token(ws.cookies.get(COOKIE_NAME))
    port_num = _owned_vnc_port(user, port) if user else None
    if port_num is None:
        # cybersec: reject before accept — this bridge gives full keyboard/mouse into the container, so it must stay behind login and per-user ownership
        await ws.close(code=1008)
        return
    # browser leg: noVNC offers no subprotocol by default — selecting one the client
    # didn't offer makes browsers abort the handshake. echo 'binary' only if offered.
    offered = ws.headers.get("sec-websocket-protocol", "")
    await ws.accept(subprotocol="binary" if "binary" in offered else None)
    # upstream leg: websockify requires the 'binary' subprotocol
    async with websockets.connect(
        f"ws://127.0.0.1:{port_num}/websockify", subprotocols=["binary"], max_size=None
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


FRONT_DIR = Path.cwd() / "fab" / "INT3RF4CE" / "front"
app.mount("/", StaticFiles(directory=FRONT_DIR, html=True), name="INT3RF4CE_front")
