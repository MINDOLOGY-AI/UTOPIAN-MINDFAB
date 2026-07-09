import asyncio
import json
import os
from typing import cast

import httpx

from intvrface.back.model import Model, KVCache
from intvrface.back.prompt import CONTEXT_SUMMARIZATION_PROMPT
from intvrface.back.config import OPENROUTER_BASE_URL, OPENROUTER_DEFAULT_MODEL

API_TIMEOUT = 180

# internal tool schema — same shape Claude used.
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


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _tool_result_messages(block: dict) -> list[dict]:
    """Convert an internal tool_result block into OpenAI tool / user messages."""
    content = block.get("content", "")
    tool_use_id = block.get("tool_use_id", "")

    if isinstance(content, str):
        return [{"role": "tool", "tool_call_id": tool_use_id, "content": content}]

    messages: list[dict] = []
    text_parts: list[str] = []
    images: list[dict] = []

    for sub in content:
        if sub.get("type") == "text":
            text_parts.append(sub.get("text", ""))
        elif sub.get("type") == "image":
            src = sub.get("source", {})
            if src.get("type") == "base64":
                images.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}",
                    },
                })

    tool_content = "\n".join(text_parts) if text_parts else "[image]"
    messages.append({"role": "tool", "tool_call_id": tool_use_id, "content": tool_content})

    if images:
        messages.append({"role": "user", "content": images})

    return messages


def _build_messages(system_prompt: str | None, internal_messages: list[dict]) -> list[dict]:
    """Convert internal Claude-shaped messages to OpenAI chat format."""
    messages: list[dict] = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    for msg in internal_messages:
        role = msg.get("role")
        blocks = msg.get("content", [])

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for b in blocks:
                if b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": b.get("name", ""),
                            "arguments": json.dumps(b.get("input", {})),
                        },
                    })
            assistant_msg: dict = {"role": "assistant"}
            if text_parts:
                assistant_msg["content"] = "\n".join(text_parts)
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

        elif role == "user":
            text_parts = []
            for b in blocks:
                if b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    if text_parts:
                        messages.append({"role": "user", "content": "\n".join(text_parts)})
                        text_parts = []
                    messages.extend(_tool_result_messages(b))
            if text_parts:
                messages.append({"role": "user", "content": "\n".join(text_parts)})

    return messages


class OpenRouter(Model):
    """OpenRouter API wrapper using the OpenAI-compatible chat completions endpoint."""

    def __init__(self, model: str = OPENROUTER_DEFAULT_MODEL, api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set in environment")
        self.client = httpx.AsyncClient()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/MINDOLOGY-AI/UTOPIAN-MINDFAB",
            "X-Title": "intvrface",
        }

    async def call(self, prompt: str, messages: list[dict], kv_cache: KVCache,
                   use_tools: bool = True) -> tuple[list[dict], KVCache]:
        payload = {
            "model": self.model,
            "messages": _build_messages(prompt, messages),
            "max_tokens": 16384,
        }
        if use_tools:
            payload["tools"] = _to_openai_tools(TOOLS)

        response = await asyncio.wait_for(
            self.client.post(OPENROUTER_BASE_URL, headers=self._headers(), json=payload),
            timeout=API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        msg = data["choices"][0]["message"]

        blocks: list[dict] = []
        content = msg.get("content")
        if content:
            blocks.append({"type": "text", "text": content})

        for tc in msg.get("tool_calls") or []:
            func = tc.get("function", {})
            try:
                input_args = json.loads(func.get("arguments", "{}"))
            except Exception:
                input_args = {}
            blocks.append({
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "input": input_args,
            })

        return blocks, None

    async def summarize(self, messages: list[dict], kv_cache: KVCache) -> tuple[str, KVCache]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": CONTEXT_SUMMARIZATION_PROMPT}]
                        + _build_messages(None, messages),
            "max_tokens": 16384,
        }

        response = await asyncio.wait_for(
            self.client.post(OPENROUTER_BASE_URL, headers=self._headers(), json=payload),
            timeout=API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"].get("content", "")
        return text, None
