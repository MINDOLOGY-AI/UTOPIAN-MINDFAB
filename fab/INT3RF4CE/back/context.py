import json
import base64
import time
import torch
from pathlib import Path

from fab.INT3RF4CE.back.prompt import WORK_MSG, build_system_prompt
from fab.INT3RF4CE.back.config import DATA_DIR

# outer tuple: one entry per layer (... means repeat N layers)
# inner tuple: (key_tensor, value_tensor) for that layer
# each tensor shape: (batch, heads, seq_len, head_dim)
# None for API models that don't expose kv cache
KVCache = tuple[tuple[torch.Tensor, torch.Tensor], ...] | None


MAX_WORDS = 30000
PRESERVE_LAST = 5


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _image_block(image_bytes: bytes) -> dict:
    # original: 0-255 (8 bit) -> base64: 6 bit ASCII -> utf8 string
    img_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": img_data},
    }


def _is_internal_block(block: dict) -> bool:
    return block.get("type") in {"text", "tool_use", "tool_result", "image"}


def _convert_legacy_block(block: dict) -> dict | None:
    """Convert legacy block shapes to the current internal standard."""
    t = block.get("type")
    if t == "text":
        return dict(block)
    if t == "tool_use":
        return {
            "type": "tool_use",
            "id": block.get("id", ""),
            "tool": block.get("tool", "computer_use"),
            "name": block.get("name", ""),
            "arguments": block.get("arguments", {}),
        }
    if t == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": block.get("tool_use_id", block.get("id", "")),
            "name": block.get("name", ""),
            "content": block.get("content", ""),
        }
    if t == "image":
        return dict(block)
    if t == "image_url":
        # legacy OpenAI image_url block -> internal image block
        url = block.get("image_url", {}).get("url", "")
        media_type = "image/png"
        data = ""
        if url.startswith("data:"):
            header, _, b64 = url.partition(";base64,")
            if header.startswith("data:"):
                media_type = header[5:]
            data = b64
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    return None


class Context:
    """Manages agent conversation memory using the internal standard block format.

    Internal message roles: system, user, assistant.
    Blocks:
      text       -> {"type": "text", "text": str}
      tool_use   -> {"type": "tool_use", "id", "tool", "name", "arguments"}
      tool_result-> {"type": "tool_result", "tool_use_id", "name", "content"}
      image      -> {"type": "image", "source": {...}}

    Adapters convert this format to/from each provider's native API shape.

    Files in context/{name}/:
        original.jsonl   - full log, append-only archive
        working.jsonl    - current working memory (loaded on startup)
        kv_cache.pt      - cached key/values for local models
    """

    def __init__(self, user: str, name: str):
        self.user = user
        self.name = name
        self.folder = DATA_DIR / user / "context" / name
        self.folder.mkdir(parents=True, exist_ok=True)

        self.original_path = self.folder / "original.jsonl"
        self.working_path = self.folder / "working.jsonl"
        self.kv_path = self.folder / "kv_cache.pt"

        self.original_path.touch(exist_ok=True)
        self.working_path.touch(exist_ok=True)

        raw_messages = [
            json.loads(line)
            for line in self.working_path.read_text().strip().splitlines()
            if line.strip()
        ]
        self.messages = self._migrate_messages(raw_messages)
        if raw_messages != self.messages:
            self._persist_working()

        # upload blocks (images/text) injected into the NEXT marshal only — the
        # bytes never persist into context, so uploads don't bloat future turns
        self.pending_attachments: list[dict] = []

    def _migrate_messages(self, messages: list[dict]) -> list[dict]:
        """Migrate older storage formats to the current internal standard."""
        migrated = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            # already internal standard: content is a list of recognized blocks
            if isinstance(content, list) and all(_is_internal_block(b) for b in content):
                migrated.append(msg)
                continue

            if role == "tool":
                # legacy tool role -> user message with tool_result block
                converted_content = content
                if isinstance(content, list):
                    converted_content = []
                    for b in content:
                        converted = _convert_legacy_block(b)
                        if converted:
                            converted_content.append(converted)
                migrated.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "name": msg.get("name", ""),
                        "content": converted_content,
                    }],
                })
                continue

            if role == "user":
                if isinstance(content, list):
                    blocks = [_convert_legacy_block(b) for b in content]
                    blocks = [b for b in blocks if b is not None]
                    migrated.append({"role": "user", "content": blocks})
                else:
                    migrated.append({"role": "user", "content": [_text_block(str(content))]})
                continue

            if role == "assistant":
                blocks: list[dict] = []
                if isinstance(content, list):
                    for b in content:
                        converted = _convert_legacy_block(b)
                        if converted:
                            blocks.append(converted)
                elif content:
                    blocks.append(_text_block(str(content)))

                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    args = func.get("arguments", "{}")
                    try:
                        args_dict = json.loads(args) if isinstance(args, str) else dict(args)
                    except Exception:
                        args_dict = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "tool": "computer_use",
                        "name": func.get("name", ""),
                        "arguments": args_dict,
                    })
                migrated.append({"role": "assistant", "content": blocks})
                continue

            # system role or unknown
            if isinstance(content, list):
                converted = [_convert_legacy_block(b) for b in content]
                converted = [b for b in converted if b is not None]
                migrated.append({"role": role, "content": converted})
            else:
                migrated.append(msg)

        return migrated

    def get_prompt(self, chat_mode: bool = False) -> str:
        # SYSTEM PROMPT: global prompt + graph context (+ chat mode)
        return build_system_prompt(self.user, self.name, chat_mode=chat_mode)

    def marshal(self) -> list[dict]:
        """Return internal-standard messages for the active adapter.

        Injects a WORK_MSG user text block when the last message is an assistant
        message with no tool_use blocks, so the API has a user message to respond to.
        This injection is API-only and is not persisted to context.
        """
        self.repair()

        if not self.messages and not self.pending_attachments:
            return []
        out = [dict(m) for m in self.messages]
        if self.pending_attachments:
            out.append({"role": "user", "content": self.pending_attachments})
            self.pending_attachments = []
        if not out:
            return []
        last = out[-1]
        if last.get("role") == "assistant" and not self._has_tool_use(last):
            out.append({"role": "user", "content": [_text_block(f"[SYSTEM]\n{WORK_MSG}")]})
        return out

    def _has_tool_use(self, msg: dict) -> bool:
        return any(b.get("type") == "tool_use" for b in msg.get("content", []))

    def repair(self):
        """Add missing tool_result messages for any assistant tool_use blocks."""
        if not self.messages:
            return

        i = 0
        repaired = False
        while i < len(self.messages):
            msg = self.messages[i]
            if msg.get("role") != "assistant":
                i += 1
                continue

            tool_call_ids = [
                b["id"] for b in msg.get("content", [])
                if b.get("type") == "tool_use" and b.get("id")
            ]
            if not tool_call_ids:
                i += 1
                continue

            existing_ids = set()
            j = i + 1
            while j < len(self.messages) and self.messages[j].get("role") == "user":
                for b in self.messages[j].get("content", []):
                    if b.get("type") == "tool_result":
                        existing_ids.add(b.get("tool_use_id", ""))
                j += 1

            missing = [tid for tid in tool_call_ids if tid not in existing_ids]
            if missing:
                insert_at = j
                for tid in missing:
                    self.messages.insert(insert_at, {
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "name": "unknown",
                            "content": "[ERROR: tool result missing — previous turn was interrupted]",
                        }],
                    })
                    insert_at += 1
                repaired = True
                i = insert_at
            else:
                i = j

        if repaired:
            self._persist_working()

    def add_message(self, role: str, content: list[dict] | str):
        """Add a complete internal-standard message."""
        assert role in ("system", "user", "assistant")
        if isinstance(content, str):
            content = [_text_block(content)]
        msg = {"role": role, "content": content, "ts": time.time()}
        self.messages.append(msg)
        with open(self.original_path, "a") as f:
            f.write(json.dumps(msg) + "\n")
        with open(self.working_path, "a") as f:
            f.write(json.dumps(msg) + "\n")

    def add_user_text(self, text: str):
        self.add_message("user", [_text_block(text)])

    def add_assistant_message(self, content_blocks: list[dict]):
        """Add an assistant message from internal content blocks."""
        self.add_message("assistant", content_blocks)

    def add_tool_result(self, tool_call_id: str, name: str, content: str | list):
        """Add a user message containing a single tool_result block."""
        self.add_message("user", [{
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "name": name,
            "content": content,
        }])

    @staticmethod
    def image_block(image_bytes: bytes) -> dict:
        return _image_block(image_bytes)

    def _persist_working(self):
        self.working_path.write_text(
            "\n".join(json.dumps(m) for m in self.messages) + "\n"
        )

    def needs_summary(self) -> bool:
        # count words across all messages. images = 1000 words.
        total = 0
        for msg in self.messages:
            for b in msg.get("content", []):
                t = b.get("type")
                if t == "text":
                    total += len(b.get("text", "").split())
                elif t == "tool_use":
                    args_text = json.dumps(b.get("arguments", {}))
                    total += len(args_text.split())
                elif t == "tool_result":
                    content = b.get("content", "")
                    if isinstance(content, str):
                        total += len(content.split())
                    elif isinstance(content, list):
                        for sub in content:
                            if sub.get("type") == "text":
                                total += len(sub.get("text", "").split())
                            elif sub.get("type") == "image":
                                total += 1000
                elif t == "image":
                    total += 1000
        return total >= MAX_WORDS

    def apply_summary(self, summary: str):
        # replace working memory with summary + last N messages.
        if len(self.messages) <= PRESERVE_LAST:
            return

        start = len(self.messages) - PRESERVE_LAST
        first = self.messages[start]
        # if the first preserved message is a tool_result user message, walk back to include the assistant
        if first.get("role") == "user" and any(
            b.get("type") == "tool_result" for b in first.get("content", [])
        ):
            while (
                start > 0
                and self.messages[start].get("role") == "user"
                and any(
                    b.get("type") == "tool_result" for b in self.messages[start].get("content", [])
                )
            ):
                start -= 1

        summary_msg = {"role": "assistant", "content": [_text_block(f"SUMMARIZED CONTEXT: {summary}")]}

        # archive summary to original
        with open(self.original_path, "a") as f:
            f.write(json.dumps(summary_msg) + "\n")

        tail = self.messages[start:]
        rebuilt = [summary_msg]
        if tail and tail[0].get("role") == "assistant":
            rebuilt.append({"role": "user", "content": [_text_block("[continue]")]})
        rebuilt.extend(tail)
        self.messages = rebuilt

        self._persist_working()

    def load_kv(self) -> KVCache:
        if self.kv_path.exists():
            # cybersec: weights_only=True blocks pickle code execution — without it a planted kv_cache.pt would run attacker code on load
            return torch.load(self.kv_path, weights_only=True)
        return None

    def save_kv(self, kv: KVCache):
        if kv is None:
            self.kv_path.unlink(missing_ok=True)
        else:
            torch.save(kv, self.kv_path)
