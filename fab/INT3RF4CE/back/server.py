"""
WebSocket server for agent management. Multi-user: every connection is bound to the
session user; agents, data folders, and broadcasts are all scoped per-user.

Commands (client -> server):
    {"cmd": "list"}
    {"cmd": "create", "name": "agent_1"}
    {"cmd": "start", "name": "agent_1"}
    {"cmd": "pause", "name": "agent_1"}
    {"cmd": "kill", "name": "agent_1"}
    {"cmd": "delete", "name": "agent_1"}
    {"cmd": "rename", "name": "agent_1", "new_name": "agent_2"}
    {"cmd": "chat", "name": "agent_1", "text": "do this task"}
    {"cmd": "chat_mode", "name": "agent_1", "enabled": true}
    {"cmd": "get_context", "name": "agent_1"}
    {"cmd": "list_models"}
    {"cmd": "set_model", "name": "agent_1", "model": "kimi-k3"}

Responses (server -> client):
    {"type": "agents", "agents": {...}}
    {"type": "context", "name": "agent_1", "messages": [...]}
    {"type": "models", "models": {...}}
    {"type": "status", "name": "agent_1", "phase": "api_call", "state": "started"}
    {"type": "error", "msg": "..."}

"""

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
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from fab.TH0UGHTGR4PH.back import storage as tg_storage
from fab.INT3RF4CE.back.agent import Agent
from fab.INT3RF4CE.back.model import Model, list_available_models, get_model_class
from fab.INT3RF4CE.back.models.kimi import Kimi  # registers the kimi provider
from fab.INT3RF4CE.back.models.glm import GLM  # registers the glm provider
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
#           "container_on": bool, "working": bool, "pending_chat": [str, ...]}}}
users: dict[str, dict[str, dict]] = {}

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


def _make_model(model_name: str) -> Model:
    provider = get_model_class(model_name)
    if provider is None:
        raise ValueError(f"unknown model {model_name}")
    return provider.make(model_name)


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
            model = _make_model(model_name)
            agent = Agent(user, name, model, use_container=True, novnc_port=novnc_port,
                          chat_mode=cfg.get("chat_mode", True))
            _attach_status_handler(user, name, agent)
            container_on = is_container_running(agent.container.name)
            if container_on:
                agent.container._running = True
            user_agents[name] = {
                "agent": agent,
                "novnc_port": novnc_port,
                "model": model_name,
                "container_on": container_on,
                "working": False,
                "pending_chat": [],
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
            if info.get("pending_chat"):
                for text in info["pending_chat"]:
                    agent.context.add_user_text(text)
                info["pending_chat"] = []
                await broadcast(user, {"type": "context", "name": name, "messages": agent.context.messages})
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

                model = _make_model(model_name)
                agent = Agent(user, name, model, use_container=True, novnc_port=novnc_port)
                _attach_status_handler(user, name, agent)

                user_agents[name] = {
                    "agent": agent,
                    "novnc_port": novnc_port,
                    "model": model_name,
                    "container_on": False,
                    "working": False,
                    "pending_chat": [],
                }

                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "start":
                name = msg.get("name")
                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                info = user_agents[name]
                # start is an explicit work-mode request: leave chat mode
                info["agent"].chat_mode = False
                if not info["container_on"]:
                    agent = info["agent"]
                    if agent.container and not agent.container._running:
                        await asyncio.to_thread(agent.container.start)
                    info["container_on"] = True

                if not info["working"]:
                    info["working"] = True
                    info["work_loop"] = asyncio.create_task(work_loop(user, name, info))
                    logger.info("[start] %s/%s work loop created", user, name)

                save_agents(user)
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
                        info["work_loop"].cancel()
                        info["work_loop"] = None
                        logger.info("[pause] %s/%s work loop cancelled", user, name)
                    agent = info["agent"]
                    for text in info.get("pending_chat", []):
                        agent.context.add_user_text(text)
                    info["pending_chat"] = []
                    await broadcast(user, {"type": "context", "name": name, "messages": agent.context.messages})

                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "kill":
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
                model = _make_model(info.get("model", "kimi-k3"))
                agent = Agent(user, new_name, model, use_container=True, novnc_port=info["novnc_port"])
                _attach_status_handler(user, new_name, agent)

                user_agents[new_name] = {
                    "agent": agent,
                    "novnc_port": info["novnc_port"],
                    "model": info.get("model", "kimi-k3"),
                    "container_on": False,
                    "working": False,
                    "pending_chat": [],
                }
                del user_agents[old_name]
                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "chat_mode":
                name = msg.get("name")
                enabled = msg["enabled"]

                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                info = user_agents[name]
                info["agent"].chat_mode = enabled
                if enabled:
                    if info["working"]:
                        info["working"] = False
                        if info.get("work_loop") and not info["work_loop"].done():
                            info["work_loop"].cancel()
                            info["work_loop"] = None
                    agent = info["agent"]
                    for text in info.get("pending_chat", []):
                        agent.context.add_user_text(text)
                    info["pending_chat"] = []
                    await broadcast(user, {"type": "context", "name": name, "messages": agent.context.messages})
                else:
                    if info.get("chat_task") and not info["chat_task"].done():
                        info["chat_task"].cancel()
                        info["chat_task"] = None
                    if info["container_on"] and not info["working"]:
                        info["working"] = True
                        info["work_loop"] = asyncio.create_task(work_loop(user, name, info))

                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

            elif cmd == "chat":
                name = msg.get("name")
                text = msg.get("text", "")

                if name not in user_agents:
                    await ws.send_text(json.dumps({"type": "error", "msg": f"agent {name} not found"}))
                    continue

                info = user_agents[name]
                # chat works containerless: agents default to chat mode, docker is on-demand

                if info["working"] and not info["agent"].chat_mode:
                    info.setdefault("pending_chat", []).append(text)
                    await broadcast(user, {"type": "context", "name": name, "messages": info["agent"].context.messages})
                    continue

                info["agent"].context.add_user_text(text)
                await broadcast(user, {"type": "context", "name": name, "messages": info["agent"].context.messages})
                if info["agent"].chat_mode:
                    agent = info["agent"]
                    async def do_chat_turn(_name=name, _agent=agent):
                        try:
                            print(f"[chat_mode] calling turn for {_name}")
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
                await ws.send_text(json.dumps({"type": "models", "models": flat_models}))

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
                user_agents[name]["agent"].model = _make_model(model_name)
                save_agents(user)
                await broadcast(user, {"type": "agents", "agents": get_agents_info(user)})

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
                for key in ("prompt_docs", "read", "write"):
                    for e in settings.get(key) or []:
                        try:
                            meta = tg_storage.load_meta(user, e["board"])
                        except Exception:
                            bad = f"board not found: {e.get('board')}"
                            break
                        if e.get("id") not in meta["nodes"]:
                            bad = f"node {e.get('id')} not on board {e['board']}"
                            break
                    if bad:
                        break
                if bad:
                    await ws.send_text(json.dumps({"type": "error", "msg": bad}))
                    continue
                specific = DATA_DIR / user / "config" / "specific" / name
                specific.mkdir(parents=True, exist_ok=True)
                (specific / "graph.json").write_text(json.dumps({
                    "prompt_docs": settings.get("prompt_docs", []),
                    "read": settings.get("read", []),
                    "write": settings.get("write", []),
                }))
                await ws.send_text(json.dumps({"type": "graph_settings", "name": name, "settings": settings}))

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
