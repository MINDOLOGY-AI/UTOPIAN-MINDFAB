import asyncio

from intvrface.back.context import Context
from intvrface.back.model import Model
from intvrface.back.container import Container


class Agent:
    """
    Orchestrates model + context + container.

    Turn structure:
        1. model reads marshaled context, outputs content blocks (text + tool_use)
        2. assistant message added to context
        3. each tool_use dispatched to container, paired with a tool_result
        4. auto-feedback: if any input action ran AND last tool wasn't perception,
           replace last "ok" tool_result with TERM (xterm focused) or LOOK (else)
        5. tool_results added to context as one user message
        6. check for summarization
    """

    # commands that produce their own perception output as the tool_result
    PERCEPTION_TOOLS = {"LOOK", "TERM", "READ"}
    # commands that are mouse/keyboard input (trigger auto-feedback)
    INPUT_TOOLS = {"TYPE", "KEY", "MOVE", "LCLICK", "RCLICK", "DCLICK",
                   "LDOWN", "LUP", "RDOWN", "RUP", "SCROLLUP", "SCROLLDOWN"}

    def __init__(self, name: str, model: Model, use_container: bool = True, novnc_port: int = 6080):
        # name used for context/{name}/ and workspace/{name}/
        self.name = name
        self.model = model
        self.context = Context(name)
        self.container = Container(name, novnc_port=novnc_port) if use_container else None

        # kv cache persists across turns for local models
        self._kv = self.context.load_kv()
        self.chat_mode = False

    async def turn(self, user_input: str | None = None) -> list[dict]:
        # returns assistant content blocks (text + tool_use)
        if user_input:
            self.context.add_user_text(user_input)

        # chat mode: no tools, plain text only
        use_tools = not self.chat_mode
        blocks, self._kv = await self.model.call(
            self.context.get_prompt(), self.context.marshal(), self._kv, use_tools=use_tools,
        )
        self.context.add_message("assistant", blocks)
        self.context.save_kv(self._kv)

        if self.chat_mode:
            return blocks

        # gather tool_use blocks
        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]  # [{id, name, input}]
        if not tool_uses or not self.container:
            return blocks

        # execute each tool_use, build tool_results in order
        tool_results = []  # [{type:"tool_result", tool_use_id, content}]
        had_input = False
        last_was_perception = False

        for tu in tool_uses:
            name = tu["name"].upper()
            args = tu.get("input", {}) or {}
            tid = tu["id"]
            content, perception = self._dispatch(name, args)
            tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": content})
            if name in self.INPUT_TOOLS:
                had_input = True
            last_was_perception = perception
            if name == "WAIT":
                await asyncio.sleep(int(args.get("secs", 5)))

        # auto-feedback: replace last "ok" with fresh perception
        if had_input and not last_was_perception:
            await asyncio.sleep(1)
            focused = self.container.run("xdotool getactivewindow getwindowclassname").strip()
            if focused == "XTerm":
                tool_results[-1]["content"] = self._term_text()
            else:
                tool_results[-1]["content"] = [Context.image_block(self._screenshot_bytes())]

        self.context.add_message("user", tool_results)

        # summarization
        if self.context.needs_summary():
            summary, _ = await self.model.summarize(self.context.marshal(), self._kv)
            self.context.apply_summary(summary)
            self._kv = None  # invalidate cache after context change

        return blocks

    def _dispatch(self, name: str, args: dict) -> tuple:
        # returns (tool_result_content, is_perception)
        # tool_result_content: str (action ack / text) OR list[dict] (image blocks)
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
            # keys: list[str] -> 'ctrl+shift+s' for xdotool
            keys = args.get("keys", [])
            self.container.key('+'.join(keys))
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
            self.container.write_file(args["file"], args["content"])
            return f"[WRITE {args['file']}] {len(args['content'])} chars written", False
        if name == "EDIT":
            return self._edit_file(args), False

        # unknown tool — shouldn't happen since API enforces schema, but assert loud.
        assert False, f"unknown tool: {name}"

    def _read_file(self, args: dict) -> str:
        assert self.container
        content = self.container.read_file(args["file"])
        lines = content.split('\n')
        start = int(args["start"]) - 1 if "start" in args else 0
        end = int(args["end"]) if "end" in args else len(lines)
        numbered = [f"{i + 1 + start:4d}| {line}" for i, line in enumerate(lines[start:end])]
        return f"[READ {args['file']}]\n" + '\n'.join(numbered)

    def _edit_file(self, args: dict) -> str:
        assert self.container
        file = args["file"]
        old = args["old"]
        new = args["new"]
        which = args["which"]
        content = self.container.read_file(file)
        count = content.count(old)
        if count == 0:
            return f"[EDIT {file}] text not found"
        if which == "all":
            result = content.replace(old, new)
        else:
            n = int(which)
            if n >= count:
                return f"[ERROR. EDIT {file}] occurrence {n} requested but only {count} found (0-indexed)"
            # find start index of nth (0-indexed) occurrence
            idx = -1
            for _ in range(n + 1):
                idx = content.index(old, idx + 1)
            result = content[:idx] + new + content[idx + len(old):]
        self.container.write_file(file, result)
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
