"""User-level secrets store: flat key -> value pairs, each with a category.

Layout (per user):
  DATA_DIR / {user} / secrets.json                            — {"name": {"value": ..., "cat": ...}}, chmod 600
  DATA_DIR / {user} / config / specific / {agent} / secrets.json — {"grants": ["name", ...]}

Categories: "llm" (api keys the backend hard-resolves by name), "compute" (ssh
targets), "account" (github tokens etc.), "git" (forced {"account", "key"} pairs:
a github identity + its ssh private key), "gitrepo" (repo urls — not actually
secret, just kept here so everything git lives in one place).
Only llm names are validated (server-side, against the registered providers).

Two consumers, one store:
  backend code (model providers, etc.) resolves keys by name via resolve() — the
  value never enters the agent's context unless the user also grants it.
  agents read only their granted subset via the READ_SECRETS tool.
"""

import json
import re
from pathlib import Path

from fab.INT3RF4CE.back.config import DATA_DIR

# cybersec: secret names are shown in UIs and used as identifiers — keep them plain
KEY_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")

CATEGORIES = ("llm", "compute", "account", "git", "gitrepo")


def _store_path(user: str) -> Path:
    return DATA_DIR / user / "secrets.json"


def _grants_path(user: str, agent: str) -> Path:
    return DATA_DIR / user / "config" / "specific" / agent / "secrets.json"


def load(user: str) -> dict:
    """Raw store: {name: {"value": str, "cat": str}}. Plain-string legacy entries
    are normalized to cat "account"."""
    path = _store_path(user)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {k: (v if isinstance(v, dict) else {"value": v, "cat": "account"})
            for k, v in raw.items()}


def save(user: str, secrets: dict):
    path = _store_path(user)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(secrets, indent=2))
    path.chmod(0o600)


def names(user: str) -> list[str]:
    return sorted(load(user))


def items(user: str) -> list[dict]:
    """Secrets for the UI: [{"name", "cat", ...}] sorted by name.
    Only non-secret fields leave the host: gitrepo urls and git account names
    are included; actual secret values (keys, tokens, llm keys) never are."""
    out = []
    for k, v in sorted(load(user).items()):
        item = {"name": k, "cat": v["cat"]}
        if v["cat"] == "gitrepo":
            item["value"] = v["value"]
        elif v["cat"] == "git":
            item["value"] = {"account": v["value"].get("account", "")}
        out.append(item)
    return out


def resolve(user: str, name: str) -> str | None:
    """Backend-side lookup: the secret value for a name, or None."""
    entry = load(user).get(name)
    return entry["value"] if entry else None


def set_secret(user: str, key: str, value, cat: str = "account"):
    if not KEY_RE.fullmatch(key):
        raise ValueError(f"invalid secret name: {key!r} (allowed: a-z 0-9 _ . -)")
    if cat not in CATEGORIES:
        raise ValueError(f"invalid category: {cat!r} (one of {', '.join(CATEGORIES)})")
    if cat == "git":
        # forced format: a github identity + its ssh private key, always together
        if not isinstance(value, dict) or not value.get("account") or not value.get("key"):
            raise ValueError('git secrets must be {"account": ..., "key": ...}')
        if "PRIVATE KEY" not in value["key"]:
            raise ValueError("git key must be an ssh private key (should contain 'PRIVATE KEY')")
    elif not isinstance(value, str) or not value:
        raise ValueError("secret value required")
    secrets = load(user)
    secrets[key] = {"value": value, "cat": cat}
    save(user, secrets)


def delete_secret(user: str, key: str):
    secrets = load(user)
    if key not in secrets:
        raise ValueError(f"no secret named {key!r}")
    del secrets[key]
    save(user, secrets)
    # strip the deleted key from every agent's grant list
    specific = DATA_DIR / user / "config" / "specific"
    if specific.exists():
        for agent_dir in specific.iterdir():
            grants = load_grants(user, agent_dir.name)
            if key in grants:
                grants.remove(key)
                save_grants(user, agent_dir.name, grants)


def load_grants(user: str, agent: str) -> list[str]:
    path = _grants_path(user, agent)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("grants", [])
    except Exception:
        return []


def save_grants(user: str, agent: str, grants: list[str]):
    path = _grants_path(user, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"grants": grants}))


def granted(user: str, agent: str) -> dict:
    """The agent's granted secrets as flat {name: value} — only names that still exist."""
    secrets = load(user)
    return {name: secrets[name]["value"] for name in load_grants(user, agent) if name in secrets}
