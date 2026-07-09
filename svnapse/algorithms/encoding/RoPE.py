'''
RoPE (Rotary Positional Encoding) is a positional encoding used on the Q and K vectors per layer.
smaller embed coordinate rotate faster and larger sentence pos rotates more
the formula is for angle to rotate by is:
theta_p,d = p * 1.0 / (base ** (2d/D))
we rotate by dimension pairs so each even dimension is the x and each odd dimension is the y. we rotate with the cos and sin rotation matrix.
a benefit of this is dot product only sees the difference in angles. at the same embed coordinate pair, the angle difference between pos 100 and 98 is the same difference as pos 5 and 3.
Qrot dot Krot = |Q||K|cos(theta_original + a - b)
theta_original is the unrotated angle between Q and K. a is angle of how Q is rotated and b is angle of how K is rotated.
a = pos_a * inv_freq, b = pos_b * inv_freq, so a - b = (pos_a - pos_b) * inv_freq. so it is only determined by the difference in positions.

earlier coordinates have larger inv_freq so rotate faster, more useful for earlier positions
however at later positions it rotates too many circles and becomes indistinguishable for the model so we rely on latter coordinates with smaller inv_freq to maintain distinctiveness.

OlMo2 tweak: this module only *computes* cos/sin from position_ids.
The actual rotation is done by apply_rotary_pos_emb in rope_utils.py.
This matches the HF-style separation and makes KV-cache decoding easy.
'''

import torch
import torch.nn as nn


class RoPE(nn.Module):
    def __init__(self, dim, max_seq_len=8192, base=10000.0):
        super().__init__()
        self.dim = dim
        self.max_seq_len = max_seq_len
        self.base = base

        # one freq per dimension pair
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim))
        self.register_buffer('inv_freq', inv_freq, persistent=False)

    def forward(self, x, position_ids):
        """
        x:           (batch, seq_len, ...) -- only device/dtype is used
        position_ids:(batch, seq_len) integer positions
        returns:     (cos, sin), each (batch, seq_len, dim)
        """
        # inv_freq: (dim//2)
        # position_ids: (batch, seq)
        # freqs: (batch, seq, dim//2)
        freqs = torch.outer(position_ids.view(-1).float(), self.inv_freq)
        freqs = freqs.view(*position_ids.shape, -1)

        # concat so cos/sin have full dim
        emb = torch.cat([freqs, freqs], dim=-1)  # (batch, seq, dim)

        cos = emb.cos().to(x.dtype)
        sin = emb.sin().to(x.dtype)
        return cos, sin
