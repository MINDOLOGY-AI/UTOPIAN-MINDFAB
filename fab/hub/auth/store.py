"""User and session storage for site-wide auth. Plain JSON files, no database.

fab/data/auth/users.json:    {username: {"salt": hex, "hash": hex, "created": ts}}
fab/data/auth/sessions.json: {sha256(token): {"user": username, "expires": ts}}
"""

import hashlib
import json
import secrets
import time
from pathlib import Path

AUTH_DIR = Path(__file__).resolve().parents[2] / "data" / "auth"
USERS_PATH = AUTH_DIR / "users.json"
SESSIONS_PATH = AUTH_DIR / "sessions.json"

COOKIE_NAME = "mindology_session"
SESSION_TTL = 30 * 24 * 3600  # 30 days, seconds

# scrypt parameters (OWASP-recommended minimums)
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1

MAX_USERNAME_LEN = 32


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text() or "{}")


def _save(path: Path, data: dict):
    # atomic write: tmp file + rename so a crash never leaves half a file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).hex()


def create_user(username: str, password: str):
    """Register a new user. Raises ValueError on invalid input or a taken name."""
    username = username.strip()
    if not username or len(username) > MAX_USERNAME_LEN or not all(c.isalnum() or c in "_-" for c in username):
        raise ValueError(f"username must be 1-{MAX_USERNAME_LEN} chars: letters, digits, _ or -")
    if not password:
        raise ValueError("password cannot be empty")
    users = _load(USERS_PATH)
    if username in users:
        raise ValueError("username taken")
    salt = secrets.token_bytes(16)
    users[username] = {
        "salt": salt.hex(),
        "hash": _hash_password(password, salt),
        "created": time.time(),
    }
    _save(USERS_PATH, users)


def verify_user(username: str, password: str) -> bool:
    entry = _load(USERS_PATH).get(username.strip())
    if not entry:
        return False
    salt = bytes.fromhex(entry["salt"])
    return secrets.compare_digest(entry["hash"], _hash_password(password, salt))


def _token_key(token: str) -> str:
    # cybersec: hash tokens at rest — without this a stolen sessions.json could be replayed to hijack accounts
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(username: str) -> str:
    sessions = _load(SESSIONS_PATH)
    token = secrets.token_hex(32)
    # cybersec: store only the token's hash, so a leaked sessions.json is useless to an attacker
    sessions[_token_key(token)] = {"user": username, "expires": time.time() + SESSION_TTL}
    _save(SESSIONS_PATH, sessions)
    return token


def user_for_token(token: str | None) -> str | None:
    """Return the session's username, or None if missing/expired. Prunes expired sessions."""
    if not token:
        return None
    sessions = _load(SESSIONS_PATH)
    key = _token_key(token)
    session = sessions.get(key)
    if not session:
        return None
    now = time.time()
    expired = [k for k, s in sessions.items() if s["expires"] < now]
    if expired:
        for k in expired:
            del sessions[k]
        _save(SESSIONS_PATH, sessions)
    if key in expired:
        return None
    return session["user"]


def delete_session(token: str | None):
    if not token:
        return
    sessions = _load(SESSIONS_PATH)
    if sessions.pop(_token_key(token), None) is not None:
        _save(SESSIONS_PATH, sessions)
