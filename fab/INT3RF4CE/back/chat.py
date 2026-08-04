"""Multi-agent/user chat: channels, messages, files — plain json/jsonl storage.

Layout per user (fab/data/INT3RF4CE/{user}/chat/):
    channels.json            {channel_id: {name, members, dm, created}}
    readers.json             {agent_name: {channel_id: last_read_ts}}
    {channel_id}/messages.jsonl   append-only message log
    {channel_id}/files/{msgid}-{name}   file bytes

Channels are the whole ACL: an agent only sees/sends to channels it is a
member of. Every agent gets a deterministic DM channel with the user (dm-{name}).
"""

import json
import re
import secrets
import shutil
import time
from pathlib import Path

from fab.INT3RF4CE.back.config import DATA_DIR

MAX_FILE_BYTES = 500 * 1024 * 1024
# executable binary formats never travel through chat — shared files are inert
BLOCKED_EXTS = {".exe", ".dll", ".so", ".bin", ".msi", ".bat", ".com", ".scr", ".jar"}
USER_SENDER = "__user__"


def _dir(user: str) -> Path:
    d = DATA_DIR / user / "chat"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    ch = {"id": cid, "name": name, "members": members, "dm": dm, "created": time.time()}
    channels[cid] = ch
    save_channels(user, channels)
    (_dir(user) / cid / "files").mkdir(parents=True, exist_ok=True)
    return ch


def ensure_dm(user: str, agent_name: str) -> str:
    """Every agent has a deterministic DM channel with the user."""
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
    save_channels(user, channels)


def delete_channel(user: str, channel_id: str):
    channels = load_channels(user)
    if channel_id in channels:
        del channels[channel_id]
        save_channels(user, channels)
    shutil.rmtree(_dir(user) / channel_id, ignore_errors=True)


def remove_agent_everywhere(user: str, agent_name: str):
    """Agent deleted: strip it from every channel's member list.
    Channels are NEVER auto-deleted — even empty ones; the user manages them."""
    channels = load_channels(user)
    changed = False
    for ch in channels.values():
        if agent_name in ch["members"]:
            ch["members"] = [m for m in ch["members"] if m != agent_name]
            changed = True
    if changed:
        save_channels(user, channels)


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


def store_file(user: str, channel_id: str, name: str, data: bytes) -> dict:
    """Save file bytes into the channel store; returns the message file ref."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"file too large (max {MAX_FILE_BYTES // 1024 // 1024}MB)")
    if Path(name).suffix.lower() in BLOCKED_EXTS:
        raise ValueError(f"file type not allowed: {Path(name).suffix}")
    safe = re.sub(r"[^\w.\- ()\[\]]+", "_", Path(name).name).strip() or "file"
    dest = _dir(user) / channel_id / "files" / f"{secrets.token_hex(4)}-{safe}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"name": safe, "size": len(data), "path": dest.name}


def channel_file(user: str, channel_id: str, filename: str) -> Path:
    base = (_dir(user) / channel_id / "files").resolve()
    dest = (base / filename).resolve()
    if not dest.is_relative_to(base):
        raise ValueError("path escapes channel files")
    return dest


def find_channel_file(user: str, channel_id: str, filename: str) -> Path | None:
    """Find the most recent file with the given display name in a channel.
    Files are stored as {msgid}-{name}, so we match by stripping the prefix.
    Returns the full path or None."""
    base = (_dir(user) / channel_id / "files").resolve()
    if not base.is_dir():
        return None
    match = None
    match_ts = 0.0
    for p in sorted(base.iterdir()):
        if not p.is_file():
            continue
        parts = p.name.split("-", 1)
        if len(parts) == 2 and parts[1] == filename:
            st = p.stat()
            if st.st_mtime > match_ts:
                match = p
                match_ts = st.st_mtime
    return match


# ---- read cursors (next-turn injection) ----

def _load_readers(user: str) -> dict:
    return _load_json(_dir(user) / "readers.json", {})


def mark_read(user: str, agent_name: str, channel_id: str, ts: float):
    readers = _load_readers(user)
    readers.setdefault(agent_name, {})[channel_id] = ts
    _atomic_write(_dir(user) / "readers.json", readers)


def pending_messages(user: str, agent_name: str) -> dict[str, list[dict]]:
    """{channel_id: [messages the agent hasn't seen]}, across all its channels."""
    readers = _load_readers(user).get(agent_name, {})
    out = {}
    for cid, ch in load_channels(user).items():
        if agent_name not in ch["members"]:
            continue
        since = readers.get(cid, 0)
        msgs = [m for m in read_messages(user, cid, limit=100, since_ts=since)
                if m["sender"] != agent_name]
        if msgs:
            out[cid] = msgs
    return out
