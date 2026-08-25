'''kimi (moonshot) provider. keys come from the repo-root .env via fab.config — secrets machinery comes later.'''

import os

import httpx

from fab.config import API_TIMEOUT
from fab.corechat.oldback import adapter, prompt

BASE_URL = "https://api.moonshot.cn/v1/chat/completions"
MODEL = "kimi-k3"


async def call(system: str | None, messages: list, tools: list | None = None,
               model: str = MODEL, max_tokens: int | None = None) -> dict:
    payload = adapter.build_payload(model, system, messages, tools)
    payload["reasoning_effort"] = "max"
    if max_tokens:
        payload["max_tokens"] = max_tokens
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(BASE_URL, json=payload,
                              headers={"Authorization": f"Bearer {os.environ['MOONSHOT_API_KEY']}"})
    r.raise_for_status()
    return adapter.parse_response(r.json())


async def summarize(messages: list) -> str:
    msg = await call(prompt.SUMMARIZE, messages)
    return msg.get("content") or ""
