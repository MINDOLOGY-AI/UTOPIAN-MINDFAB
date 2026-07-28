# normal SAE

import torch
import torch.nn as nn

class SAE (nn.Module):
    def __init__ (self,embed_dim, expansion_factor):
        super().__init__()
        self.embed_dim = embed_dim
        self.feature_dim = embed_dim * expansion_factor

        self.encoder_weight = nn.Parameter(torch.randn(self.feature_dim, self.embed_dim) / self.embed_dim ** 0.5) # (out, in) format
        self.encoder_bias = nn.Parameter(torch.randn(self.feature_dim) / self.embed_dim ** 0.5)
        self.decoder_weight = nn.Parameter(torch.randn(self.embed_dim, self.feature_dim) / self.feature_dim ** 0.5)
        # find a center to substract from all activations
        self.decoder_bias = nn.Parameter(torch.randn(self.embed_dim) / self.embed_dim ** 0.5)

        self.relu = nn.ReLU()

    def encode(self, input):
        pre_gate_features = (input - self.decoder_bias) @ self.encoder_weight.T + self.encoder_bias
        features = self.relu(pre_gate_features)
        return features

    def decode(self, features):
        return features @ self.decoder_weight.T

    def compute_loss(self, input, sparsity_coeff):
        features = self.encode(input)
        # average cross feature_dim and batch
        sparsity_loss = features.mean() * sparsity_coeff
        pred = self.decode(features)
        # average cross embed_dim and batch
        recon_loss = (input - pred).pow(2).mean()
        loss = sparsity_loss + recon_loss
        return loss
