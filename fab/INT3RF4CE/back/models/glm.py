import os

from fab.INT3RF4CE.back.model import register_provider
from fab.INT3RF4CE.back.models.kimi import Kimi
from fab.INT3RF4CE.back.adapter import GLMAdapter

# OpenRouter's OpenAI-compatible endpoint — one key for all non-kimi providers
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


@register_provider
class GLM(Kimi):
    """Zhipu GLM via OpenRouter — OpenAI-compatible wire format, GLMAdapter for thinking params."""

    name = "glm"
    adapter = GLMAdapter()
    base_url = OPENROUTER_BASE_URL
    models = {
        # OpenRouter model slug — change here if the id changes upstream
        "glm-5.2": "z-ai/glm-5.2",
    }

    def __init__(self, model: str = "z-ai/glm-5.2", api_key: str | None = None):
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set in environment")
        super().__init__(model=model, api_key=key)
