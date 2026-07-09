from typing import cast
import asyncio
import anthropic
from anthropic.types import MessageParam, ToolParam
from model import Model, KVCache
from prompt import CONTEXT_SUMMARIZATION_PROMPT

# seconds before API call is considered hung
API_TIMEOUT = 180


# all command tools as Claude API tool schemas.
# [{name, description, input_schema}, ...]
TOOLS: list[dict] = [
    # mouse
    {"name": "MOVE", "description": "Move cursor to absolute screen position (pixels).",
     "input_schema": {"type": "object", "properties": {
         "x": {"type": "integer", "description": "x in pixels (0-1280)"},
         "y": {"type": "integer", "description": "y in pixels (0-720)"},
     }, "required": ["x", "y"]}},
    {"name": "LCLICK", "description": "Left click at current cursor position.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "RCLICK", "description": "Right click at current cursor position.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "DCLICK", "description": "Double-click left mouse at current cursor position.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "LDOWN", "description": "Press and hold left mouse button.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "LUP", "description": "Release left mouse button.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "RDOWN", "description": "Press and hold right mouse button.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "RUP", "description": "Release right mouse button.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "SCROLLUP", "description": "Scroll up in the active window.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "SCROLLDOWN", "description": "Scroll down in the active window.",
     "input_schema": {"type": "object", "properties": {}}},

    # keyboard
    {"name": "TYPE", "description": "Type literal text via keyboard. No escaping needed.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "raw text to type"},
     }, "required": ["text"]}},
    {"name": "KEY", "description": "Press a key combo. Each entry is one X11 keysym (Return, BackSpace, Tab, Escape, Delete, Up, Down, Left, Right, ctrl, shift, alt, etc.). All keys are pressed together.",
     "input_schema": {"type": "object", "properties": {
         "keys": {"type": "array", "items": {"type": "string"},
                  "description": "list of X11 keysyms, e.g. ['Return'] or ['ctrl','shift','s']"},
     }, "required": ["keys"]}},

    # perception
    {"name": "LOOK", "description": "Take a screenshot and return it as the tool_result.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "TERM", "description": "Return the last 5000 chars of terminal output.",
     "input_schema": {"type": "object", "properties": {}}},

    # special
    {"name": "WAIT", "description": "Pause for N seconds. Useful when waiting for external events (page load, build).",
     "input_schema": {"type": "object", "properties": {
         "secs": {"type": "integer", "description": "seconds to sleep"},
     }, "required": ["secs"]}},

    # file (host-side, bypasses terminal)
    {"name": "READ", "description": "Read file (in container) with line numbers. Optional 1-indexed start/end.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string"},
         "start": {"type": "integer", "description": "1-indexed start line (optional)"},
         "end": {"type": "integer", "description": "1-indexed end line, inclusive (optional)"},
     }, "required": ["file"]}},
    {"name": "WRITE", "description": "Overwrite a file with content (in container). No escaping needed.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string"},
         "content": {"type": "string"},
     }, "required": ["file", "content"]}},
    {"name": "EDIT", "description": "Replace text in a file. 'which' is '0','1',... (0-indexed occurrence) or 'all'.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string"},
         "old": {"type": "string"},
         "new": {"type": "string"},
         "which": {"type": "string", "description": "'all' or 0-indexed occurrence as string"},
     }, "required": ["file", "old", "new", "which"]}},
]


class Claude(Model):
    """Claude API wrapper (async). Uses tool-use API for commands."""

    def __init__(self, model: str = "claude-opus-4-6"):
        self.model = model
        self.client = anthropic.AsyncAnthropic()

    async def call(self, prompt: str, messages: list[dict], kv_cache: KVCache,
                   use_tools: bool = True) -> tuple[list[dict], KVCache]:
        # returns full content blocks list (text + tool_use mixed), not just text.
        kwargs = {
            "model": self.model,
            "max_tokens": 16384,
            "system": [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
            "messages": cast(list[MessageParam], messages),
        }
        if use_tools:
            kwargs["tools"] = cast(list[ToolParam], TOOLS)

        response = await asyncio.wait_for(
            self.client.messages.create(**kwargs),
            timeout=API_TIMEOUT,
        )

        # convert SDK content blocks to plain dicts so they round-trip through json.
        # [{"type":"text","text":...}, {"type":"tool_use","id":...,"name":...,"input":...}, ...]
        blocks = [block.model_dump() for block in response.content]
        return blocks, None

    async def summarize(self, messages: list[dict], kv_cache: KVCache) -> tuple[str, KVCache]:
        response = await asyncio.wait_for(
            self.client.messages.create(
                model=self.model,
                max_tokens=16384,
                system=CONTEXT_SUMMARIZATION_PROMPT,
                messages=cast(list[MessageParam], messages),
            ),
            timeout=API_TIMEOUT,
        )

        text = "".join(block.text for block in response.content if block.type == "text")
        return text, None
