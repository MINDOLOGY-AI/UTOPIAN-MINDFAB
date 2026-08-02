import os

from fab.INT3RF4CE.back.model import register_provider
from fab.INT3RF4CE.back.models.kimi import Kimi
from fab.INT3RF4CE.back.adapter import KimiAdapter

# DeepSeek's official OpenAI-compatible endpoint (api-docs.deepseek.com)
DEEPSEEK_BASE_URL = "https://api.deepseek.com/chat/completions"


class DeepSeekAdapter(KimiAdapter):
    """DeepSeek uses its own thinking toggle instead of moonshot's reasoning params."""

    def reasoning_params(self, model: str) -> dict:
        return {"thinking": {"type": "enabled"}}


@register_provider
class DeepSeek(Kimi):
    """DeepSeek API wrapper — OpenAI-compatible wire format, DEEPSEEK_API_KEY env var.
    NOTE: v4 is text-only in the public API — no image input (no LOOK screenshots)."""

    name = "deepseek"
    adapter = DeepSeekAdapter()
    base_url = DEEPSEEK_BASE_URL
    secret_name = "deepseek"
    models = {
        "deepseek-v4-flash": "deepseek-v4-flash",
        "deepseek-v4-pro": "deepseek-v4-pro",
    }

    def __init__(self, model: str = "deepseek-v4-flash", api_key: str | None = None):
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY not set in environment")
        super().__init__(model=model, api_key=key)
