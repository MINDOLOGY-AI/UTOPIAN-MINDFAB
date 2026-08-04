import json
import torch
import torch.nn as nn
from pathlib import Path

from mind.EV0K3.OlMo2_1b.run.loader import build_model_and_tokenizer
from mind.SYN4P5E.train.simple_train import simple_train, simple_eval
from mind.SYN4P5E.train.data_to_loaders import BinUnsupervisedDataset
from mind.SYN4P5E.probes.sae.SAE import SAE
from mind.SYN4P5E.probes.sae.JumpReluSAE import JumpReLU_SAE
from mind.SYN4P5E.probes.sae.SlabConeSAE import SlabConeSAE


BIN_DIR = Path.cwd() / "mind" / "data" / "D4T4STEPS" / "tokenized" / "interp_dataset"
WEIGHTS_DIR = Path.cwd() / "mind" / "weights" / "EV0K3" / "OlMo2_1b" / "sae_compare"
D_IN = 2048
EXPANSION = 16
D_SAE = D_IN * EXPANSION  # 32768
K = 64
MAX_STEPS = 100_000
BATCH_SIZE = 4
LAYER_IDX = 8


# =============================================================================
# TopK SAE — built-in sparsity via top-k selection, no penalty coefficient
# =============================================================================
class TopKSAE(nn.Module):
    def __init__(self, d_in, d_sae, k=64):
        super().__init__()
        self.d_in = d_in
        self.d_sae = d_sae
        self.k = k

        self.W_enc = nn.Parameter(torch.randn(d_in, d_sae) * 0.01)
        self.b_enc = nn.Parameter(torch.zeros(d_sae))
        self.W_dec = nn.Parameter(torch.randn(d_sae, d_in) * 0.01)
        self.b_dec = nn.Parameter(torch.zeros(d_in))

    def _norm_decoder(self):
        with torch.no_grad():
            self.W_dec.data /= self.W_dec.data.norm(dim=1, keepdim=True).clamp(min=1e-8)

    def compute_loss(self, batch_data):
        self._norm_decoder()
        # batch_data: (B*seq_len, 2048)
        x = batch_data - self.b_dec
        pre = x @ self.W_enc + self.b_enc             # (N, d_sae)
        _, topk_idx = torch.topk(pre, self.k, dim=-1)
        mask = torch.zeros_like(pre)
        mask.scatter_(-1, topk_idx, 1.0)
        f = pre * mask                                 # (N, d_sae) — k active features
        x_hat = f @ self.W_dec + self.b_dec            # (N, d_in)
        recon_loss = ((batch_data - x_hat) ** 2).sum(dim=-1).mean()
        activation_energy = batch_data.pow(2).mean()
        active_count = (f > 0).float().sum(dim=-1).mean()
        metrics = {
            "active": active_count.item(),
            "recon_pct": (recon_loss / activation_energy * 100.0).item(),
        }
        return recon_loss, metrics


# =============================================================================
# Activation trainer — hooks frozen LM, feeds acts to SAE
# =============================================================================
class ActivationTrainer(nn.Module):
    def __init__(self, lm, sae, layer_idx=LAYER_IDX):
        super().__init__()
        self.lm = lm
        self.sae = sae
        self.lm.eval()
        for p in self.lm.parameters():
            p.requires_grad = False
        self._acts = None
        self._hook_handle = self.lm.model.layers[layer_idx].register_forward_hook(self._capture)

    def remove_hook(self):
        if self._hook_handle is not None:
            self._hook_handle.remove()
            self._hook_handle = None

    def _capture(self, module, input, output):
        # output: (hidden_states, present_kv) from Olmo2DecoderLayer.forward
        self._acts = output[0].detach()                # (B, seq_len, 2048)

    def compute_loss(self, token_chunk):
        # token_chunk: (B, 1024) int32/int64
        with torch.no_grad():
            self.lm.model(input_ids=token_chunk)
        # flatten batch+seq into (B*1024, 2048)
        acts = self._acts.reshape(-1, self._acts.shape[-1])
        return self.sae.compute_loss(acts)

    def train(self, mode=True):
        super().train(mode)
        self.lm.eval()
        return self


# =============================================================================
# main — train all 4 SAE types, compare eval
# =============================================================================
def main():
    meta = json.loads((BIN_DIR / "meta.json").read_text())
    train_shape = tuple(meta["train_shape"])  # type: ignore
    eval_shape = tuple(meta["eval_shape"])  # type: ignore

    train_ds = BinUnsupervisedDataset(str(BIN_DIR / "train.bin"), torch.int32, train_shape)
    eval_ds = BinUnsupervisedDataset(str(BIN_DIR / "eval.bin"), torch.int32, eval_shape)

    lm, _, _ = build_model_and_tokenizer()

    sae_builders = {
        "vanilla":  lambda: SAE(D_IN, EXPANSION, sparsity_coeff=1e-3),
        "jumprelu": lambda: JumpReLU_SAE(D_IN, D_SAE, sparsity_coeff=1e-3),
        "topk":     lambda: TopKSAE(D_IN, D_SAE, k=K),
        "slabcone": lambda: SlabConeSAE(D_IN, EXPANSION, sparsity_coeff=1e-3, target_active=64),
    }

    results = {}

    for name, build in sae_builders.items():
        print(f"\n{'='*60}")
        print(f"=== {name} ===")
        print(f"{'='*60}")

        sae = build()
        trainer = ActivationTrainer(lm, sae)
        opt = torch.optim.Adam(trainer.parameters(), lr=7e-5, betas=(0.0, 0.999))

        save_dir = WEIGHTS_DIR / name
        save_dir.mkdir(parents=True, exist_ok=True)

        simple_train(
            model=trainer,
            dataset=train_ds,
            batch_size=BATCH_SIZE,
            optimizer=opt,
            epochs=1,
            save_path=str(save_dir),
            batches_per_log=100,
            batches_per_save=10_000_000,  # essentially never — no checkpoints
            eval_dataset=eval_ds,
            eval_batch_size=BATCH_SIZE,
            max_steps=MAX_STEPS,
        )

        print(f"\n--- {name} final eval ---")
        eval_metrics = simple_eval(trainer, eval_ds, BATCH_SIZE, batches=10000)
        trainer.remove_hook()
        results[name] = eval_metrics
        for k, v in eval_metrics.items():
            print(f"  {k}: {v:.4f}")

    print(f"\n{'='*60}")
    print("=== COMPARISON ===")
    print(f"{'='*60}")
    header = f"{'SAE':<12} {'recon_pct':>10} {'active':>10}"
    print(header)
    print("-" * len(header))
    for name, metrics in results.items():
        print(f"{name:<12} {metrics.get('recon_pct', 0):>10.1f} {metrics.get('active', 0):>10.1f}")


if __name__ == "__main__":
    main()
