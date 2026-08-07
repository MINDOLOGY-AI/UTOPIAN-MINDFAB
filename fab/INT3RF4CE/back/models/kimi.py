import asyncio
import logging

import httpx

from fab.INT3RF4CE.back.model import Model, KVCache, register_provider
from fab.INT3RF4CE.back.adapter import OpenAICompatAdapter
from fab.INT3RF4CE.back.prompt import CONTEXT_SUMMARIZATION_PROMPT

API_TIMEOUT = 180
KIMI_BASE_URL = "https://api.moonshot.cn/v1/chat/completions"
KIMI_DEFAULT_MODEL = "kimi-k3"


@register_provider
class Kimi(Model):
    """Moonshot Kimi API wrapper using the Kimi native OpenAI-compatible adapter."""

    name = "kimi"
    adapter = OpenAICompatAdapter()
    base_url = KIMI_BASE_URL
    # name of this provider's key in the user's secrets store (secrets.json)
    secret_name = "moonshot"
    SUPPORTED_ATTACHMENT_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    models = {
        "kimi-k3": "kimi-k3",
    }

    @classmethod
    def make(cls, model_id: str, get_key=None) -> "Kimi":
        # get_key: resolves a secret name from the user's secrets store (secrets.json) — the single source of truth
        return cls(model=model_id, api_key=get_key(cls.secret_name) if get_key else None)

    def __init__(self, model: str = KIMI_DEFAULT_MODEL, api_key: str | None = None):
        self.model = model
        if not api_key:
            raise RuntimeError(f"no '{self.secret_name}' key in the secrets store — add it on the secrets page")
        self.api_key = api_key
        self.client = httpx.AsyncClient()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def call(self, prompt: str, messages: list[dict], kv_cache: KVCache,
                   use_tools: bool = True, allowed_tools: set | None = None) -> tuple[dict, KVCache]:
        payload = self.adapter.to_api_payload(
            model=self.model,
            system_prompt=prompt,
            messages=messages,
            use_tools=use_tools,
            allowed_tools=allowed_tools,
        )

        response = await asyncio.wait_for(
            self.client.post(self.base_url, headers=self._headers(), json=payload, timeout=API_TIMEOUT),
            timeout=API_TIMEOUT,
        )
        self._check_response(response, payload)
        data = response.json()
        msg = self.adapter.parse_api_response(data)
        return msg, None

    async def summarize(self, messages: list[dict], kv_cache: KVCache) -> tuple[str, KVCache]:
        payload = self.adapter.to_api_payload(
            model=self.model,
            system_prompt=CONTEXT_SUMMARIZATION_PROMPT,
            messages=messages,
            use_tools=False,
        )

        response = await asyncio.wait_for(
            self.client.post(self.base_url, headers=self._headers(), json=payload, timeout=API_TIMEOUT),
            timeout=API_TIMEOUT,
        )
        self._check_response(response, payload)
        data = response.json()
        msg = self.adapter.parse_api_response(data)
        # summary is expected as plain text
        return msg.get("content") or "", None

    def _check_response(self, response: httpx.Response, payload: dict):
        """Raise on error, but log the status and a truncated response first."""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # cybersec: don't dump the full conversation payload into logs — status code plus the first 200 chars of the reply is enough to debug, and chat content shouldn't leak into log files
            logging.error("Kimi request failed: %s %.200s", exc.response.status_code, exc.response.text)
            raise
