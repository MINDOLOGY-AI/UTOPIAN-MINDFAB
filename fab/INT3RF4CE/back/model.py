from abc import ABC, abstractmethod

import torch

from fab.INT3RF4CE.back.adapter import Adapter

# outer tuple: one entry per layer (... means repeat N layers)
# inner tuple: (key_tensor, value_tensor) for that layer
# each tensor shape: (batch, heads, seq_len, head_dim)
# None for API models that don't expose kv cache
KVCache = tuple[tuple[torch.Tensor, torch.Tensor], ...] | None


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

    @classmethod
    def make(cls, model_id: str) -> "Model":
        """Factory that creates an instance for a model id listed in cls.models."""
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
