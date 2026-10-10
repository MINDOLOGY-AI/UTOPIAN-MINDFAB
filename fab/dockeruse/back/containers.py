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
from fab.dockeruse.back.config import du_dir, workspace_dir, BASE_PORT, NAME_RE
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
        _handles[(user, name)] = Container(name, workspace=workspace_dir(user, name),
                                           novnc_port=entry["novnc_port"])
    return _handles[(user, name)]


# ---- docker state (docker ps is the truth, not memory) ----

def daemon_state() -> tuple[set, dict]:
    # one docker ps for both facts: who's running, and which host port each container really bound to 6080
    result = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}} {{.State}} {{.Ports}}"],
                            capture_output=True, text=True)
    running, ports = set(), {}
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        name, _, rest = line.partition(" ")
        state, _, spec = rest.partition(" ")
        if state == "running":
            running.add(name)
        # spec looks like "127.0.0.1:6081->6080/tcp"
        for part in spec.split(", "):
            if "->6080" in part:
                ports[name] = int(part.rsplit(":", 1)[1].split("->")[0])
    return running, ports


def running_names() -> set:
    return daemon_state()[0]


def daemon_ports() -> dict:
    # name -> host port actually bound, per the live daemon — the truth when containers.json drifts
    return daemon_state()[1]


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


# containers store their agent by name — a rename has to follow, or gc_assignments
# sees a name that no longer exists and silently unassigns the computer
def rename_agent(user: str, old: str, new: str):
    containers = load(user)
    renamed = [e for e in containers.values() if e.get("agent") == old]
    for e in renamed:
        e["agent"] = new
    if renamed:
        save(user, containers)


def container_for_agent(user: str, agent_name: str) -> str | None:
    for name, entry in load(user).items():
        if entry.get("agent") == agent_name:
            return name
    return None


# ---- lifecycle ----

def _next_port() -> int:
    # ports are host-wide: scan every user's containers.json so two users never collide,
    # plus the live daemon so zombie containers from failed creates don't hand out a taken port
    used = set(daemon_ports().values())
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
    h = _handles.pop((user, name), Container(name, workspace=workspace_dir(user, name),
                                             novnc_port=entry["novnc_port"]))
    h.destroy()
    if workspace:
        ws = workspace_dir(user, name)
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
    # one agent per computer, one computer per agent — reassignment auto-resolves:
    # the agent's old container loses it, then the target takes the agent
    for c, e in containers.items():
        if e.get("agent") == agent:
            e["agent"] = None
    containers[name]["agent"] = agent
    save(user, containers)


def unassign(user: str, name: str):
    containers = load(user)
    if name not in containers:
        raise ValueError(f"no container named {name!r}")
    containers[name]["agent"] = None
    save(user, containers)


def list_containers(user: str) -> list:
    running, live = daemon_state()
    containers = load(user)
    # json port drifted from the real binding (failed creates, manual docker runs, old data) — the daemon is the truth
    changed = False
    for name, e in containers.items():
        if name in live and live[name] != e["novnc_port"]:
            e["novnc_port"] = live[name]
            changed = True
    if changed:
        save(user, containers)
    return [{"name": name, "novnc_port": e["novnc_port"], "agent": e.get("agent"),
             "running": name in running}
            for name, e in sorted(containers.items())]
