from mind.D4T4STEPS.config import TARGETS

print("=== D4T4STEPS SAE MIX DOWNLOAD ===\n")

total_target = sum(TARGETS.values())
print(f"Target: {total_target:,} tokens total\n")

for name, target in TARGETS.items():
    print(f"[{name}] ~{target:,} tokens")

print("\n===================================\n")

import mind.D4T4STEPS.download_scripts.interp_dataset.dclm_baseline as _dc  # noqa: F401
import mind.D4T4STEPS.download_scripts.interp_dataset.starcoder as _sc  # noqa: F401
import mind.D4T4STEPS.download_scripts.interp_dataset.wikipedia_en as _wi  # noqa: F401
import mind.D4T4STEPS.download_scripts.interp_dataset.openwebmath as _ow  # noqa: F401
import mind.D4T4STEPS.download_scripts.interp_dataset.arxiv as _ax  # noqa: F401
import mind.D4T4STEPS.download_scripts.interp_dataset.tulu3_sft as _t3  # noqa: F401

print("\n=== DOWNLOAD COMPLETE ===")
