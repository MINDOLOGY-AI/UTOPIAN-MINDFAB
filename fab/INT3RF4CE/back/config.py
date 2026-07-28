import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE"

# per-user layout: DATA_DIR / {username} / {agents.json, config/, context/, workspace/}


def _load_env() -> None:
    """Load root .env into os.environ if present. Existing env vars take precedence."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


_load_env()
