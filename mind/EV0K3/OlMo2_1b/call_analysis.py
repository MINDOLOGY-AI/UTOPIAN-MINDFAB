# call static_analysis and dynamic_analysis on olmo2-1b
# saves jsons and htmls in mind/weights/EV0K3/OlMo2_1b/analysis

import sys
from pathlib import Path


PROJECT_ROOT = Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT))

from mind.EV0K3.OlMo2_1b import loader
from mind.SYN4P5E.probes import static_analysis


OUTPUT_DIR = PROJECT_ROOT / "mind" / "weights" / "EV0K3" / "OlMo2_1b" / "analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    print("Loading OlMo2-1B...")
    model, tokenizer, config = loader.build_model_and_tokenizer()

    print("Running static analysis...")
    static_analysis.analyze_model(model, str(OUTPUT_DIR / "static.json"))

    print(f"Done. Saved to {OUTPUT_DIR / 'static.json'}")


if __name__ == "__main__":
    main()
