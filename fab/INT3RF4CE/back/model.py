from abc import ABC, abstractmethod

import asyncio
import httpx
import torch

from fab.INT3RF4CE.back.adapter import Adapter

# outer tuple: one entry per layer (... means repeat N layers)
# inner tuple: (key_tensor, value_tensor) for that layer
# each tensor shape: (batch, heads, seq_len, head_dim)
# None for API models that don't expose kv cache
KVCache = tuple[tuple[torch.Tensor, torch.Tensor], ...] | None

# fallback order for the "hierarchy" model: on timeout / 429 / 5xx the next
# provider in line answers instead. each provider uses its own adapter.
HIERARCHY = ["kimi-k3", "deepseek-v4-flash", "z-ai/glm-5.2"]


class Model(ABC):
    """Base model wrapper. Subclass for API/local/remote models.

    Each subclass declares:
      name    - provider short name (e.g. "kimi")
      adapter - Adapter instance that converts internal standard <-> provider native
      models  - mapping of UI display names to provider model ids
    """

    name: str = ""
    adapter: Adapter | None = None
    models: dict[str, str] = {}
    # name of this provider's api key in the user's secrets store (None = no key needed)
    secret_name: str | None = None

    @classmethod
    def make(cls, model_id: str, get_key=None) -> "Model":
        """Factory that creates an instance for a model id listed in cls.models.
        get_key: optional callable resolving a provider's secret_name to an API key."""
        raise NotImplementedError

    @abstractmethod
    async def call(self, prompt: str, messages: list[dict], kv_cache: KVCache,
                   use_tools: bool = True, allowed_tools: set | None = None) -> tuple[list[dict], KVCache]:
        # returns: (content_blocks, updated_kv_cache)
        # content_blocks: list of internal standard blocks — text and tool_use mixed.
        # use_tools=False: tools omitted entirely; allowed_tools: only these command names.
        raise NotImplementedError

    @abstractmethod
    async def summarize(self, messages: list[dict], kv_cache: KVCache) -> tuple[str, KVCache]:
        # plain text summary; never uses tools.
        raise NotImplementedError


# registry of all concrete Model subclasses that are imported
MODEL_PROVIDERS: dict[str, type[Model]] = {}


def register_provider(cls: type[Model]) -> type[Model]:
    """Decorator to register a model provider."""
    MODEL_PROVIDERS[cls.name] = cls
    return cls


def get_model_class(model_id: str) -> type[Model] | None:
    """Find the provider class that supports the given model id."""
    for provider in MODEL_PROVIDERS.values():
        if model_id in provider.models.values():
            return provider
    return None


def list_available_models() -> dict[str, dict[str, str]]:
    """Return {provider_name: {display_name: model_id, ...}, ...}."""
    return {name: dict(provider.models) for name, provider in MODEL_PROVIDERS.items()}


@register_provider
class HierarchyModel(Model):
    """Ordered fallback across providers: on timeout / 429 / 5xx the next model
    in HIERARCHY answers instead. Each provider in the chain uses its own
    adapter, so switching models also switches adapters."""

    name = "hierarchy"
    models = {"hierarchy": "hierarchy"}

    @classmethod
    def make(cls, model_id: str, get_key=None) -> "HierarchyModel":
        chain = []
        for mid in HIERARCHY:
            provider = get_model_class(mid)
            if provider is None:
                raise ValueError(f"hierarchy: unknown model {mid}")
            chain.append(provider.make(mid, get_key=get_key))
        return cls(chain)

    def __init__(self, chain: list[Model]):
        self.chain = chain
        # the model that answered most recently (or the primary before any call)
        self.active_model = chain[0].model

    async def _try_chain(self, fn):
        last_err = None
        for m in self.chain:
            try:
                result = await fn(m)
                self.active_model = m.model
                return result
            except asyncio.TimeoutError as e:
                last_err = e
            except httpx.HTTPStatusError as e:
                # only fall through on overload/ratelimit/server errors — real
                # request bugs (4xx) should surface, not be retried downstream
                if e.response.status_code != 429 and e.response.status_code < 500:
                    raise
                last_err = e
        raise last_err

    async def call(self, prompt: str, messages: list[dict], kv_cache: KVCache,
                   use_tools: bool = True, allowed_tools: set | None = None) -> tuple[list[dict], KVCache]:
        return await self._try_chain(
            lambda m: m.call(prompt, messages, kv_cache, use_tools=use_tools, allowed_tools=allowed_tools)
        )

    async def summarize(self, messages: list[dict], kv_cache: KVCache) -> tuple[str, KVCache]:
        return await self._try_chain(lambda m: m.summarize(messages, kv_cache))
