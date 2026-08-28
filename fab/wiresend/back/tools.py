'''wiresend tools: the WIRE_* commands, registered into corechat's central COMMANDS.
corechat must import this module for registration to happen (the plumbing line).
membership is the whole ACL; readonly members read/download but never send/upload.
file tools are plain host-side copies between the channel store and the agent's
workspace — the workspace path comes from reading dockeruse's containers.json at
FILE level (no imports — same precedent as thoughtgraph reading agents.json).'''

import json
import shutil
from pathlib import Path

from fab.config import udir
from fab.corechat.back.commands import register
from fab.wiresend.back import chat, notify


# ---- workspace resolution (the ONLY inter-module touch: one json file, read-only) ----

def _workspace_for(user: str, agent_name: str) -> Path | None:
    containers_path = udir(user) / "dockeruse" / "containers.json"
    containers = json.loads(containers_path.read_text()) if containers_path.exists() else {}
    for name, entry in containers.items():
        if entry.get("agent") == agent_name:
            return udir(user) / "dockeruse" / "workspace" / name
    return None


def _workspace_path(workspace: Path, file: str) -> Path:
    # the agent sees its workspace as /home/agent inside the container — accept
    # those absolute paths too instead of rejecting them as escapes
    if file == "/home/agent":
        file = "."
    elif file.startswith("/home/agent/"):
        file = file[len("/home/agent/"):]
    path = (workspace / file).resolve()
    # cybersec: confine to the workspace — without this a prompt injection could
    # read or wipe any file on the host, e.g. ../../.env
    if not path.is_relative_to(workspace.resolve()):
        raise ValueError(f"path escapes workspace: {file}")
    return path


_NO_DOCKER = ("[no docker assigned to you — files move through your computer's workspace; "
              "the user assigns one on the dockeruse page]")


# ---- the tools ----

async def _wire_channels(args: dict, agent) -> str:
    mine = [(cid, ch) for cid, ch in chat.load_channels(agent.user).items() if agent.name in ch["members"]]
    if not mine:
        return "[WIRE_CHANNELS] no channels — the user adds you to channels on the wiresend page"
    lines = [f"[WIRE_CHANNELS — {len(mine)} channels]"]
    for cid, ch in mine:
        unread = chat.unread_count(agent.user, agent.name, cid)
        dm_tag = " (DM with user)" if ch.get("dm") else ""
        ro_tag = " (read-only)" if agent.name in ch.get("readonly", []) else ""
        lines.append(f"  #{ch['name']} (id: {cid}) — {len(ch['members'])} members, {unread} unread{dm_tag}{ro_tag}")
    return "\n".join(lines)


async def _wire_send(args: dict, agent) -> str:
    cid = chat.resolve_channel(agent.user, args["channel"], agent.name)
    ch = chat.channel_of(agent.user, cid)
    assert ch
    text = args.get("text")
    if not text:
        raise ValueError("text required")
    if not chat.can_write(agent.user, cid, agent.name):
        return f"[WIRE_SEND] you are read-only in #{ch['name']} — reading and downloads only"
    msg = chat.append_message(agent.user, cid, agent.name, "text", text=text)
    notify.message_posted(agent.user, cid, msg)
    return f"[WIRE_SEND] sent to #{ch['name']} ({cid})"


async def _wire_read(args: dict, agent) -> str:
    cid = chat.resolve_channel(agent.user, args["channel"], agent.name)
    msgs = chat.read_messages(agent.user, cid, limit=int(args.get("limit", 20)))
    chat.mark_read(agent.user, agent.name, cid, msgs[-1]["ts"] if msgs else 0)
    ch = chat.channel_of(agent.user, cid)
    assert ch
    lines = [f"[WIRE_READ #{ch['name']} — {len(msgs)} messages]"]
    for m in msgs:
        body = m.get("text", "")
        if m["type"] == "file":
            body = f"{body} [file: {m['file']['name']} ({m['file']['size']} bytes, path: {m['file']['path']})]".strip()
        who = "user" if m["sender"] == chat.USER_SENDER else m["sender"]
        lines.append(f"  {who}: {body}")
    return "\n".join(lines)


async def _wire_upload(args: dict, agent) -> str:
    ws = _workspace_for(agent.user, agent.name)
    if ws is None:
        return _NO_DOCKER
    cid = chat.resolve_channel(agent.user, args["channel"], agent.name)
    ch = chat.channel_of(agent.user, cid)
    assert ch
    if not chat.can_write(agent.user, cid, agent.name):
        return f"[WIRE_UPLOAD] you are read-only in #{ch['name']} — downloads only"
    text = args.get("text", "")
    if not text.strip():
        raise ValueError("text required — say what you're uploading and why")
    src = _workspace_path(ws, args.get("source", ""))
    if not src.exists():
        return f"[WIRE_UPLOAD] not found in your workspace: {args.get('source', '')}"
    if src.is_dir():
        # folders copy file-by-file, preserving the workspace-relative structure
        for f in sorted(src.rglob("*")):
            if f.is_file():
                rel = str(f.relative_to(ws))
                dest = chat.channel_file(agent.user, cid, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(f), str(dest))
        ref = {"name": src.name, "size": 0, "path": args["source"]}
    else:
        ref = chat.store_file(agent.user, cid, args["source"], src.read_bytes())
    msg = chat.append_message(agent.user, cid, agent.name, "file", text=text, file=ref)
    notify.message_posted(agent.user, cid, msg)
    return f"[WIRE_UPLOAD] '{args['source']}' uploaded to #{ch['name']}"


async def _wire_download(args: dict, agent) -> str:
    ws = _workspace_for(agent.user, agent.name)
    if ws is None:
        return _NO_DOCKER
    cid = chat.resolve_channel(agent.user, args["channel"], agent.name)
    src = chat.channel_file(agent.user, cid, args["file"])
    if not src.exists():
        return f"[WIRE_DOWNLOAD] '{args['file']}' not found in that channel"
    dest = _workspace_path(ws, args.get("dest") or args["file"])
    if src.is_dir():
        shutil.copytree(str(src), str(dest), dirs_exist_ok=True)
        size_s = "(folder)"
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        size_b = dest.stat().st_size
        size_s = f"{size_b / 1048576:.1f}MB" if size_b >= 1048576 else \
                 f"{size_b / 1024:.0f}KB" if size_b >= 1024 else f"{size_b}B"
    return f"[WIRE_DOWNLOAD] {args['file']} → {args.get('dest') or args['file']} ({size_s})"


# ---- schemas ----

def _schema(name, description, properties, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []}}}


_CHANNEL = {"type": "string", "description": "channel name or id"}

register("WIRE_CHANNELS", _schema("WIRE_CHANNELS",
    "List every channel you are a member of: name, id, member count, unread count. Your DM channel with the user (dm-<your name>) is how you reach them.",
    {}), _wire_channels)

register("WIRE_SEND", _schema("WIRE_SEND",
    "Send a text message to a channel you are a member of (id or name). Use ONLY for: a final report/deliverable, or an important one-off message (blocked, question). Do NOT use it for progress commentary. To reach the user, send to your DM channel (dm-<your name>).",
    {"channel": _CHANNEL, "text": {"type": "string"}}, ["channel", "text"]), _wire_send)

register("WIRE_READ", _schema("WIRE_READ",
    "Read recent messages from a channel you are a member of (marks them read). You get a [wiresend] ping when new messages arrive — call this to read them.",
    {"channel": _CHANNEL, "limit": {"type": "integer"}}, ["channel"]), _wire_read)

register("WIRE_UPLOAD", _schema("WIRE_UPLOAD",
    "Upload a file or folder FROM your workspace TO a channel. 'source' is the workspace path; TEXT is REQUIRED — say what you're uploading and why. The path (including subdirectory structure) is preserved in the channel's files/ directory.",
    {"channel": _CHANNEL, "source": {"type": "string", "description": "path in your workspace"},
     "text": {"type": "string", "description": "what you're uploading and why"}},
    ["channel", "source", "text"]), _wire_upload)

register("WIRE_DOWNLOAD", _schema("WIRE_DOWNLOAD",
    "Download a file or folder from a channel to your workspace. 'file' is a path relative to the channel's files/ root; 'dest' is the destination path in your workspace. Copies recursively for folders.",
    {"channel": _CHANNEL, "file": {"type": "string", "description": "path in the channel's files"},
     "dest": {"type": "string", "description": "destination path in your workspace"}},
    ["channel", "file"]), _wire_download)
