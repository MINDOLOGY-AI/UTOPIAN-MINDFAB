"""Multi-agent chat: channels, messages, files — plain json/jsonl storage, per user.

Layout (users/{user}/wiresend/):
    channels.json            {channel_id: {name, members, readonly, dm, created}}
    readers.json             {agent_name: {channel_id: last_read_ts}}
    {channel_id}/messages.jsonl   append-only message log
    {channel_id}/files/...        file tree (original names, browsable)

Channels are the whole ACL: an agent only sees/sends to channels it is a
member of. readonly members can read + download but not send/upload (clean
library channels). Every agent has a deterministic DM channel with the user
(dm-{name}), created lazily on first touch. pure per-user: nothing crosses users.
"""

import json
import re
import secrets
import shutil
import time
from pathlib import Path

from fab.config import udir
from fab.wiresend.back.config import MAX_FILE_BYTES

USER_SENDER = "__user__"


def _dir(user: str) -> Path:
    p = udir(user) / "wiresend"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _atomic_write(path: Path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


# ---- channels ----

def load_channels(user: str) -> dict:
    return _load_json(_dir(user) / "channels.json", {})


def save_channels(user: str, channels: dict):
    _atomic_write(_dir(user) / "channels.json", channels)


def _new_channel_id(channels: dict, base: str) -> str:
    cid = re.sub(r"[^\w-]+", "-", base.lower()).strip("-") or "channel"
    cid = cid[:48]
    if cid not in channels:
        return cid
    i = 2
    while f"{cid}-{i}" in channels:
        i += 1
    return f"{cid}-{i}"


def create_channel(user: str, name: str, members: list[str], dm: bool = False,
                   channel_id: str | None = None) -> dict:
    channels = load_channels(user)
    cid = channel_id or _new_channel_id(channels, name)
    ch = {"id": cid, "name": name, "members": members, "readonly": [], "dm": dm, "created": time.time()}
    channels[cid] = ch
    save_channels(user, channels)
    (_dir(user) / cid / "files").mkdir(parents=True, exist_ok=True)
    return ch


def ensure_dm(user: str, agent_name: str) -> str:
    """Every agent has a deterministic DM channel with the user, created on first touch."""
    cid = f"dm-{agent_name}"
    channels = load_channels(user)
    if cid not in channels:
        create_channel(user, agent_name, [USER_SENDER, agent_name], dm=True, channel_id=cid)
    return cid


def channel_of(user: str, channel_id: str) -> dict | None:
    return load_channels(user).get(channel_id)


def set_members(user: str, channel_id: str, members: list[str]):
    channels = load_channels(user)
    if channel_id not in channels:
        raise ValueError(f"channel not found: {channel_id}")
    channels[channel_id]["members"] = members
    # a removed member's readonly flag dies with the membership
    channels[channel_id]["readonly"] = [a for a in channels[channel_id].get("readonly", []) if a in members]
    save_channels(user, channels)


def set_readonly(user: str, channel_id: str, agent: str, readonly: bool):
    channels = load_channels(user)
    if channel_id not in channels:
        raise ValueError(f"channel not found: {channel_id}")
    if agent not in channels[channel_id]["members"]:
        raise ValueError(f"{agent!r} is not a member of {channel_id}")
    ro = set(channels[channel_id].get("readonly", []))
    if readonly:
        ro.add(agent)
    else:
        ro.discard(agent)
    channels[channel_id]["readonly"] = sorted(ro)
    save_channels(user, channels)


def delete_channel(user: str, channel_id: str):
    channels = load_channels(user)
    if channel_id in channels:
        del channels[channel_id]
        save_channels(user, channels)
    shutil.rmtree(_dir(user) / channel_id, ignore_errors=True)


def rename_channel(user: str, channel_id: str, name: str):
    channels = load_channels(user)
    if channel_id not in channels:
        raise ValueError(f"channel not found: {channel_id}")
    if not name.strip():
        raise ValueError("channel name cannot be empty")
    channels[channel_id]["name"] = name.strip()
    save_channels(user, channels)


def is_member(user: str, channel_id: str, name: str) -> bool:
    ch = channel_of(user, channel_id)
    return bool(ch) and name in ch["members"]


def can_write(user: str, channel_id: str, name: str) -> bool:
    """members may talk; readonly members may only read/download. the user is never readonly."""
    ch = channel_of(user, channel_id)
    if not ch or name not in ch["members"]:
        return False
    return name == USER_SENDER or name not in ch.get("readonly", [])


def resolve_channel(user: str, ref: str, agent_name: str) -> str:
    """Resolve a channel id or unique name the agent is a member of."""
    channels = load_channels(user)
    if ref in channels and agent_name in channels[ref]["members"]:
        return ref
    matches = [cid for cid, ch in channels.items()
               if ch["name"] == ref and agent_name in ch["members"]]
    if len(matches) > 1:
        raise ValueError(f"ambiguous channel name {ref!r} — use the id")
    if not matches:
        raise ValueError(f"no access to channel: {ref!r}")
    return matches[0]


# ---- messages ----

def _log_path(user: str, channel_id: str) -> Path:
    p = _dir(user) / channel_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "messages.jsonl"


def append_message(user: str, channel_id: str, sender: str, type: str,
                   text: str | None = None, file: dict | None = None) -> dict:
    msg = {"id": secrets.token_hex(4), "ts": time.time(), "sender": sender, "type": type}
    if text is not None:
        msg["text"] = text
    if file is not None:
        msg["file"] = file
    with open(_log_path(user, channel_id), "a") as f:
        f.write(json.dumps(msg) + "\n")
    return msg


def read_messages(user: str, channel_id: str, limit: int = 50, since_ts: float = 0) -> list[dict]:
    p = _log_path(user, channel_id)
    if not p.exists():
        return []
    msgs = [json.loads(line) for line in p.read_text().strip().splitlines() if line.strip()]
    msgs = [m for m in msgs if m["ts"] > since_ts]
    return msgs[-limit:]


# ---- channel file tree ----

def store_file(user: str, channel_id: str, remote_path: str, data: bytes) -> dict:
    """Save file bytes into the channel store at the given relative path. Creates parent dirs.
    Returns the message file ref. remote_path is relative to files/ (e.g. 'weights/model.pt')."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"file too large: {len(data)} bytes (max {MAX_FILE_BYTES})")
    safe = _safe_path(remote_path)
    dest = _dir(user) / channel_id / "files" / safe
    _validate_within(user, channel_id, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"name": Path(remote_path).name, "size": len(data), "path": safe}


def channel_file(user: str, channel_id: str, remote_path: str) -> Path:
    """Resolve a file path relative to the channel's files/ dir. Rejects escapes."""
    safe = _safe_path(remote_path)
    dest = (_dir(user) / channel_id / "files" / safe).resolve()
    _validate_within(user, channel_id, dest)
    return dest


def _safe_path(remote_path: str) -> str:
    """Normalize a user-provided path: strip leading slashes, resolve .. ., reject escapes."""
    cleaned = remote_path.lstrip("/").replace("\\", "/")
    parts = [p for p in cleaned.split("/") if p and p != "."]
    resolved = []
    for p in parts:
        if p == "..":
            if resolved:
                resolved.pop()
        else:
            resolved.append(p)
    return "/".join(resolved) if resolved else "file"


def _validate_within(user: str, channel_id: str, dest: Path):
    base = (_dir(user) / channel_id / "files").resolve()
    if not str(dest.resolve()).startswith(str(base)):
        raise ValueError("path escapes channel files")


def list_file_tree(user: str, channel_id: str, remote_path: str = "") -> list[dict]:
    """Recursive listing of the channel's files/ dir at remote_path. Returns [{name, path, size, is_dir}, ...]."""
    base = _dir(user) / channel_id / "files"
    scope = base / _safe_path(remote_path) if remote_path else base
    _validate_within(user, channel_id, scope)
    if not scope.exists():
        return []
    entries = []
    for p in sorted(scope.iterdir()):
        rel = str(p.relative_to(base))
        entry = {"name": p.name, "path": rel, "is_dir": p.is_dir()}
        if not p.is_dir():
            entry["size"] = p.stat().st_size
        entries.append(entry)
    return entries


def mkdir_channel(user: str, channel_id: str, remote_path: str):
    """Create a directory (and parents) inside the channel's files/ dir."""
    safe = _safe_path(remote_path)
    dest = _dir(user) / channel_id / "files" / safe
    _validate_within(user, channel_id, dest)
    dest.mkdir(parents=True, exist_ok=True)


def rename_file(user: str, channel_id: str, old_path: str, new_path: str):
    """Rename/move a file or folder within the channel."""
    src = channel_file(user, channel_id, old_path)
    if not src.exists():
        raise ValueError(f"not found: {old_path}")
    safe_new = _safe_path(new_path)
    dest = _dir(user) / channel_id / "files" / safe_new
    _validate_within(user, channel_id, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)


def delete_file(user: str, channel_id: str, remote_path: str):
    """Delete a file or folder (recursive) from the channel."""
    dest = channel_file(user, channel_id, remote_path)
    if not dest.exists():
        raise ValueError(f"not found: {remote_path}")
    if dest.is_dir():
        shutil.rmtree(dest)
    else:
        dest.unlink()


# ---- read cursors (unread counts only — notifications ride corechat's inbox) ----

def _load_readers(user: str) -> dict:
    return _load_json(_dir(user) / "readers.json", {})


def mark_read(user: str, agent_name: str, channel_id: str, ts: float):
    readers = _load_readers(user)
    readers.setdefault(agent_name, {})[channel_id] = ts
    _atomic_write(_dir(user) / "readers.json", readers)


def unread_count(user: str, agent_name: str, channel_id: str) -> int:
    since = _load_readers(user).get(agent_name, {}).get(channel_id, 0)
    return len([m for m in read_messages(user, channel_id, limit=10_000, since_ts=since)
                if m["sender"] != agent_name])
