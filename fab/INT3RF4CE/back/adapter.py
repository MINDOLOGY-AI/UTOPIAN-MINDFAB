"""Provider adapters: thin wrappers around each model's native API.

The canonical message format IS the OpenAI chat-completions format
===========================================================
  {"role": "system", "content": str}
  {"role": "user", "content": str | [{"type": "text", "text"}, {"type": "image_url", "image_url": {"url"}}]}
  {"role": "assistant", "content": str (optional), "tool_calls": [{"id", "type": "function", "function": {"name", "arguments": str}}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}

- user content is a plain string unless images are present (the APIs reject a
  bare dict content, so list form is only used with image_url parts).
- tool_call ids come from the API response directly.
- screenshots split into a tool message ("[image result]") plus a following
  user message with a "[screenshot]" marker text part and the image_url parts.

Adapters are responsible for:
  1. converting the shared command definitions into provider-native tool schemas.
  2. adding provider-native reasoning params.
  3. parsing provider responses into a canonical assistant message.

Messages themselves pass through nearly verbatim — a future Claude adapter
would be the first one that actually translates.
"""

from abc import ABC, abstractmethod
from typing import Any


# Shared command definitions. Each adapter wraps these in its native schema.
COMMANDS: list[dict[str, Any]] = [
    # mouse
    {"name": "MOVE", 
     "description": "Move cursor to absolute screen position (pixels).", "parameters": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}},

    {"name": "LCLICK", 
     "description": "Left click at current cursor position.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "RCLICK",
     "description": "Right click at current cursor position.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "DCLICK",
     "description": "Double-click left mouse at current cursor position.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "LDOWN",
     "description": "Press and hold left mouse button.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "LUP",
     "description": "Release left mouse button.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "RDOWN",
     "description": "Press and hold right mouse button.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "RUP",
     "description": "Release right mouse button.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "SCROLLUP",
     "description": "Scroll up in the active window.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "SCROLLDOWN",
     "description": "Scroll down in the active window.",
     "parameters": {"type": "object", "properties": {}}},

    # keyboard
    {"name": "TYPE",
     "description": "Type literal text via keyboard. No escaping needed.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},

    {"name": "KEY",
     "description": "Press a key combo. Each entry is one X11 keysym (Return, BackSpace, Tab, Escape, Delete, Up, Down, Left, Right, ctrl, shift, alt, etc.). All keys are pressed together.",
     "parameters": {"type": "object", "properties": {"keys": {"type": "array", "items": {"type": "string"}}}, "required": ["keys"]}},

    # perception
    {"name": "LOOK",
     "description": "Take a screenshot and return it as the tool_result.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "TERM",
     "description": "Return the last 5000 chars of terminal output (full log, including history).",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "TERM_LAST_COMMAND",
     "description": "Return only terminal output since your last keyboard command (TYPE/KEY). Use this to see what a command printed without getting old output mixed in.",
     "parameters": {"type": "object", "properties": {}}},

    # shell (host-side, bypasses terminal entirely — returns stdout+stderr)
    {"name": "EXEC",
     "description": "Run a shell command directly inside your docker container. Returns stdout+stderr. Use this for ALL terminal work (ls, pip install, git, python, curl, etc.) — do NOT TYPE commands into the terminal. Output is also logged to term.log so the user can see it in the VNC terminal later.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},

    # special
    {"name": "WAIT",
     "description": "Pause for N seconds. Useful when waiting for external events (page load, build).",
     "parameters": {"type": "object", "properties": {"secs": {"type": "integer"}}, "required": ["secs"]}},

    {"name": "STOP",
     "description": "Stop yourself COMPLETELY and PERMANENTLY. This halts all your work and you CANNOT resume on your own — only the user can start you again. Call this ONLY when every task is fully finished: implemented, tested, and reviewed. If anything is still open, keep working instead.",
     "parameters": {"type": "object", "properties": {}}},

    # file (host-side, bypasses terminal)
    {"name": "READ",
     "description": "Read file in workspace with line numbers. Optional 1-indexed start/end.",
     "parameters": {"type": "object", "properties": {"file": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}, "required": ["file"]}},

    {"name": "WRITE",
     "description": "Overwrite a file in workspace with content. No escaping needed.",
     "parameters": {"type": "object", "properties": {"file": {"type": "string"}, "content": {"type": "string"}}, "required": ["file", "content"]}},

    {"name": "EDIT",
     "description": "Replace text in a workspace file. 'which' is '0','1',... (0-indexed occurrence) or 'all'.",
     "parameters": {"type": "object", "properties": {"file": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}, "which": {"type": "string"}}, "required": ["file", "old", "new", "which"]}},

    # graph (host-side, thoughtgraph docs — access-enforced by the agent's context-management settings)
    {"name": "CHECK_ACCESS",
     "description": "Print your thoughtgraph access: your boards, then each granted node/folder with its level (read, write, time, total). Write implies read; to-do (time) access implies read but write does NOT imply time; folder total control covers everything inside, including time.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "GMAP",
     "description": "Your primary picture of the graph: a dry listing of every node you can see (path (type) [state], one per line) followed by every edge (path -(edge_type)-> path, one per line). Optional 'board' (default: all your boards) and 'folder' (scope to a subtree). Use this constantly to orient.",
     "parameters": {"type": "object", "properties": {"folder": {"type": "string"}, "board": {"type": "string"}}}},

    {"name": "ASCII_MAP",
     "description": "Spatial ASCII picture of a folder's layout (or the board root): boxes on a grid plus node ids and coordinates. NICHE tool — use only when you need to see or fix spatial layout before GMOVE-ing things. For understanding the graph use GMAP.",
     "parameters": {"type": "object", "properties": {"folder": {"type": "string"}, "board": {"type": "string"}}}},

    {"name": "GREAD",
     "description": "Read a thoughtgraph node you have access to (id or unique title): its fields and full content.",
     "parameters": {"type": "object", "properties": {"node": {"type": "string"}}, "required": ["node"]}},

    {"name": "GUPDATE",
     "description": "Update a node: title, node_type, expanded (true/false) need WRITE access; state ('todo'|'doing'|'done' or null to clear) needs TO-DO (time) access — write does NOT imply it. Marking 'doing' claims the task under your name; only the assignee can then complete or release it. For content edits use GEDIT.",
     "parameters": {"type": "object", "properties": {"node": {"type": "string"}, "title": {"type": "string"}, "node_type": {"type": "string"}, "state": {"type": ["string", "null"]}, "expanded": {"type": "boolean"}}, "required": ["node"]}},

    {"name": "GEDIT",
     "description": "Replace text in a node you have WRITE access to. 'which' is '0','1',... (0-indexed occurrence) or 'all'. Same semantics as the EDIT file tool.",
     "parameters": {"type": "object", "properties": {"node": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}, "which": {"type": "string"}}, "required": ["node", "old", "new", "which"]}},

    {"name": "GCREATE",
     "description": "Create a node inside a folder you have total control over. kind is 'doc'|'folder'; node_type must be a known doc type (or 'folder' for folders); parent is the folder (id or unique title).",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "kind": {"type": "string"}, "node_type": {"type": "string"}, "parent": {"type": "string"}, "state": {"type": ["string", "null"]}}, "required": ["title", "kind", "node_type", "parent"]}},

    {"name": "GMOVE",
     "description": "Move a node you have WRITE access to: new grid position (x, y) and/or new parent folder (inside your access, same board).",
     "parameters": {"type": "object", "properties": {"node": {"type": "string"}, "x": {"type": "integer"}, "y": {"type": "integer"}, "parent": {"type": "string"}}, "required": ["node"]}},

    {"name": "GLINK",
     "description": "Create a typed, colored edge between two doc nodes on the same board (never to/from folders — containment is GMOVE parent). edge_type is one of the board's edge types (support|reject|inference|training by default). Both nodes must be in your write access or total-control folders.",
     "parameters": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "edge_type": {"type": "string"}}, "required": ["source", "target", "edge_type"]}},

    # docker (host-side, controls this agent's own computer)
    {"name": "DOCKER_START",
     "description": "Start your docker computer (Linux desktop with terminal + chromium). Use when you genuinely need to run code, browse, or control a GUI. Starts the container and switches you to work mode with computer tools.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "DOCKER_STOP",
     "description": "Stop your docker computer when you no longer need it, to save resources. Returns you to chat mode.",
     "parameters": {"type": "object", "properties": {}}},

    # chat (host-side, channels with the user and other agents — membership-enforced)
    {"name": "CHAT_SEND",
     "description": "Send a text message to a chat channel you are a member of (id or name). Use ONLY for: a final report/deliverable, or an important one-off message (blocked, question). Do NOT use it for normal conversation or progress commentary — the user already sees your plain text responses. To reach the user, send to your DM channel (dm-<your name>).",
     "parameters": {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel"]}},

    {"name": "CHAT_READ",
     "description": "Read recent messages from a chat channel you are a member of (marks them read). Incoming chats also inject automatically before your turns.",
     "parameters": {"type": "object", "properties": {"channel": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["channel"]}},

    {"name": "CHECK_CHANNELS",
     "description": "List every channel you are a member of: name, id, member count, and unread message count. Your DM channel with the user has __user__ as a member — use it for CHAT_SEND to the user.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "CHAT_FILE_DOWNLOAD",
     "description": "Download a file or folder from a chat channel to your workspace. 'file' is a path relative to the channel's files/ root; 'dest' is the destination path in your workspace. Copies recursively for folders.",
     "parameters": {"type": "object", "properties": {"channel": {"type": "string"}, "file": {"type": "string"}, "dest": {"type": "string"}}, "required": ["channel", "file"]}},

    {"name": "CHAT_FILE_UPLOAD",
     "description": "Upload a file or folder FROM your workspace TO a chat channel. 'source' is the workspace path; TEXT is REQUIRED — say what you're uploading and why. The path (including subdirectory structure) is preserved in the channel's files/ directory.",
     "parameters": {"type": "object", "properties": {"channel": {"type": "string"}, "source": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel", "source", "text"]}},

    # secrets (host-side, only the subset the user granted this agent)
    {"name": "READ_SECRETS",
     "description": "Read the secrets (API keys etc.) the user granted you, as JSON name -> value pairs. The user manages the grant list in your settings; empty until they grant some.",
     "parameters": {"type": "object", "properties": {}}},

    # compute (host-side, ssh targets the user configured)
    {"name": "SEE_COMPUTERS",
     "description": "List all compute targets the user configured. Each entry: name, ssh_command, password (redacted when claimed by another agent), used_by (null if free). Use this to find a free machine, then USE_COMPUTER to claim it.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "USE_COMPUTER",
     "description": "Claim a compute target by name. You get its ssh_command + password. Only one agent can hold a target at a time — the next SEE_COMPUTERS will show it as used. RELEASE_COMPUTER when done.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},

    {"name": "RELEASE_COMPUTER",
     "description": "Release a compute target you previously claimed with USE_COMPUTER. Other agents can then claim it.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
]


class Adapter(ABC):
    """Base class for model-specific adapters. Messages are canonical OpenAI
    chat-completions format end to end; adapters only wrap tool schemas, add
    reasoning params, and parse responses."""

    @abstractmethod
    def api_tools(self, allowed: set | None = None) -> list[dict]:
        """Return provider-native tool schemas. `allowed` filters command names (None = all)."""
        raise NotImplementedError

    @abstractmethod
    def to_api_payload(self, model: str, system_prompt: str | None, messages: list[dict], use_tools: bool = True, allowed_tools: set | None = None) -> dict:
        """Build provider-native request payload from canonical messages."""
        raise NotImplementedError

    @abstractmethod
    def parse_api_response(self, data: dict) -> dict:
        """Parse provider response JSON into a canonical assistant message."""
        raise NotImplementedError

    def reasoning_params(self, model: str) -> dict:
        """Extra provider-native parameters for reasoning models. Override if needed."""
        return {}


class OpenAICompatAdapter(Adapter):
    """OpenAI-compatible chat-completions adapter — the shared wire format for
    Kimi (Moonshot), GLM (OpenRouter) and DeepSeek. Provider subclasses only
    override reasoning_params.

    The wire format IS the canonical format, so messages pass through verbatim.
    """

    def api_tools(self, allowed: set | None = None) -> list[dict]:
        cmds = COMMANDS if allowed is None else [c for c in COMMANDS if c["name"] in allowed]
        return [{"type": "function", "function": dict(cmd)} for cmd in cmds]

    def reasoning_params(self, model: str) -> dict:
        # moonshot kimi: k3 uses reasoning_effort; k2.7 uses reasoning object.
        if "k3" in model:
            return {"reasoning_effort": "max"}
        return {"reasoning": {"type": "enabled", "keep": "all"}}

    def to_api_payload(self, model: str, system_prompt: str | None, messages: list[dict], use_tools: bool = True, allowed_tools: set | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [],
            "max_tokens": 8192,
        }
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        payload["messages"].extend(messages)
        payload.update(self.reasoning_params(model))
        if use_tools:
            payload["tools"] = self.api_tools(allowed_tools)
        return payload

    def parse_api_response(self, data: dict) -> dict:
        msg = data["choices"][0]["message"]
        out: dict[str, Any] = {"role": "assistant"}

        # reasoning folds into the content string, bracketed so the frontend
        # can split it back off: [reasoning]\n...\n[/reasoning]\n<reply>
        parts = []
        reasoning = msg.get("reasoning_content")
        if reasoning:
            parts.append(f"[reasoning]\n{reasoning}\n[/reasoning]")
        content = msg.get("content")
        if content:
            parts.append(content)
        if parts:
            out["content"] = "\n".join(parts)

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # arguments stay stringified JSON — that's the canonical shape
            out["tool_calls"] = tool_calls
        return out
