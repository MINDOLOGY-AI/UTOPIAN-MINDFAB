'''containers: the containers.json store (per user), the Container handle registry, and the lifecycle.

the four verbs and their owners (DOC.md): create/destroy are human-only (the watch
page), start/pause are shared — but the agent's start is a STRICT resume (never
creates, never rebuilds). workspaces belong to containers, not agents.

ports are a HOST resource: novnc ports allocate across ALL users' containers.json.'''

import json
import shutil
import subprocess
from pathlib import Path

from fab.config import FAB_DIR, udir
from fab.dockeruse.back.config import du_dir, BASE_PORT, NAME_RE
from fab.dockeruse.back.container import Container


def containers_json(user: str) -> Path:
    return du_dir(user) / "containers.json"


# ---- store ----

# atomic write so a kill mid-write never leaves a half json
def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def load(user: str) -> dict:
    p = containers_json(user)
    return json.loads(p.read_text()) if p.exists() else {}


def save(user: str, containers: dict):
    _write_json(containers_json(user), containers)


def validate_name(name: str):
    # cybersec: the name becomes a docker container name and a folder path —
    # allowlist it before anything touches docker or disk
    if not name or not NAME_RE.fullmatch(name):
        raise ValueError(f"invalid name: {name!r} (docker rule: 2+ chars, starts with a letter or digit, then a-z 0-9 _ . -)")


# ---- handles (one Container instance per (user, name), lazy) ----

_handles: dict[tuple[str, str], Container] = {}


def handle(user: str, name: str) -> Container:
    if (user, name) not in _handles:
        entry = load(user)[name]
        _handles[(user, name)] = Container(name, workspace=du_dir(user) / "workspace" / name,
                                           novnc_port=entry["novnc_port"])
    return _handles[(user, name)]


# ---- docker state (docker ps is the truth, not memory) ----

def running_names() -> set:
    result = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                            capture_output=True, text=True)
    return set(result.stdout.split())


def is_running(name: str) -> bool:
    return name in running_names()


# ---- this user's corechat agents, read at file level (same precedent as thoughtgraph) ----

def agent_names(user: str) -> list:
    names = set()
    agents_json = udir(user) / "agents.json"
    if agents_json.exists():
        names |= set(json.loads(agents_json.read_text()))
    agents_dir = udir(user) / "agents"
    if agents_dir.exists():
        names |= {p.name for p in agents_dir.iterdir()}
    return sorted(names)


# every read of the agent list also garbage-collects assignments to dead agents
def gc_assignments(user: str):
    containers = load(user)
    names = set(agent_names(user))
    stale = [c for c, e in containers.items() if e.get("agent") and e["agent"] not in names]
    if stale:
        for c in stale:
            containers[c]["agent"] = None
        save(user, containers)


def container_for_agent(user: str, agent_name: str) -> str | None:
    for name, entry in load(user).items():
        if entry.get("agent") == agent_name:
            return name
    return None


# ---- lifecycle ----

def _next_port() -> int:
    # ports are host-wide: scan every user's containers.json so two users never collide
    used = set()
    users_dir = FAB_DIR / "users"
    if users_dir.exists():
        for u in users_dir.iterdir():
            p = u / "dockeruse" / "containers.json"
            if p.exists():
                used |= {e["novnc_port"] for e in json.loads(p.read_text()).values()}
    port = BASE_PORT
    while port in used:
        port += 1
    return port


def create(user: str, name: str) -> dict:
    """Human only. Create the entry + port, then the first boot — the container
    exists from this moment on, so the agent's strict-resume start always can."""
    validate_name(name)
    containers = load(user)
    if name in containers:
        raise ValueError(f"container {name!r} already exists")
    containers[name] = {"novnc_port": _next_port(), "agent": None}
    save(user, containers)
    try:
        handle(user, name).start()  # the first boot: start() create-or-resumes
    except Exception:
        # a failed first boot must not strand a broken entry (name squatting, dead dockerd, ...)
        _handles.pop((user, name), None)
        containers = load(user)
        del containers[name]
        save(user, containers)
        raise
    return containers[name]


def destroy(user: str, name: str, workspace: bool = False):
    """Human only. docker rm; the workspace dies only on explicit request."""
    containers = load(user)
    if name not in containers:
        raise ValueError(f"no container named {name!r}")
    entry = containers.pop(name)
    save(user, containers)
    h = _handles.pop((user, name), Container(name, workspace=du_dir(user) / "workspace" / name,
                                             novnc_port=entry["novnc_port"]))
    h.destroy()
    if workspace:
        ws = du_dir(user) / "workspace" / name
        if ws.exists():
            _rmtree_even_root_owned(ws, h.image)


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


def start(user: str, name: str):
    """Human start: create-or-resume, rebuild if the Dockerfile changed."""
    handle(user, name).start()


def agent_start(user: str, name: str):
    """The agent's DOCKER_START: a STRICT resume. never creates, never rebuilds."""
    h = handle(user, name)
    if not h.exists():
        raise ValueError("your computer doesn't exist yet — ask the user to create it")
    if h._needs_rebuild():
        raise ValueError("the computer's image changed — ask the user to start it once")
    h.start()  # the exists() guard above forces the resume branch


def stop(user: str, name: str):
    handle(user, name).stop()


def assign(user: str, name: str, agent: str):
    containers = load(user)
    if name not in containers:
        raise ValueError(f"no container named {name!r}")
    if agent not in agent_names(user):
        raise ValueError(f"no agent named {agent!r}")
    # one agent per computer, one computer per agent
    if containers[name].get("agent") and containers[name]["agent"] != agent:
        raise ValueError(f"{name!r} is assigned to {containers[name]['agent']} — unassign it first")
    holder = container_for_agent(user, agent)
    if holder and holder != name:
        raise ValueError(f"{agent!r} already has {holder!r} — unassign that first")
    containers[name]["agent"] = agent
    save(user, containers)


def unassign(user: str, name: str):
    containers = load(user)
    if name not in containers:
        raise ValueError(f"no container named {name!r}")
    containers[name]["agent"] = None
    save(user, containers)


def list_containers(user: str) -> list:
    running = running_names()
    return [{"name": name, "novnc_port": e["novnc_port"], "agent": e.get("agent"),
             "running": name in running}
            for name, e in sorted(load(user).items())]
