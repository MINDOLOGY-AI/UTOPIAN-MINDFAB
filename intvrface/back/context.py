import json
import base64
import torch
from pathlib import Path

from intvrface.back.prompt import WORK_MSG, CLAUDY_PROMPT
from intvrface.back.config import DATA_DIR

# outer tuple: one entry per layer (... means repeat N layers)
# inner tuple: (key_tensor, value_tensor) for that layer
# each tensor shape: (batch, heads, seq_len, head_dim)
# None for API models that don't expose kv cache
KVCache = tuple[tuple[torch.Tensor, torch.Tensor], ...] | None


CONTEXT_ROOT = DATA_DIR / "context"
MAX_WORDS = 64000
PRESERVE_LAST = 5


class Context:
    """
    Manages context for an agent session.

    Storage IS Claude API format. Two roles only: "user" and "assistant".
    Each message has content = list of blocks (text / tool_use / tool_result / image).
    Frontend distinguishes display rows by block type, not by role.

    Files in context/{name}/:
        original.jsonl   - full log, append-only archive
        working.jsonl    - current working memory (loaded on startup)
        kv_cache.pt      - cached key/values for local models
        user_prompt.json - persistent task prompt injected into system prompt
    """

    def __init__(self, name: str):
        self.name = name
        self.folder = CONTEXT_ROOT / name
        self.folder.mkdir(parents=True, exist_ok=True)

        self.original_path = self.folder / "original.jsonl"
        self.working_path = self.folder / "working.jsonl"
        self.kv_path = self.folder / "kv_cache.pt"
        self.user_prompt_path = self.folder / "user_prompt.json"

        self.original_path.touch(exist_ok=True)
        self.working_path.touch(exist_ok=True)
        # [{"role": "user"|"assistant", "content": [block, ...]}, ...]
        self.messages: list[dict] = [json.loads(line) for line in self.working_path.read_text().strip().splitlines()]

    def get_prompt(self) -> str:
        # SYSTEM PROMPT + optional USER PROMPT from user_prompt.json
        prompt = f"SYSTEM PROMPT:\n{CLAUDY_PROMPT}"
        if self.user_prompt_path.exists():
            user_prompt = json.loads(self.user_prompt_path.read_text()).get("user_prompt", "")
            if user_prompt:
                prompt += f"\n\nUSER PROMPT:\n{user_prompt}"
        return prompt

    def set_user_prompt(self, text: str):
        self.user_prompt_path.write_text(json.dumps({"user_prompt": text}))

    def marshal(self) -> list[dict]:
        # storage is already API format. only special case: if last message is
        # assistant with NO tool_use blocks (pure-text turn), append WORK_MSG as
        # user — API requires last message be user. injection is API-only.
        if not self.messages:
            return []
        out = [dict(m) for m in self.messages]  # shallow copy of message dicts
        last = out[-1]
        if last["role"] == "assistant":
            has_tool_use = any(b.get("type") == "tool_use" for b in last["content"])
            if not has_tool_use:
                out.append({"role": "user", "content": [{"type": "text", "text": f"[SYSTEM]\n{WORK_MSG}"}]})
        return out

    def add_message(self, role: str, content: list[dict]):
        # add a complete message (one role + list of blocks). always creates a new entry.
        assert role in ("user", "assistant")
        assert isinstance(content, list) and len(content) > 0
        msg = {"role": role, "content": content}  # {"role": str, "content": [block, ...]}
        self.messages.append(msg)
        with open(self.original_path, "a") as f:
            f.write(json.dumps(msg) + "\n")
        with open(self.working_path, "a") as f:
            f.write(json.dumps(msg) + "\n")

    def add_user_text(self, text: str):
        self.add_message("user", [{"type": "text", "text": text}])

    @staticmethod
    def image_block(image_bytes: bytes) -> dict:
        # original: 0-255 (8 bit) -> base64: 6 bit ASCII -> utf8 string
        img_data = base64.standard_b64encode(image_bytes).decode("utf-8")
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": img_data},
        }

    def needs_summary(self) -> bool:
        # count words across all text/tool_use/tool_result blocks. images = 1000 words.
        total = 0
        for msg in self.messages:
            for block in msg.get("content", []):
                t = block.get("type")
                if t == "text":
                    total += len(block.get("text", "").split())
                elif t == "tool_use":
                    # input dict serialized as text approximation
                    total += len(json.dumps(block.get("input", {})).split())
                elif t == "tool_result":
                    inner = block.get("content", "")
                    if isinstance(inner, str):
                        total += len(inner.split())
                    else:
                        for sub in inner:
                            if sub.get("type") == "text":
                                total += len(sub.get("text", "").split())
                            elif sub.get("type") == "image":
                                total += 1000
                elif t == "image":
                    total += 1000
        return total >= MAX_WORDS

    def apply_summary(self, summary: str):
        # replace working memory with summary + last N messages.
        # constraint: tool_use blocks in an assistant message MUST be matched by
        # tool_result blocks in the next user message. if PRESERVE_LAST would
        # start at a tool_result-leading user message, we walk back one to keep
        # the pair together.
        if len(self.messages) <= PRESERVE_LAST:
            return  # everything preserved anyway

        start = len(self.messages) - PRESERVE_LAST
        first = self.messages[start]
        if first["role"] == "user" and first["content"] and first["content"][0].get("type") == "tool_result":
            start -= 1

        summary_msg = {"role": "assistant", "content": [{"type": "text", "text": f"SUMMARIZED CONTEXT: {summary}"}]}

        # archive summary to original
        with open(self.original_path, "a") as f:
            f.write(json.dumps(summary_msg) + "\n")

        # summary is assistant; first message after it must be user (API rule).
        tail = self.messages[start:]
        rebuilt = [summary_msg]  # [{"role": str, "content": [block, ...]}, ...]
        if tail[0]["role"] == "assistant":
            rebuilt.append({"role": "user", "content": [{"type": "text", "text": "[continue]"}]})
        rebuilt.extend(tail)
        self.messages = rebuilt

        # overwrite working.jsonl
        self.working_path.write_text(
            '\n'.join(json.dumps(msg) for msg in self.messages) + '\n'
        )

    def load_kv(self) -> KVCache:
        if self.kv_path.exists():
            return torch.load(self.kv_path)
        return None

    def save_kv(self, kv: KVCache):
        if kv is None:
            self.kv_path.unlink(missing_ok=True)
        else:
            torch.save(kv, self.kv_path)
