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
KEEP_RECENT_SCREENSHOTS = 3  # screenshots that survive elision in marshal()

# keys that go on the wire — everything else (e.g. ts) is local metadata
_API_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name"}

# block types of the pre-OpenAI internal standard — a working.jsonl containing
# these is archived wholesale instead of migrated (old contexts are worthless)
_LEGACY_BLOCK_TYPES = {"tool_use", "tool_result", "image"}

SCREENSHOT_MARKER = "[screenshot]"
REPAIR_NOTE = "[ERROR: tool result missing — previous turn was interrupted]"
ELIDED_NOTE = "[screenshot omitted — old desktop view; call LOOK for a fresh one]"


def _image_part(image_bytes: bytes) -> dict:
    # original: 0-255 (8 bit) -> base64: 6 bit ASCII -> utf8 string
    img_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{img_data}"},
    }


def _looks_legacy(messages: list[dict]) -> bool:
    for m in messages:
        content = m.get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") in _LEGACY_BLOCK_TYPES for b in content
        ):
            return True
    return False


def _is_screenshot_msg(msg: dict) -> bool:
    # a screenshot user message carries the marker text part next to the images —
    # user-attached images have no marker and are never elided
    content = msg.get("content")
    return (
        msg.get("role") == "user"
        and isinstance(content, list)
        and any(p.get("type") == "text" and p.get("text") == SCREENSHOT_MARKER for p in content)
    )


def _elide_old_screenshots(out: list[dict]) -> list[dict]:
    # api-only elision: keep the newest KEEP_RECENT_SCREENSHOTS images, swap older
    # ones for a text reference. self.messages is shared structure — copy on write.
    shots = []
    for mi, m in enumerate(out):
        if not _is_screenshot_msg(m):
            continue
        for pi, p in enumerate(m["content"]):
            if p.get("type") == "image_url":
                shots.append((mi, pi))
    for mi, pi in shots[:-KEEP_RECENT_SCREENSHOTS] if len(shots) > KEEP_RECENT_SCREENSHOTS else []:
        m = out[mi]
        content = [dict(p) for p in m["content"]]
        content[pi] = {"type": "text", "text": ELIDED_NOTE}
        out[mi] = {**m, "content": content}
    return out


class Context:
    """Manages agent conversation memory in the canonical OpenAI chat-completions format.

    Messages:
      {"role": "system", "content": str}
      {"role": "user", "content": str | [text_part | image_url_part]}
      {"role": "assistant", "content": str (optional), "tool_calls": [...]}
      {"role": "tool", "tool_call_id": str, "name": str, "content": str}

    Screenshots split in two: a tool message ("[image result]") answering the
    tool_call, then a user message with a "[screenshot]" marker text part plus
    the image_url parts. The marker tells the model what the image is and gives
    elision something to key on.

    Adapters pass these messages through nearly verbatim — they only wrap tool
    schemas, add reasoning params, and parse responses.

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

        self.messages = [
            json.loads(line)
            for line in self.working_path.read_text().strip().splitlines()
            if line.strip()
        ]
        if _looks_legacy(self.messages):
            legacy_path = self.folder / "working.legacy.jsonl"
            self.working_path.replace(legacy_path)
            self.working_path.touch()
            print(f"[context] {user}/{name}: legacy block-format context archived "
                  f"to {legacy_path.name} — starting fresh")
            self.messages = []

        # upload parts (text/image_url) injected into the NEXT marshal only — the
        # bytes never persist into context, so uploads don't bloat future turns
        self.pending_attachments: list[dict] = []

    def get_prompt(self, chat_mode: bool = False) -> str:
        # SYSTEM PROMPT: global prompt + graph context (+ chat mode)
        return build_system_prompt(self.user, self.name, chat_mode=chat_mode)

    def marshal(self) -> list[dict]:
        """Return canonical API-ready messages (local metadata stripped).

        Injects a WORK_MSG user message when the last message is an assistant
        message with no tool_calls, so the API has a user message to respond to.
        This injection is API-only and is not persisted to context.
        Old screenshots are elided to text references the same way (_elide_old_screenshots).
        """
        self.repair()

        if not self.messages and not self.pending_attachments:
            return []
        out = [{k: v for k, v in m.items() if k in _API_KEYS} for m in self.messages]
        if self.pending_attachments:
            parts = self.pending_attachments
            self.pending_attachments = []
            texts = [p["text"] for p in parts if p.get("type") == "text"]
            images = [p for p in parts if p.get("type") == "image_url"]
            if images:
                # text-only content stays a plain string; with images the API
                # needs a list of parts (it rejects a bare dict content)
                content = ([{"type": "text", "text": "\n".join(texts)}] if texts else []) + images
            else:
                content = "\n".join(texts)
            out.append({"role": "user", "content": content})
        if not out:
            return []
        last = out[-1]
        if last.get("role") == "assistant" and not last.get("tool_calls"):
            out.append({"role": "user", "content": f"[SYSTEM]\n{WORK_MSG}"})
        return _elide_old_screenshots(out)

    def repair(self, note: str = REPAIR_NOTE):
        """Insert placeholder tool messages for any unanswered tool_calls.

        Position matters: tool messages must immediately follow the assistant
        tool_calls run, before any non-tool message — so missing results are
        inserted right after the run (in tool_calls order), not appended."""
        if not self.messages:
            return

        i = 0
        repaired = False
        while i < len(self.messages):
            msg = self.messages[i]
            tool_calls = msg.get("tool_calls") if msg.get("role") == "assistant" else None
            if not tool_calls:
                i += 1
                continue

            existing_ids = set()
            j = i + 1
            while j < len(self.messages) and self.messages[j].get("role") == "tool":
                existing_ids.add(self.messages[j].get("tool_call_id", ""))
                j += 1

            missing = [tc for tc in tool_calls if tc.get("id") and tc["id"] not in existing_ids]
            if missing:
                for k, tc in enumerate(missing):
                    self.messages.insert(j + k, {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc.get("function", {}).get("name", "unknown"),
                        "content": note,
                        "ts": time.time(),
                    })
                repaired = True
                i = j + len(missing)
            else:
                i = j

        if repaired:
            self._persist_working()

    def add_message(self, role: str, content=None, **extra):
        """Append a complete canonical message (content: str or content-part list)."""
        msg = {"role": role, **extra}
        if content is not None:
            msg["content"] = content
        msg["ts"] = time.time()
        self.messages.append(msg)
        with open(self.original_path, "a") as f:
            f.write(json.dumps(msg) + "\n")
        with open(self.working_path, "a") as f:
            f.write(json.dumps(msg) + "\n")

    def add_user_text(self, text: str):
        self.add_message("user", text)

    def add_assistant_message(self, msg: dict):
        """Add the canonical assistant message dict produced by the model layer."""
        self.add_message("assistant", msg.get("content"),
                         **{k: v for k, v in msg.items() if k not in ("role", "content")})

    def add_tool_result(self, tool_call_id: str, name: str, content: str | list):
        """Answer a tool_call. String content -> plain tool message. Content with
        image parts -> tool message (text or "[image result]") followed by a user
        message with the "[screenshot]" marker + image_url parts."""
        if isinstance(content, str):
            self.add_message("tool", content, tool_call_id=tool_call_id, name=name)
            return
        texts = [p.get("text", "") for p in content if p.get("type") == "text"]
        images = [p for p in content if p.get("type") == "image_url"]
        self.add_message("tool", "\n".join(t for t in texts if t).strip() or "[image result]",
                         tool_call_id=tool_call_id, name=name)
        if images:
            self.add_message("user", [{"type": "text", "text": SCREENSHOT_MARKER}] + images)

    def close_dangling_tool_calls(self, note: str = "[interrupted] this tool call was cancelled before it finished"):
        """A turn cancelled mid-execution (pause, single-turn switch) can leave an
        assistant message with tool_calls that never got their tool message.
        Provider APIs reject that dangling state, so every later turn fails
        silently. close any unanswered tool_call with a note result."""
        self.repair(note)

    @staticmethod
    def image_part(image_bytes: bytes) -> dict:
        return _image_part(image_bytes)

    def _persist_working(self):
        self.working_path.write_text(
            "\n".join(json.dumps(m) for m in self.messages) + "\n"
        )

    def needs_summary(self) -> bool:
        # count words across all messages. images = 1000 words.
        total = 0
        for msg in self.messages:
            content = msg.get("content")
            if isinstance(content, str):
                total += len(content.split())
            elif isinstance(content, list):
                for p in content:
                    t = p.get("type")
                    if t == "text":
                        total += len(p.get("text", "").split())
                    elif t == "image_url":
                        total += 1000
            for tc in msg.get("tool_calls") or []:
                total += len(tc.get("function", {}).get("arguments", "").split())
        return total >= MAX_WORDS

    def apply_summary(self, summary: str):
        # replace working memory with summary + last N messages.
        if len(self.messages) <= PRESERVE_LAST:
            return

        start = len(self.messages) - PRESERVE_LAST
        # if the first preserved message is a tool message, walk back to include the assistant
        while start > 0 and self.messages[start].get("role") == "tool":
            start -= 1

        summary_msg = {"role": "assistant", "content": f"SUMMARIZED CONTEXT: {summary}"}

        # archive summary to original
        with open(self.original_path, "a") as f:
            f.write(json.dumps(summary_msg) + "\n")

        tail = self.messages[start:]
        rebuilt = [summary_msg]
        if tail and tail[0].get("role") == "assistant":
            rebuilt.append({"role": "user", "content": "[continue]"})
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
