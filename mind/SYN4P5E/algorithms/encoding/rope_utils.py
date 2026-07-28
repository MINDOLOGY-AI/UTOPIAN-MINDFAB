'''
Helpers for applying Rotary Position Embeddings.
OlMo2 expects cos/sin computed once by RoPE and then injected into Q/K.
'''

import torch


def rotate_half(x):
    """Rotates half the hidden dims of the input."""
    x1 = x[..., : x.shape[-1] // 2]
    x2 = x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_pos_emb(q, k, cos, sin, unsqueeze_dim=1):
    """
    Applies Rotary Position Embedding to query and key tensors.

    Args:
        q, k: (batch, heads, seq, head_dim) by default
        cos, sin: (batch, seq, head_dim)
        unsqueeze_dim: where to insert the heads dimension so cos/sin broadcast.
                       1 for (batch, heads, seq, head_dim).
    Returns:
        rotated q, k with original dtypes preserved
    """
    q_type, k_type = q.dtype, k.dtype
    cos = cos.unsqueeze(unsqueeze_dim)
    sin = sin.unsqueeze(unsqueeze_dim)
    q_embed = (q * cos) + (rotate_half(q) * sin)
    k_embed = (k * cos) + (rotate_half(k) * sin)
    return q_embed.to(q_type), k_embed.to(k_type)
