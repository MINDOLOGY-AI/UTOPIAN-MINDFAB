import torch

# outer tuple: one entry per layer (... means repeat N layers)
# inner tuple: (key_tensor, value_tensor) for that layer
# each tensor shape: (batch, heads, seq_len, head_dim)
# None for API models that don't expose kv cache
KVCache = tuple[tuple[torch.Tensor, torch.Tensor], ...] | None


class Model:
    """
    Base model wrapper. Subclass for API/local/remote models.
    """

    async def call(self, prompt: str, messages: list[dict], kv_cache: KVCache,
                   use_tools: bool = True) -> tuple[list[dict], KVCache]:
        # returns: (content_blocks, updated_kv_cache)
        # content_blocks: list of Claude API content blocks — text and tool_use mixed.
        # use_tools=False: tools omitted (e.g. chat mode), so output is text-only.
        raise NotImplementedError

    async def summarize(self, messages: list[dict], kv_cache: KVCache) -> tuple[str, KVCache]:
        # plain text summary; never uses tools.
        raise NotImplementedError
