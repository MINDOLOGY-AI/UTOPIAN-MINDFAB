import asyncio
import json
import logging
import time
import traceback
from pathlib import Path

from fab.TH0UGHTGR4PH.back import graph_actions
from fab.INT3RF4CE.back import secrets as secretsmod
from fab.INT3RF4CE.back.context import Context
from fab.INT3RF4CE.back.model import Model
from fab.INT3RF4CE.back.container import Container
from fab.INT3RF4CE.back.config import DATA_DIR

logger = logging.getLogger(__name__)

# EXEC is synchronous — a wedged command (training run, dead-mirror download)
# would park the whole turn forever without this. over the limit the command is
# NOT killed: it's demoted to a background task (id + logfile) and the agent is
# notified when it finishes. long jobs can also start backgrounded directly.
EXEC_TIMEOUT = 30


class Agent:
    """
    Orchestrates model + context + container.

    Turn structure (canonical OpenAI messages):
        1. model reads marshaled context, returns a canonical assistant message
        2. assistant message (content + tool_calls) added to context
        3. each tool_call dispatched by name
        4. each tool_call produces a matching tool message (screenshots split
           into tool message + a following "[screenshot]" user message)
        5. auto-feedback: keyboard commands without TERM -> TERM; mouse commands without LOOK -> LOOK
        6. tool results added to context
        7. check for summarization
    """

    # commands that are keyboard input (trigger auto TERM if no TERM)
    KEYBOARD_TOOLS = {"TYPE", "KEY"}
    # commands that are mouse input (trigger auto LOOK if no LOOK)
    MOUSE_TOOLS = {"MOVE", "LCLICK", "RCLICK", "DCLICK",
                   "LDOWN", "LUP", "RDOWN", "RUP", "SCROLLUP", "SCROLLDOWN"}
    # graph commands (host-side, access-enforced against the agent's graph.json)
    GRAPH_TOOLS = {"CHECK_ACCESS", "GREAD", "GWRITE", "GRENAME", "GMETA", "GEDIT", "GCREATE", "GMOVE", "GLINK", "GMAP", "ASCII_MAP", "TODO"}
    # chat commands (host-side, membership-enforced against chat/channels.json)
    CHAT_TOOLS = {"CHAT_SEND", "CHAT_READ", "CHECK_CHANNELS", "CHAT_FILE_DOWNLOAD", "CHAT_FILE_UPLOAD"}
    # secrets commands (host-side, grant-enforced against config/specific/{agent}/secrets.json)
    SECRET_TOOLS = {"READ_SECRETS"}
    # compute commands (host-side, usage-enforced against compute.json)
    COMPUTE_TOOLS = {"SEE_COMPUTERS", "USE_COMPUTER", "RELEASE_COMPUTER"}
    DOCKER_TOOLS = {"DOCKER_START", "DOCKER_STOP"}
    # STOP: the agent halts itself permanently (only the user can restart it)
    SELF_TOOLS = {"STOP"}
    # in chat mode only docker control + graph tools are advertised — no computer use
    CHAT_MODE_TOOLS = DOCKER_TOOLS | GRAPH_TOOLS | SELF_TOOLS | CHAT_TOOLS | SECRET_TOOLS | COMPUTE_TOOLS

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
        # set when the agent calls STOP: blocks self-restart until the user starts it
        self.stopped = False
        # server-side hook: called when the agent STOPs itself
        self.on_stop: callable | None = None

        # background EXEC tasks: id -> {command, log, status, exit, task, proc}
        self._bg_tasks: dict[int, dict] = {}
        self._bg_next_id = 1

        # dispatch: tool name -> bound handler(self, args) -> (content, is_perception)
        self._tool_handlers: dict[str, callable] = {
            "MOVE": self._h_move,
            "LCLICK": self._h_lclick,
            "RCLICK": self._h_rclick,
            "DCLICK": self._h_dclick,
            "LDOWN": self._h_ldown,
            "LUP": self._h_lup,
            "RDOWN": self._h_rdown,
            "RUP": self._h_rup,
            "SCROLLUP": self._h_scrollup,
            "SCROLLDOWN": self._h_scrolldown,
            "TYPE": self._h_type,
            "KEY": self._h_key,
            "LOOK": self._h_look,
            "TERM": self._h_term,
            "TERM_LAST_COMMAND": self._h_term_last_command,
            "WAIT": self._h_wait,
            "READ": self._h_read,
            "WRITE": self._h_write,
            "EDIT": self._h_edit,
        }

    def _notify(self, phase: str, state: str):
        if self.on_status:
            try:
                self.on_status({"phase": phase, "state": state})
            except Exception:
                pass

    async def turn(self, user_input: str | None = None) -> dict:
        # returns the canonical assistant message (content + tool_calls)
        notes = self._drain_finished_bg()
        if user_input or notes:
            self.context.add_user_text("\n".join(filter(None, [user_input] + notes)))

        # chat mode: only docker control is offered — the agent can ask for a computer
        allowed = self.CHAT_MODE_TOOLS if self.chat_mode else None
        self._notify("api_call", "started")
        try:
            msg, self._kv = await self.model.call(
                self.context.get_prompt(chat_mode=self.chat_mode), self.context.marshal(), self._kv,
                use_tools=True, allowed_tools=allowed,
            )
        finally:
            self._notify("api_call", "ended")

        # hierarchy models report which provider actually answered
        used = getattr(self.model, "active_model", None)
        if used:
            self._notify("model_used", used)

        self.context.add_assistant_message(msg)
        self.context.save_kv(self._kv)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls or not self.container:
            return msg

        # execute each tool_call, add a matching tool message per call
        had_keyboard = False
        had_mouse = False
        had_perception = set()

        for tc in tool_calls:
            name = tc["function"]["name"].upper()
            args = json.loads(tc["function"].get("arguments") or "{}")
            tid = tc.get("id", "")
            if self.chat_mode and name not in self.CHAT_MODE_TOOLS:
                self.context.add_tool_result(tid, name, f"[{name}] unavailable in chat mode — computer tools need DOCKER_START first")
                continue
            try:
                if name in self.DOCKER_TOOLS:
                    result_content, perception = await self._docker_control(name)
                elif name == "EXEC":
                    result_content, perception = await self._exec_tool(args)
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
        if had_keyboard and "TERM" not in had_perception and "TERM_LAST_COMMAND" not in had_perception:
            await asyncio.sleep(0.5)
            self._replace_last_tool_result(self._term_last_command())
        elif had_mouse and "LOOK" not in had_perception:
            await asyncio.sleep(0.5)
            self._replace_last_tool_result([Context.image_part(self._screenshot_bytes())])

        # summarization
        if self.context.needs_summary():
            summary, _ = await self.model.summarize(self.context.marshal(), self._kv)
            self.context.apply_summary(summary)
            self._kv = None

        return msg

    def _replace_last_tool_result(self, content: str | list):
        """Retarget the most recent tool message to fresh perception: string
        content swaps the text; image parts set "[image result]" and insert a
        "[screenshot]" user message right after the tool-message run."""
        msgs = self.context.messages
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") != "tool":
                continue
            if isinstance(content, str):
                msgs[i]["content"] = content
            else:
                msgs[i]["content"] = "[image result]"
                j = i + 1
                while j < len(msgs) and msgs[j].get("role") == "tool":
                    j += 1
                msgs.insert(j, {
                    "role": "user",
                    "content": [{"type": "text", "text": "[screenshot]"}] + content,
                    "ts": time.time(),
                })
            self.context._persist_working()
            return

    def _dispatch(self, name: str, args: dict) -> tuple:
        # returns (tool_result_content, is_perception)
        # tool_result_content: str (action ack / text) OR list[dict] (image_url parts)

        # graph commands are host-side and work without a container
        if name.startswith("G") or name.startswith("ASCII_") or name in ("CHECK_ACCESS", "TODO"):
            return self._graph_dispatch(name, args), True

        if name == "STOP":
            self.stopped = True
            if self.on_stop:
                self.on_stop()
            return ("[STOP] you are now stopped. you cannot resume on your own — "
                    "only the user can start you again. goodbye."), True

        if name in {"CHAT_SEND", "CHAT_READ", "CHAT_FILE_DOWNLOAD", "CHAT_FILE_UPLOAD", "CHECK_CHANNELS"}:
            return self._chat_dispatch(name, args), True

        if name == "READ_SECRETS":
            granted = secretsmod.granted(self.user, self.name)
            if not granted:
                return ("[READ_SECRETS] no secrets granted — the user grants secrets to you "
                        "in your settings (secrets section)"), True
            return "[READ_SECRETS]\n" + json.dumps(granted, indent=2), True

        if name in {"SEE_COMPUTERS", "USE_COMPUTER", "RELEASE_COMPUTER"}:
            return self._compute_dispatch(name, args), True

        if name == "TASKS":
            return self._tasks_list(), True

        assert self.container

        handler = self._tool_handlers.get(name)
        if handler is not None:
            return handler(args)
        assert False, f"unknown tool: {name}"

    async def _docker_control(self, name: str) -> tuple:
        """DOCKER_START/DOCKER_STOP — the agent asks for (or releases) its computer.

        A docker is a tool, not a requirement. Starting switches to work mode and
        tells the server to drive the work loop; stopping releases everything.
        """
        assert self.container
        if name == "DOCKER_START":
            if self.stopped:
                return ("[STOPPED] you stopped yourself with STOP earlier — you cannot resume on your own. "
                        "only the user can start you again."), True
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
        """Read this agent's thoughtgraph access: {prompt_docs, read, write, time, folders} or None."""
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
        time_entries = settings.get("time", [])
        folder_entries = settings.get("folders", [])
        # write implies read; to-do (time) access implies read — but write does
        # NOT imply time: flipping task states is its own grant
        readable = read_entries + write_entries + time_entries
        scope = {(e["board"], e["id"]) for e in folder_entries}

        _metas = {}

        def meta_of(board):
            if board not in _metas:
                _metas[board] = graph_actions.storage.load_meta(self.user, board)
            return _metas[board]

        def in_scope(board, nid):
            # node sits inside a total-control folder (or IS one)
            seen = set()
            cur = nid
            while cur and cur not in seen:
                seen.add(cur)
                if (board, cur) in scope:
                    return True
                node = meta_of(board)["nodes"].get(cur)
                cur = node["parent"] if node else None
            return False

        def entry_of(ref, entries):
            # find the {board, id} entry matching an id or a unique title
            for e in entries:
                if e.get("id") == ref:
                    return (e["board"], e["id"])
            matches = []
            for e in entries:
                try:
                    node = meta_of(e["board"])["nodes"].get(e["id"])
                except Exception:
                    continue
                if node and node["title"] == ref:
                    matches.append((e["board"], e["id"]))
            if len(matches) > 1:
                raise ValueError(f"ambiguous title {ref!r} — use the id")
            return matches[0] if matches else None

        def resolve(ref, write=False):
            # resolve an id or unique title to (board, id) within the agent's access
            e = entry_of(ref, write_entries)
            if e:
                return e
            if not write:
                e = entry_of(ref, readable)
                if e:
                    return e
            return resolve_in_folders(ref)

        def resolve_in_folders(ref):
            # folder total control only: any node inside a controlled folder
            matches = []
            for board in {b for b, _ in scope}:
                meta = meta_of(board)
                if ref in meta["nodes"] and in_scope(board, ref):
                    matches.append((board, ref))
                    continue
                for nid, node in meta["nodes"].items():
                    if node["title"] == ref and in_scope(board, nid):
                        matches.append((board, nid))
            matches = list(dict.fromkeys(matches))
            if len(matches) > 1:
                raise ValueError(f"ambiguous title {ref!r} — use the id")
            return matches[0] if matches else None

        def path_of(board, nid):
            # folder-joined title path, e.g. mind/mech interp/train SAE
            parts = []
            cur = nid
            meta = meta_of(board)
            while cur:
                n = meta["nodes"].get(cur)
                if not n:
                    break
                parts.append(n["title"])
                cur = n["parent"]
            return "/".join(reversed(parts))

        def visible_set(board):
            # every node the agent may see on this board: listed entries +
            # everything inside total-control folders
            meta = meta_of(board)
            listed = {(e["board"], e["id"]) for e in readable}
            return {nid for nid in meta["nodes"] if (board, nid) in listed or in_scope(board, nid)}

        try:
            if name == "CHECK_ACCESS":
                boards = sorted({e["board"] for e in readable + folder_entries})
                if not boards:
                    return "[CHECK_ACCESS] no thoughtgraph access — the user grants it in your context panel on the board"
                out = ["boards: " + ", ".join(boards)]
                for b in boards:
                    lines = []
                    for label, entries in (("read", read_entries), ("write", write_entries), ("time", time_entries)):
                        for e in entries:
                            if e["board"] == b and meta_of(b)["nodes"].get(e["id"]):
                                lines.append(f"  {label:<6} {path_of(b, e['id'])}")
                    for e in folder_entries:
                        if e["board"] == b and meta_of(b)["nodes"].get(e["id"]):
                            lines.append(f"  total  {path_of(b, e['id'])}/ (everything inside)")
                    out.append("")
                    out.append(f"{b}:")
                    out.extend(lines or ["  (nothing)"])
                return "[CHECK_ACCESS]\n" + "\n".join(out)

            if name == "GREAD":
                e = resolve(args["node"])
                if not e:
                    return "[GREAD ERROR] no read access to that node — CHECK_ACCESS shows your access"
                return f"[GREAD]\n{json.dumps(graph_actions.read_node(self.user, e[0], e[1]), indent=2)}"

            if name == "GWRITE":
                board = args.get("board")
                if not board:
                    return "[GWRITE ERROR] board required — GWRITE board node content [parent]"
                if board not in {b for b, _ in scope} | {e["board"] for e in readable}:
                    return "[GWRITE ERROR] no access to that board — CHECK_ACCESS shows your access"
                meta = meta_of(board)
                ref = args["node"]
                exists = ref in meta["nodes"] or any(n["title"] == ref for n in meta["nodes"].values())
                if exists:
                    # overwrite: the node itself must be in write access / total control
                    e = resolve(ref, write=True)
                    if not e or e[0] != board:
                        return "[GWRITE ERROR] no write access to that node — CHECK_ACCESS shows your access"
                else:
                    # create: the parent folder must be in write access / total control
                    parent_ref = args.get("parent")
                    if not parent_ref:
                        return "[GWRITE ERROR] parent required for new docs — GWRITE board node content parent"
                    pe = resolve(parent_ref, write=True)
                    if not pe or pe[0] != board:
                        return "[GWRITE ERROR] parent folder must be inside your write access on that board"
                    parent_node = meta["nodes"].get(pe[1])
                    if not parent_node or parent_node["kind"] != "folder":
                        return "[GWRITE ERROR] parent must be a folder"
                return graph_actions.write_node(
                    self.user, board, ref, args["content"],
                    parent=args.get("parent"),
                )

            if name == "GRENAME":
                e = resolve(args["node"], write=True)
                if not e:
                    return "[GRENAME ERROR] no write access to that node"
                if "title" not in args:
                    return "[GRENAME ERROR] title required"
                old = meta_of(e[0])["nodes"][e[1]]["title"]
                graph_actions.rename_node(self.user, e[0], e[1], args["title"])
                return f"[GRENAME] '{old}' → '{args['title']}'"

            if name == "GMETA":
                e = resolve(args["node"], write=True)
                if not e:
                    return "[GMETA ERROR] no write access to that node"
                if "node_type" not in args and "expanded" not in args:
                    return "[GMETA ERROR] pass node_type and/or expanded"
                node = graph_actions.update_meta(
                    self.user, e[0], e[1],
                    node_type=args.get("node_type"),
                    expanded=args.get("expanded"),
                )
                return f"[GMETA] '{node['title']}' updated"

            if name == "TODO":
                wanted_state = args.get("state")
                if wanted_state:
                    e = entry_of(args["node"], time_entries) or resolve_in_folders(args["node"])
                    if not e:
                        return "[TODO ERROR] no to-do (time) access to that node — CHECK_ACCESS shows your tasks"
                    graph_actions.flip_task_state(self.user, e[0], e[1], wanted_state, actor=self.name)
                    # fall through to re-list tasks
                settings = self._graph_settings()
                time_entries = settings.get("time", []) if settings else []
                return graph_actions.list_tasks(self.user, self.name, time_entries)

            if name == "GMAP":
                # dry listing — the primary picture of the graph
                ref = args.get("folder")
                if ref:
                    e = resolve(ref)
                    if not e:
                        return "[GMAP ERROR] no access to that folder — CHECK_ACCESS shows your access"
                    node = meta_of(e[0])["nodes"].get(e[1])
                    if not node or node["kind"] != "folder":
                        return "[GMAP ERROR] map target must be a folder"
                    return f"[GMAP]\n{graph_actions.gmap(self.user, e[0], e[1], visible=visible_set(e[0]))}"
                board = args.get("board")
                if board:
                    if board not in {b for b, _ in scope} | {e["board"] for e in readable}:
                        return "[GMAP ERROR] no access to that board — CHECK_ACCESS shows your boards"
                    return f"[GMAP]\n{graph_actions.gmap(self.user, board, visible=visible_set(board))}"
                boards = sorted({e["board"] for e in readable} | {b for b, _ in scope})
                if not boards:
                    return "[GMAP ERROR] no access — the user grants it in your context panel"
                return "[GMAP]\n" + "\n\n".join(
                    graph_actions.gmap(self.user, b, visible=visible_set(b)) for b in boards)

            if name == "ASCII_MAP":
                # spatial picture — only for placement/layout work
                ref = args.get("folder")
                if ref:
                    e = resolve(ref)
                    if not e:
                        return "[ASCII_MAP ERROR] no access to that folder — CHECK_ACCESS shows your access"
                    node = meta_of(e[0])["nodes"].get(e[1])
                    if not node or node["kind"] != "folder":
                        return "[ASCII_MAP ERROR] map target must be a folder"
                    return f"[ASCII_MAP]\n{graph_actions.ascii_map(self.user, e[0], e[1])}"
                board = args.get("board")
                if not board:
                    boards = sorted({b for b, _ in scope})
                    if not boards:
                        return "[ASCII_MAP ERROR] no folder access — the user grants it in your context panel"
                    board = boards[0]
                return f"[ASCII_MAP]\n{graph_actions.ascii_map(self.user, board)}"

            if name == "GEDIT":
                e = resolve(args["node"], write=True)
                if not e:
                    return "[GEDIT ERROR] no write access to that node — CHECK_ACCESS shows your access"
                content = graph_actions.storage.read_content(self.user, e[0], meta_of(e[0]), e[1])
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
                graph_actions.storage.write_content(self.user, e[0], meta_of(e[0]), e[1], result)
                return "[GEDIT] done"

            if name == "GCREATE":
                parent_ref = args.get("parent")
                if not parent_ref:
                    return "[GCREATE ERROR] parent folder required — folders are created inside your total-control folders"
                pe = resolve(parent_ref, write=True)
                if not pe:
                    return "[GCREATE ERROR] parent must be a folder inside your access — CHECK_ACCESS shows it"
                parent_node = meta_of(pe[0])["nodes"].get(pe[1])
                if not parent_node or parent_node["kind"] != "folder":
                    return "[GCREATE ERROR] parent must be a folder"
                # folders only — docs are created with GWRITE
                node = graph_actions.create_node(
                    self.user, pe[0], args["title"], "folder", "folder",
                    parent=pe[1], state=args.get("state"),
                )
                return f"[GCREATE] created '{node['title']}' (id {node['id']}, kind {node['kind']}) in '{parent_node['title']}'"

            if name == "GMOVE":
                e = resolve(args["node"], write=True)
                if not e:
                    return "[GMOVE ERROR] no write access to that node — CHECK_ACCESS shows your access"
                parent = ...
                if "parent" in args:
                    pe = resolve(args["parent"], write=True) if args["parent"] else None
                    if not pe or pe[0] != e[0]:
                        return "[GMOVE ERROR] new parent must be a folder inside your access on the same board"
                    parent_node = meta_of(pe[0])["nodes"].get(pe[1])
                    if not parent_node or parent_node["kind"] != "folder":
                        return "[GMOVE ERROR] parent must be a folder"
                    parent = pe[1]
                node = graph_actions.move_node(
                    self.user, e[0], e[1],
                    x=args.get("x"), y=args.get("y"), parent=parent,
                )
                return f"[GMOVE] '{node['title']}' (id {e[1]}) moved"

            if name == "GLINK":
                if not args.get("edge_type"):
                    return "[GLINK ERROR] edge_type required (support|reject|causes|training)"
                se = resolve(args["source"], write=True)
                te = resolve(args["target"], write=True)
                if not se or not te:
                    return "[GLINK ERROR] both nodes must be in your write access or total-control folders"
                if se[0] != te[0]:
                    return "[GLINK ERROR] both nodes must be on the same board"
                edge = graph_actions.link(self.user, se[0], se[1], te[1], args["edge_type"])
                return f"[GLINK] linked -[{edge['edge_type']}]-> (edge id {edge['id']})"
        except ValueError as err:
            return f"[{name} ERROR] {err}"
        return f"[{name} ERROR] unknown graph command"

    def _chat_dispatch(self, name: str, args: dict) -> str:
        """CHAT_* — membership-enforced channel messaging and file transfer."""
        from fab.INT3RF4CE.back import chat as chatmod
        import shutil
        try:
            if name == "CHAT_SEND":
                cid = chatmod.resolve_channel(self.user, args["channel"], self.name)
                text = args.get("text")
                if not text:
                    return "[CHAT_SEND ERROR] text required"
                msg = chatmod.append_message(self.user, cid, self.name, "text", text=text)
                ch = chatmod.channel_of(self.user, cid)
                return f"[CHAT_SEND] sent to #{ch['name']} ({cid})"
            if name == "CHAT_READ":
                cid = chatmod.resolve_channel(self.user, args["channel"], self.name)
                chatmod.mark_read(self.user, self.name, cid, time.time())
                msgs = chatmod.read_messages(self.user, cid, limit=int(args.get("limit", 20)))
                ch = chatmod.channel_of(self.user, cid)
                lines = [f"[CHAT_READ #{ch['name']} — {len(msgs)} messages]"]
                for m in msgs:
                    body = m.get("text", "")
                    if m["type"] == "file":
                        body = f"{body} [file: {m['file']['name']} ({m['file']['size']} bytes)]".strip()
                    lines.append(f"  {m['sender']}: {body}")
                return "\n".join(lines)
            if name == "CHECK_CHANNELS":
                channels = chatmod.load_channels(self.user)
                my = [(cid, ch) for cid, ch in channels.items() if self.name in ch["members"]]
                readers = chatmod._load_readers(self.user).get(self.name, {})
                lines = [f"[CHECK_CHANNELS — {len(my)} channels]"]
                for cid, ch in my:
                    since = readers.get(cid, 0)
                    unread = len([m for m in chatmod.read_messages(self.user, cid, limit=200, since_ts=since)
                                  if m["sender"] != self.name])
                    dm_tag = " (DM with user)" if ch.get("dm") else ""
                    lines.append(f"  #{ch['name']} (id: {cid}) — {len(ch['members'])} members, {unread} unread{dm_tag}")
                return "\n".join(lines)
            if name == "CHAT_FILE_DOWNLOAD":
                cid = chatmod.resolve_channel(self.user, args["channel"], self.name)
                src_path = args["file"]
                src = chatmod.channel_file(self.user, cid, src_path)
                if not src.exists():
                    return f"[CHAT_FILE_DOWNLOAD ERROR] '{src_path}' not found in that channel"
                dest_name = args.get("dest") or src_path
                dest = self._workspace_path(dest_name)
                if src.is_dir():
                    shutil.copytree(str(src), str(dest))
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dest))
                size_b = dest.stat().st_size if not dest.is_dir() else 0
                if size_b >= 1048576:
                    size_s = f"{size_b / 1048576:.1f}MB"
                elif size_b >= 1024:
                    size_s = f"{size_b / 1024:.0f}KB"
                else:
                    size_s = f"{size_b}B" if not dest.is_dir() else "(folder)"
                return f"[CHAT_FILE_DOWNLOAD] {src_path} → {dest_name} ({size_s})"
            if name == "CHAT_FILE_UPLOAD":
                cid = chatmod.resolve_channel(self.user, args["channel"], self.name)
                text = args.get("text", "")
                if not text.strip():
                    return "[CHAT_FILE_UPLOAD ERROR] text required — explain what you're uploading"
                source_path = args.get("source", "")
                src = self._workspace_path(source_path)
                if not src.exists():
                    return f"[CHAT_FILE_UPLOAD ERROR] not found in your workspace: {source_path}"
                # copy into channel files/ preserving the workspace path
                base = src if src.is_file() else None
                if src.is_dir():
                    for f in sorted(src.rglob("*")):
                        if f.is_file():
                            rel = str(f.relative_to(self.workspace))
                            dest_file = chatmod.channel_file(self.user, cid, rel)
                            dest_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(f), str(dest_file))
                else:
                    rel = source_path
                    dest_file = chatmod.channel_file(self.user, cid, rel)
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dest_file))
                    ref = {"name": src.name, "size": src.stat().st_size, "path": rel}
                    chatmod.append_message(self.user, cid, self.name, "file", text=text, file=ref)
                ch = chatmod.channel_of(self.user, cid)
                return f"[CHAT_FILE_UPLOAD] '{source_path}' uploaded to #{ch['name']}"
        except (ValueError, KeyError) as err:
            return f"[{name} ERROR] {err}"
        return f"[{name} ERROR] unknown chat command"

    def _compute_dispatch(self, name: str, args: dict) -> str:
        """SEE_COMPUTERS / USE_COMPUTER / RELEASE_COMPUTER — usage-enforced compute targets."""
        from fab.INT3RF4CE.back import compute as computemod
        try:
            if name == "SEE_COMPUTERS":
                entries = computemod.computers_for_agent(self.user, self.name)
                if not entries:
                    return "[SEE_COMPUTERS] no compute targets configured — the user adds them on the compute page"
                lines = [f"[SEE_COMPUTERS — {len(entries)} targets]"]
                for e in entries:
                    status = f" (used by {e['used_by']})" if e.get("used_by") else ""
                    if e.get("ssh_command"):
                        lines.append(f"  {e['name']}: ssh {e['ssh_command']}{status}")
                        if e.get("password"):
                            lines.append(f"    password: {e['password']}")
                    else:
                        lines.append(f"  {e['name']}{status} [claimed by another agent — details hidden]")
                return "\n".join(lines)
            if name == "USE_COMPUTER":
                target = args.get("name", "")
                try:
                    computemod.claim(self.user, self.name, target)
                except ValueError as e:
                    return f"[USE_COMPUTER ERROR] {e}"
                computes = computemod.list_computers(self.user)
                entry = next((c for c in computes if c["name"] == target), None)
                if entry:
                    return f"[USE_COMPUTER] claimed '{target}' — ssh {entry['ssh_command']} password: {entry['password']}"
                return f"[USE_COMPUTER] claimed '{target}'"
            if name == "RELEASE_COMPUTER":
                target = args.get("name", "")
                try:
                    computemod.release(self.user, self.name, target)
                except ValueError as e:
                    return f"[RELEASE_COMPUTER ERROR] {e}"
                return f"[RELEASE_COMPUTER] released '{target}'"
        except Exception as e:
            return f"[{name} ERROR] {e}"
        return f"[{name} ERROR] unknown compute command"

    def _workspace_path(self, file: str) -> Path:
        """Resolve a file argument inside the workspace, rejecting anything that escapes it."""
        # the agent sees its workspace as /home/agent inside the container — accept
        # those absolute paths too instead of rejecting them as escapes
        if file == "/home/agent":
            file = "."
        elif file.startswith("/home/agent/"):
            file = file[len("/home/agent/"):]
        path = (self.workspace / file).resolve()
        # cybersec: confine file tools to the agent's own workspace — without this the LLM (or a prompt injection) could read/write any file on the host, e.g. ../../.env
        if not path.is_relative_to(self.workspace.resolve()):
            raise ValueError(f"path escapes workspace: {file}")
        return path

    def _container_rel(self, path: Path) -> str:
        # workspace host path -> the same file's path inside the container
        return f"/home/agent/{path.relative_to(self.workspace.resolve())}"

    def _container_file(self, file: str) -> str:
        """Validate a workspace file arg and return its in-container path.

        ALL file ops go through the container (docker exec as root): the
        container is the single writer, so ownership is uniform and host-side
        permission mismatches can't happen. File tools aren't advertised in
        chat mode, so requiring a running container here is consistent."""
        if not self.container or not self.container._running:
            raise ValueError("container not running — DOCKER_START first")
        return self._container_rel(self._workspace_path(file))

    def _read_file(self, args: dict) -> str:
        cpath = self._container_file(args["file"])
        if self.container.run(f"test -e '{cpath}' && echo y").strip() != "y":
            return f"[READ {args['file']}] file not found"
        content = self.container.read_file(cpath)
        lines = content.split("\n")
        start = int(args["start"]) - 1 if "start" in args else 0
        end = int(args["end"]) if "end" in args else len(lines)
        numbered = [f"{i + 1 + start:4d}| {line}" for i, line in enumerate(lines[start:end])]
        return f"[READ {args['file']}]\n" + "\n".join(numbered)

    def _write_file(self, file: str, content: str):
        self.container.write_file(self._container_file(file), content)

    def _edit_file(self, args: dict) -> str:
        file = args["file"]
        old = args["old"]
        new = args["new"]
        which = args["which"]
        cpath = self._container_file(file)
        if self.container.run(f"test -e '{cpath}' && echo y").strip() != "y":
            return f"[EDIT {file}] file not found"
        content = self.container.read_file(cpath)
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
        self.container.write_file(cpath, result)
        return f"[EDIT {file}] done"

    # ---- tool-dispatch handlers (called via self._tool_handlers dict) ----

    def _h_move(self, args):
        self.container.move(int(args["x"]), int(args["y"]))
        return "ok", False

    def _h_lclick(self, _):
        self.container.click(1)
        return "ok", False

    def _h_rclick(self, _):
        self.container.click(3)
        return "ok", False

    def _h_dclick(self, _):
        self.container.double_click()
        return "ok", False

    def _h_ldown(self, _):
        self.container.mousedown(1)
        return "ok", False

    def _h_lup(self, _):
        self.container.mouseup(1)
        return "ok", False

    def _h_rdown(self, _):
        self.container.mousedown(3)
        return "ok", False

    def _h_rup(self, _):
        self.container.mouseup(3)
        return "ok", False

    def _h_scrollup(self, _):
        self.container.scroll("up")
        return "ok", False

    def _h_scrolldown(self, _):
        self.container.scroll("down")
        return "ok", False

    def _h_type(self, args):
        self.container.type_text(args.get("text", ""))
        return "ok", False

    def _h_key(self, args):
        keys = args.get("keys", [])
        self.container.key("+".join(keys))
        return "ok", False

    def _h_look(self, _):
        return [Context.image_part(self._screenshot_bytes())], True

    def _h_term(self, _):
        return self._term_text(), True

    def _h_term_last_command(self, _):
        return self._term_last_command(), True

    def _h_wait(self, args):
        return f"waited {args.get('secs', 5)}s", False

    def _h_read(self, args):
        return self._read_file(args), True

    def _h_write(self, args):
        self._write_file(args["file"], args["content"])
        return f"[WRITE {args['file']}] {len(args['content'])} chars written", False

    def _h_edit(self, args):
        return self._edit_file(args), False

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

    def _term_last_command(self) -> str:
        assert self.container
        log_path = self.container.workspace / "term.log"
        if not log_path.exists():
            return "[TERM_LAST_COMMAND]\n[no terminal output]"
        offset = self.container._term_offset
        with open(log_path, "rb") as f:
            f.seek(offset)
            new_bytes = f.read()
        self.container._term_offset = log_path.stat().st_size
        if not new_bytes:
            return "[TERM_LAST_COMMAND]\n(no new output since last keyboard command)"
        text = new_bytes.decode("utf-8", errors="replace")[-5000:]
        return f"[TERM_LAST_COMMAND]\n{text}"

    # ---- background EXEC (kimi-code-style task registry) ----

    async def _exec_bg_spawn(self, command: str) -> int:
        """Spawn a docker exec as an asyncio task; stream output to workspace/exec_logs/{id}.log."""
        tid = self._bg_next_id
        self._bg_next_id += 1
        log_rel = f"exec_logs/{tid}.log"
        log_host = self.workspace / log_rel
        log_host.parent.mkdir(parents=True, exist_ok=True)
        entry: dict = {"command": command, "log": log_rel, "status": "running", "exit": None}
        self._bg_tasks[tid] = entry

        async def runner():
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", self.container.name, "bash", "-c", command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            entry["proc"] = proc
            with open(log_host, "wb") as f:
                f.write(f"$ {command}\n".encode())
                while True:
                    chunk = await proc.stdout.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    f.flush()
                f.write(f"\n[exit {await proc.wait()}]\n")
            entry["exit"] = proc.returncode
            entry["status"] = "done"
            # user visibility: note the finish in the VNC terminal log too
            await asyncio.to_thread(
                self.container.append_file, "/home/agent/term.log",
                f"\n$ {command}\n[background exec {tid} finished, exit {proc.returncode}] log: /home/agent/{log_rel}")

        entry["task"] = asyncio.create_task(runner())
        return tid

    def _bg_log_tail(self, entry: dict, chars: int = 1500) -> str:
        log_host = self.workspace / entry["log"]
        if not log_host.exists():
            return ""
        return log_host.read_text(errors="replace")[-chars:]

    def _drain_finished_bg(self) -> list[str]:
        """Completion notes for background EXECs that finished since the last turn —
        injected as a user message so the agent never has to poll 'just in case'."""
        notes = []
        for tid, e in self._bg_tasks.items():
            if e["status"] == "done" and not e.get("notified"):
                e["notified"] = True
                notes.append(f"[EXEC BG {tid} finished, exit {e['exit']}] log: /home/agent/{e['log']}\n"
                             f"last output:\n{self._bg_log_tail(e)}")
        return notes

    def _tasks_list(self) -> str:
        if not self._bg_tasks:
            return "[TASKS] no background tasks"
        lines = ["[TASKS]"]
        for tid, e in self._bg_tasks.items():
            lines.append(f"  {tid}: {e['status']} (exit {e['exit']}) log /home/agent/{e['log']} — {e['command'][:80]}")
        return "\n".join(lines)

    async def _exec_tool(self, args: dict) -> tuple:
        """EXEC tool entry (async). background=true: spawn and return immediately.
        foreground: wait up to EXEC_TIMEOUT; over the limit the command keeps
        running as a background task instead of being killed."""
        assert self.container
        command = args["command"]
        if args.get("background"):
            tid = await self._exec_bg_spawn(command)
            return (f"[EXEC BG started: id {tid}] log: /home/agent/exec_logs/{tid}.log — "
                    f"you'll be notified when it finishes; peek with EXEC tail /home/agent/exec_logs/{tid}.log"), True

        tid = await self._exec_bg_spawn(command)
        entry = self._bg_tasks[tid]
        done, _ = await asyncio.wait({entry["task"]}, timeout=EXEC_TIMEOUT)
        if not done:
            # demote to background — asyncio.wait does not cancel the runner
            note = (f"[EXEC $ {command}]\nstill running after {EXEC_TIMEOUT}s — moved to background id {tid}. "
                    f"you'll be notified when it finishes; peek with EXEC tail /home/agent/{entry['log']}\n"
                    f"output so far:\n{self._bg_log_tail(entry)}")
            await asyncio.to_thread(self.container.append_file, "/home/agent/term.log",
                                    f"\n$ {command}\n[moved to background exec {tid}]")
            return note, True

        # foreground completion: return the output (minus the log's "$ cmd" header)
        raw = self._bg_log_tail(entry, chars=10_000_000)
        output = raw.split("\n", 1)[1] if "\n" in raw else raw
        await asyncio.to_thread(self.container.append_file, "/home/agent/term.log",
                                f"\n$ {command}\n{output}")
        entry["notified"] = True  # foreground: the tool result IS the notification
        trimmed = output[-5000:] if len(output) > 5000 else output
        return f"[EXEC $ {command}]\n{trimmed}", True
