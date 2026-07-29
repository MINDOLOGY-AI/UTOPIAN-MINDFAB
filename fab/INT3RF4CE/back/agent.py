import asyncio
import json
import logging
import traceback
from pathlib import Path

from fab.TH0UGHTGR4PH.back import graph_actions
from fab.INT3RF4CE.back.context import Context
from fab.INT3RF4CE.back.model import Model
from fab.INT3RF4CE.back.container import Container
from fab.INT3RF4CE.back.config import DATA_DIR

logger = logging.getLogger(__name__)


class Agent:
    """
    Orchestrates model + context + container.

    Turn structure (internal standard blocks):
        1. model reads marshaled context, outputs internal content blocks
        2. assistant message (text + tool_use blocks) added to context
        3. each tool_use dispatched by name
        4. each tool_use produces a matching user message with a tool_result block
        5. auto-feedback: keyboard commands without TERM -> TERM; mouse commands without LOOK -> LOOK
        6. tool results added to context
        7. check for summarization
    """

    # commands that produce their own perception output as the tool_result
    PERCEPTION_TOOLS = {"LOOK", "TERM", "READ"}
    # commands that are keyboard input (trigger auto TERM if no TERM)
    KEYBOARD_TOOLS = {"TYPE", "KEY"}
    # commands that are mouse input (trigger auto LOOK if no LOOK)
    MOUSE_TOOLS = {"MOVE", "LCLICK", "RCLICK", "DCLICK",
                   "LDOWN", "LUP", "RDOWN", "RUP", "SCROLLUP", "SCROLLDOWN"}
    # graph commands (host-side, access-enforced against the agent's graph.json)
    GRAPH_TOOLS = {"CHECK_GRAPH_ACCESS", "GREAD", "GUPDATE", "GEDIT"}
    DOCKER_TOOLS = {"DOCKER_START", "DOCKER_STOP"}
    # in chat mode only docker control + graph tools are advertised — no computer use
    CHAT_MODE_TOOLS = DOCKER_TOOLS | GRAPH_TOOLS

    def __init__(self, user: str, name: str, model: Model, use_container: bool = True,
                 novnc_port: int = 6080, chat_mode: bool = True):
        self.user = user
        self.name = name
        self.model = model
        self.context = Context(user, name)
        self.container = Container(user, name, novnc_port=novnc_port) if use_container else None
        self.workspace = DATA_DIR / user / "workspace" / name

        # kv cache persists across turns for local models
        self._kv = self.context.load_kv()
        # agents default to chat mode: a docker is a tool, started on demand
        self.chat_mode = chat_mode

        # optional status callback: called with {"phase": "api_call", "state": "started"|"ended"}
        self.on_status: callable | None = None

    def _notify(self, phase: str, state: str):
        if self.on_status:
            try:
                self.on_status({"phase": phase, "state": state})
            except Exception:
                pass

    async def turn(self, user_input: str | None = None) -> list[dict]:
        # returns internal content blocks (text + tool_use)
        if user_input:
            self.context.add_user_text(user_input)

        # chat mode: only docker control is offered — the agent can ask for a computer
        allowed = self.CHAT_MODE_TOOLS if self.chat_mode else None
        self._notify("api_call", "started")
        try:
            blocks, self._kv = await self.model.call(
                self.context.get_prompt(chat_mode=self.chat_mode), self.context.marshal(), self._kv,
                use_tools=True, allowed_tools=allowed,
            )
        finally:
            self._notify("api_call", "ended")

        # hierarchy models report which provider actually answered
        used = getattr(self.model, "active_model", None)
        if used:
            self._notify("model_used", used)

        self.context.add_assistant_message(blocks)
        self.context.save_kv(self._kv)

        if not self._has_tool_use(blocks) or not self.container:
            return blocks

        # execute each tool_use, build user messages with tool_result blocks
        had_keyboard = False
        had_mouse = False
        had_perception = set()

        for b in blocks:
            if b.get("type") != "tool_use":
                continue
            name = b["name"].upper()
            args = b.get("arguments", {})
            tid = b.get("id", "")
            if self.chat_mode and name not in self.CHAT_MODE_TOOLS:
                self.context.add_tool_result(tid, name, f"[{name}] unavailable in chat mode — computer tools need DOCKER_START first")
                continue
            try:
                if name in self.DOCKER_TOOLS:
                    result_content, perception = await self._docker_control(name)
                else:
                    result_content, perception = self._dispatch(name, args)
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error("tool %s failed: %s\n%s", name, exc, tb)
                result_content = f"[ERROR executing {name}] {exc}\n{tb}"
                perception = False
            self.context.add_tool_result(tid, name, result_content)
            if name in self.KEYBOARD_TOOLS:
                had_keyboard = True
            if name in self.MOUSE_TOOLS:
                had_mouse = True
            if perception:
                had_perception.add(name)
            if name == "WAIT":
                await asyncio.sleep(int(args.get("secs", 5)))

        # auto-feedback: replace last tool result with fresh perception
        if had_keyboard and "TERM" not in had_perception:
            await asyncio.sleep(0.5)
            self._replace_last_tool_result(self._term_text())
        elif had_mouse and "LOOK" not in had_perception:
            await asyncio.sleep(0.5)
            self._replace_last_tool_result([Context.image_block(self._screenshot_bytes())])

        # summarization
        if self.context.needs_summary():
            summary, _ = await self.model.summarize(self.context.marshal(), self._kv)
            self.context.apply_summary(summary)
            self._kv = None

        return blocks

    def _has_tool_use(self, blocks: list[dict]) -> bool:
        return any(b.get("type") == "tool_use" for b in blocks)

    def _replace_last_tool_result(self, content: str | list):
        """Replace the content of the most recent tool_result block."""
        for msg in reversed(self.context.messages):
            if msg.get("role") == "user":
                for block in reversed(msg.get("content", [])):
                    if block.get("type") == "tool_result":
                        block["content"] = content
                        self.context._persist_working()
                        return

    def _dispatch(self, name: str, args: dict) -> tuple:
        # returns (tool_result_content, is_perception)
        # tool_result_content: str (action ack / text) OR list[dict] (image blocks)

        # graph commands are host-side and work without a container
        if name.startswith("G") or name == "CHECK_GRAPH_ACCESS":
            return self._graph_dispatch(name, args), True

        assert self.container

        if name == "MOVE":
            self.container.move(int(args["x"]), int(args["y"]))
            return "ok", False
        if name == "LCLICK":
            self.container.click(1)
            return "ok", False
        if name == "RCLICK":
            self.container.click(3)
            return "ok", False
        if name == "DCLICK":
            self.container.double_click()
            return "ok", False
        if name == "LDOWN":
            self.container.mousedown(1)
            return "ok", False
        if name == "LUP":
            self.container.mouseup(1)
            return "ok", False
        if name == "RDOWN":
            self.container.mousedown(3)
            return "ok", False
        if name == "RUP":
            self.container.mouseup(3)
            return "ok", False
        if name == "SCROLLUP":
            self.container.scroll("up")
            return "ok", False
        if name == "SCROLLDOWN":
            self.container.scroll("down")
            return "ok", False
        if name == "TYPE":
            self.container.type_text(args.get("text", ""))
            return "ok", False
        if name == "KEY":
            keys = args.get("keys", [])
            self.container.key("+".join(keys))
            return "ok", False

        if name == "LOOK":
            return [Context.image_block(self._screenshot_bytes())], True
        if name == "TERM":
            return self._term_text(), True

        if name == "WAIT":
            return f"waited {args.get('secs', 5)}s", False

        if name == "READ":
            return self._read_file(args), True
        if name == "WRITE":
            self._write_file(args["file"], args["content"])
            return f"[WRITE {args['file']}] {len(args['content'])} chars written", False
        if name == "EDIT":
            return self._edit_file(args), False

        # unknown tool
        assert False, f"unknown tool: {name}"

    async def _docker_control(self, name: str) -> tuple:
        """DOCKER_START/DOCKER_STOP — the agent asks for (or releases) its computer.

        A docker is a tool, not a requirement. Starting switches to work mode and
        tells the server to drive the work loop; stopping releases everything.
        """
        assert self.container
        if name == "DOCKER_START":
            if not self.container._running:
                await asyncio.to_thread(self.container.start)
                self.container._running = True
            self.chat_mode = False
            self._notify("container", "started")
            self._notify("chat_mode", "off")
            return ("[DOCKER_START] container running. you are now in work mode with computer tools: "
                    "LOOK, TERM, TYPE, KEY, mouse commands, READ/WRITE/EDIT."), True
        if not self.container._running:
            self.chat_mode = True
            self._notify("chat_mode", "on")
            return "[DOCKER_STOP] container was not running. you are in chat mode.", True
        await asyncio.to_thread(self.container.destroy)
        self.container._running = False
        self.chat_mode = True
        self._notify("container", "stopped")
        self._notify("chat_mode", "on")
        return "[DOCKER_STOP] container stopped. you are back in chat mode.", True

    def _graph_settings(self) -> dict | None:
        """Read this agent's thoughtgraph access: {board, prompt_docs, read, write} or None."""
        path = DATA_DIR / self.user / "config" / "specific" / self.name / "graph.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _graph_dispatch(self, name: str, args: dict) -> str:
        settings = self._graph_settings()
        if not settings:
            return f"[{name}] no thoughtgraph access configured — the user sets it in your context panel on the board"
        read_entries = settings.get("read", [])
        write_entries = settings.get("write", [])
        readable = read_entries + write_entries  # write access implies read access

        def entry_of(ref: str, entries: list) -> dict | None:
            # find the {board, id} entry matching an id or a unique title
            for e in entries:
                if e.get("id") == ref:
                    return e
            matches = []
            for e in entries:
                try:
                    meta = graph_actions.storage.load_meta(self.user, e["board"])
                except Exception:
                    continue
                node = meta["nodes"].get(e["id"])
                if node and node["title"] == ref:
                    matches.append(e)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ValueError(f"ambiguous title {ref!r} — use the id")
            return None

        try:
            if name == "CHECK_GRAPH_ACCESS":
                def names(entries):
                    out = []
                    for e in entries:
                        try:
                            meta = graph_actions.storage.load_meta(self.user, e["board"])
                            node = meta["nodes"].get(e["id"])
                            if node:
                                out.append({"board": e["board"], "id": e["id"],
                                            "title": node["title"], "node_type": node["node_type"],
                                            "state": node["state"]})
                        except Exception:
                            continue
                    return out
                return "[CHECK_GRAPH_ACCESS]\n" + json.dumps({
                    "read": names(readable),
                    "write": names(write_entries),
                }, indent=2)

            if name == "GREAD":
                e = entry_of(args["node"], readable)
                if not e:
                    return "[GREAD ERROR] no read access to that node — CHECK_GRAPH_ACCESS shows your access"
                return f"[GREAD]\n{json.dumps(graph_actions.read_node(self.user, e['board'], e['id']), indent=2)}"

            if name == "GUPDATE":
                e = entry_of(args["node"], write_entries)
                if not e:
                    return "[GUPDATE ERROR] no write access to that node — CHECK_GRAPH_ACCESS shows your access"
                node = graph_actions.update_node(
                    self.user, e["board"], e["id"],
                    title=args.get("title"),
                    state=args["state"] if "state" in args else ...,
                    content=args.get("content"),
                )
                return f"[GUPDATE] '{node['title']}' (id {e['id']}) updated"

            if name == "GEDIT":
                e = entry_of(args["node"], write_entries)
                if not e:
                    return "[GEDIT ERROR] no write access to that node — CHECK_GRAPH_ACCESS shows your access"
                content = graph_actions.storage.read_content(self.user, e["board"], e["id"])
                old, new, which = args["old"], args["new"], str(args.get("which", "0"))
                count = content.count(old)
                if count == 0:
                    return "[GEDIT] text not found"
                if which == "all":
                    result = content.replace(old, new)
                else:
                    n = int(which)
                    if n >= count:
                        return f"[GEDIT ERROR] occurrence {n} requested but only {count} found (0-indexed)"
                    idx = -1
                    for _ in range(n + 1):
                        idx = content.index(old, idx + 1)
                    result = content[:idx] + new + content[idx + len(old):]
                graph_actions.storage.write_content(self.user, e["board"], e["id"], result)
                return "[GEDIT] done"
        except ValueError as err:
            return f"[{name} ERROR] {err}"
        return f"[{name} ERROR] unknown graph command"

    def _workspace_path(self, file: str) -> Path:
        """Resolve a file argument inside the workspace, rejecting anything that escapes it."""
        path = (self.workspace / file).resolve()
        # cybersec: confine file tools to the agent's own workspace — without this the LLM (or a prompt injection) could read/write any file on the host, e.g. ../../.env
        if not path.is_relative_to(self.workspace.resolve()):
            raise ValueError(f"path escapes workspace: {file}")
        return path

    def _read_file(self, args: dict) -> str:
        path = self._workspace_path(args["file"])
        if not path.exists():
            return f"[READ {args['file']}] file not found"
        content = path.read_text()
        lines = content.split("\n")
        start = int(args["start"]) - 1 if "start" in args else 0
        end = int(args["end"]) if "end" in args else len(lines)
        numbered = [f"{i + 1 + start:4d}| {line}" for i, line in enumerate(lines[start:end])]
        return f"[READ {args['file']}]\n" + "\n".join(numbered)

    def _write_file(self, file: str, content: str):
        path = self._workspace_path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def _edit_file(self, args: dict) -> str:
        file = args["file"]
        old = args["old"]
        new = args["new"]
        which = args["which"]
        path = self._workspace_path(file)
        if not path.exists():
            return f"[EDIT {file}] file not found"
        content = path.read_text()
        count = content.count(old)
        if count == 0:
            return f"[EDIT {file}] text not found"
        if which == "all":
            result = content.replace(old, new)
        else:
            n = int(which)
            if n >= count:
                return f"[ERROR. EDIT {file}] occurrence {n} requested but only {count} found (0-indexed)"
            idx = -1
            for _ in range(n + 1):
                idx = content.index(old, idx + 1)
            result = content[:idx] + new + content[idx + len(old):]
        path.write_text(result)
        return f"[EDIT {file}] done"

    def _screenshot_bytes(self) -> bytes:
        assert self.container
        path = self.container.screenshot()
        with open(path, "rb") as f:
            return f.read()

    def _term_text(self) -> str:
        assert self.container
        log_path = self.container.workspace / "term.log"
        output = log_path.read_text()[-5000:] if log_path.exists() else "[no terminal output]"
        return f"[TERM]\n{output}"
