from pathlib import Path

PROJECT_ROOT = Path.cwd()
DATA_DIR = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE"

# per-user layout: DATA_DIR / {username} / {agents.json, config/, context/, workspace/}
# api keys come ONLY from the user's secrets store (secrets.json) — no env/.env fallbacks
