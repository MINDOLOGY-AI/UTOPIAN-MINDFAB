'''site-wide auth, plain json files, no database. one router mounted at /auth by hub/back/app.py;
user_for_token() is the cookie check used by the hub middleware and the websocket endpoints.

~/.fab/auth/users.json:    {username: {"salt": hex, "hash": hex, "created": ts}}
~/.fab/auth/sessions.json: {sha256(token): {"user": username, "expires": ts}}
'''

import hashlib
import json
import secrets
import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from fab.config import FAB_DIR

AUTH_DIR = FAB_DIR / "auth"
USERS_PATH = AUTH_DIR / "users.json"
SESSIONS_PATH = AUTH_DIR / "sessions.json"

COOKIE_NAME = "fab_session"
SESSION_TTL = 30 * 24 * 3600  # 30 days, seconds

# scrypt parameters (OWASP-recommended minimums)
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1

MAX_USERNAME_LEN = 32

router = APIRouter(prefix="/auth")


def _load(path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text() or "{}")


def _save(path, data: dict):
    # atomic write: tmp file + rename so a crash never leaves half a file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).hex()


# usernames become per-user dir names (users/{name}/), so the charset is the allowlist
def create_user(username: str, password: str):
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
    sessions[_token_key(token)] = {"user": username, "expires": time.time() + SESSION_TTL}
    _save(SESSIONS_PATH, sessions)
    return token


def user_for_token(token: str | None) -> str | None:
    '''return the session's username, or None if missing/expired. prunes expired sessions.'''
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


# login/register attempts per (username, ip), in-memory (resets on restart — fine)
MAX_ATTEMPTS = 20
ATTEMPT_WINDOW = 300  # seconds
_attempts: dict[tuple[str, str], list[float]] = {}


def _rate_limited(key: tuple[str, str]) -> bool:
    now = time.time()
    # cybersec: prune entries older than the window on every check — without this the dict grows forever (memory DoS)
    for k in list(_attempts):
        _attempts[k] = [t for t in _attempts[k] if now - t < ATTEMPT_WINDOW]
        if not _attempts[k]:
            del _attempts[k]
    return len(_attempts.get(key, [])) >= MAX_ATTEMPTS


def _record_attempt(key: tuple[str, str]):
    _attempts.setdefault(key, []).append(time.time())


def _set_session_cookie(request: Request, response: Response, token: str):
    # cybersec: mark the cookie Secure only when the request arrived over HTTPS (directly or via a
    # TLS-terminating proxy) — tokens can't be sniffed on public HTTPS, but http://localhost logins still work
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True, samesite="lax", path="/", secure=secure)


@router.post("/register")
async def register(request: Request, response: Response):
    assert request.client
    ip = request.client.host
    body = await request.json()
    username = body.get("username", "").strip()
    # cybersec: key the limit on (username, ip) — IP-only limits are bypassed by rotating IPs and
    # one shared proxy IP would lock out every user
    key = (username, ip)
    # cybersec: also cap registrations per IP regardless of username — otherwise an attacker just
    # invents a new username each attempt and mass-creates accounts (each one costs scrypt CPU + disk)
    ip_key = ("__register__", ip)
    if _rate_limited(key) or _rate_limited(ip_key):
        return JSONResponse({"error": "too many attempts, try again later"}, status_code=429)
    # cybersec: count every register attempt (not just failures) — unlimited account creation is a
    # CPU/disk DoS because each one runs scrypt and writes to disk
    _record_attempt(key)
    _record_attempt(ip_key)
    try:
        create_user(username, body.get("password", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _set_session_cookie(request, response, create_session(username))
    return {"user": username}


@router.post("/login")
async def login(request: Request, response: Response):
    assert request.client
    ip = request.client.host
    body = await request.json()
    username = body.get("username", "").strip()
    # cybersec: key the limit on (username, ip) so one user's brute-force doesn't lock out others on the same IP
    key = (username, ip)
    if _rate_limited(key):
        return JSONResponse({"error": "too many attempts, try again later"}, status_code=429)
    if not verify_user(username, body.get("password", "")):
        _record_attempt(key)
        return JSONResponse({"error": "wrong username or password"}, status_code=401)
    _set_session_cookie(request, response, create_session(username))
    return {"user": username}


@router.post("/logout")
async def logout(request: Request, response: Response):
    delete_session(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user = user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    return {"user": user}
