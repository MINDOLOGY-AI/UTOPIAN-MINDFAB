"""Compute manager: named ssh targets the agent can claim and release.

Layout (per user):
  DATA_DIR / {user} / compute.json       — [{"name", "ssh_command", "password"}]
  DATA_DIR / {user} / compute_usage.json — {"computer_name": "agent_name"}

Agent tools: SEE_COMPUTERS (list with usage), USE_COMPUTER (claim), RELEASE_COMPUTER (release).
"""

import json
import os
import re
from pathlib import Path

from fab.INT3RF4CE.back.config import DATA_DIR

KEY_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")

# fn(user) fired after every successful mutation — server.py registers a WS broadcast here
_on_change = None


def set_on_change(fn):
    global _on_change
    _on_change = fn


def _changed(user: str):
    if _on_change:
        _on_change(user)


def _computes_path(user: str) -> Path:
    return DATA_DIR / user / "compute.json"


def _usage_path(user: str) -> Path:
    return DATA_DIR / user / "compute_usage.json"


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)
    os.chmod(path, 0o600)  # plaintext passwords — same treatment as secrets.json


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def list_computers(user: str) -> list[dict]:
    """All compute entries. Passwords included — caller is the backend web socket."""
    return _load_json(_computes_path(user), [])


def add_computer(user: str, name: str, ssh_command: str, password: str):
    if not KEY_RE.fullmatch(name):
        raise ValueError(f"invalid name: {name!r} (allowed: a-z 0-9 _ . -)")
    if not ssh_command.strip():
        raise ValueError("ssh command cannot be empty")
    computes = list_computers(user)
    if any(c["name"] == name for c in computes):
        raise ValueError(f"compute already exists: {name!r}")
    computes.append({
        "name": name,
        "ssh_command": ssh_command.strip(),
        "password": password,
    })
    _write_json(_computes_path(user), computes)
    _changed(user)


def delete_computer(user: str, name: str):
    computes = list_computers(user)
    if not any(c["name"] == name for c in computes):
        raise ValueError(f"compute not found: {name!r}")
    computes = [c for c in computes if c["name"] != name]
    _write_json(_computes_path(user), computes)
    # release if claimed
    usage = _load_json(_usage_path(user), {})
    if usage.pop(name, None) is not None:
        _write_json(_usage_path(user), usage)
    _changed(user)


def usage_map(user: str) -> dict[str, str]:
    """{computer_name: agent_name} — who has claimed what."""
    return _load_json(_usage_path(user), {})


def claim(user: str, agent_name: str, computer_name: str):
    computes = list_computers(user)
    if not any(c["name"] == computer_name for c in computes):
        raise ValueError(f"compute not found: {computer_name!r}")
    usage = usage_map(user)
    if computer_name in usage:
        raise ValueError(f"'{computer_name}' is already in use by {usage[computer_name]}")
    usage[computer_name] = agent_name
    _write_json(_usage_path(user), usage)
    _changed(user)


def release(user: str, agent_name: str, computer_name: str):
    """Release a target. The current holder or the human user (account owner) can release."""
    usage = usage_map(user)
    current = usage.get(computer_name)
    if current is None:
        return  # already released, no-op
    if current != agent_name and agent_name != user:
        raise ValueError(f"'{computer_name}' is held by {current} — you cannot release it")
    del usage[computer_name]
    _write_json(_usage_path(user), usage)
    _changed(user)


def release_all(user: str, agent_name: str) -> list[str]:
    """Free every target held by agent_name (e.g. the agent was deleted). Returns freed names."""
    usage = usage_map(user)
    freed = [name for name, holder in usage.items() if holder == agent_name]
    if not freed:
        return []
    usage = {name: holder for name, holder in usage.items() if holder != agent_name}
    _write_json(_usage_path(user), usage)
    _changed(user)
    return freed


def computers_for_agent(user: str, agent_name: str) -> list[dict]:
    """The agent's view: full details for unused + claimed-by-this-agent, redacted for claimed-by-others."""
    computes = list_computers(user)
    usage = usage_map(user)
    out = []
    for c in computes:
        entry = {"name": c["name"]}
        used_by = usage.get(c["name"])
        if used_by is None or used_by == agent_name:
            entry["ssh_command"] = c["ssh_command"]
            entry["password"] = c["password"]
        if used_by:
            entry["used_by"] = used_by
        out.append(entry)
    return out
