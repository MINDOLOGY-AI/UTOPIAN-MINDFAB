import asyncio
import logging
import os

import httpx

from fab.INT3RF4CE.back.model import Model, KVCache, register_provider
from fab.INT3RF4CE.back.adapter import KimiAdapter
from fab.INT3RF4CE.back.prompt import CONTEXT_SUMMARIZATION_PROMPT

API_TIMEOUT = 180
KIMI_BASE_URL = "https://api.moonshot.cn/v1/chat/completions"
KIMI_DEFAULT_MODEL = "kimi-k3"


@register_provider
class Kimi(Model):
    """Moonshot Kimi API wrapper using the Kimi native OpenAI-compatible adapter."""

    name = "kimi"
    adapter = KimiAdapter()
    models = {
        "kimi-k3": "kimi-k3",
        "kimi-k2.7-fast": "kimi-k2.7-fast",
    }

    @classmethod
    def make(cls, model_id: str) -> "Kimi":
        return cls(model=model_id)

    def __init__(self, model: str = KIMI_DEFAULT_MODEL, api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("MOONSHOT_API_KEY")
        if not self.api_key:
            raise RuntimeError("MOONSHOT_API_KEY not set in environment")
        self.client = httpx.AsyncClient()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def call(self, prompt: str, messages: list[dict], kv_cache: KVCache,
                   use_tools: bool = True, allowed_tools: set | None = None) -> tuple[list[dict], KVCache]:
        payload = self.adapter.to_api_payload(
            model=self.model,
            system_prompt=prompt,
            messages=messages,
            use_tools=use_tools,
            allowed_tools=allowed_tools,
        )

        response = await asyncio.wait_for(
            self.client.post(KIMI_BASE_URL, headers=self._headers(), json=payload, timeout=API_TIMEOUT),
            timeout=API_TIMEOUT,
        )
        self._check_response(response, payload)
        data = response.json()
        blocks = self.adapter.parse_api_response(data)
        return blocks, None

    async def summarize(self, messages: list[dict], kv_cache: KVCache) -> tuple[str, KVCache]:
        payload = self.adapter.to_api_payload(
            model=self.model,
            system_prompt=CONTEXT_SUMMARIZATION_PROMPT,
            messages=messages,
            use_tools=False,
        )

        response = await asyncio.wait_for(
            self.client.post(KIMI_BASE_URL, headers=self._headers(), json=payload, timeout=API_TIMEOUT),
            timeout=API_TIMEOUT,
        )
        self._check_response(response, payload)
        data = response.json()
        blocks = self.adapter.parse_api_response(data)
        # summary is expected as plain text
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text, None

    def _check_response(self, response: httpx.Response, payload: dict):
        """Raise on error, but log the status and a truncated response first."""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # cybersec: don't dump the full conversation payload into logs — status code plus the first 200 chars of the reply is enough to debug, and chat content shouldn't leak into log files
            logging.error("Kimi request failed: %s %.200s", exc.response.status_code, exc.response.text)
            raise
