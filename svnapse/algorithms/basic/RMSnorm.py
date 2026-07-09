'''
RMSnorm scales by sqrt(n) and then multiplies by a learnable weight.
RMS is applied at the token level across the embed_dim. the total would be sqrt(n)*gamma rather than normal norm would be 1.
without gamma the mean(x_norm^2) = 1
RMS(x) = sqrt (1/n * sum(x^2)) * gamma

OlMo2 tweak: cast to float32 for numerical stability, multiply by weight,
then cast back to the input dtype.
'''

import torch
import torch.nn as nn


class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-6, cast_to_float32=True):
        super().__init__()
        self.eps = eps
        self.cast_to_float32 = cast_to_float32
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        # x: (batch, seq, dim)
        input_dtype = x.dtype
        if self.cast_to_float32 and x.dtype != torch.float32:
            x = x.to(torch.float32)

        variance = x.pow(2).mean(-1, keepdim=True)
        x_norm = x * torch.rsqrt(variance + self.eps)

        # OlMo2 multiplies weight before dtype conversion
        out = self.weight * x_norm
        return out.to(input_dtype)

    def extra_repr(self):
        return f"{tuple(self.weight.shape)}, eps={self.eps}, cast_to_float32={self.cast_to_float32}"
