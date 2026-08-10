"""HTTP routes for site-wide auth. Mounted at /auth by hub/back/app.py."""

import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from fab.hub.auth import store
from fab.hub.auth.store import COOKIE_NAME

# login/register attempts per (username, ip), in-memory (resets on restart — fine for now)
MAX_ATTEMPTS = 20
ATTEMPT_WINDOW = 300  # seconds
# (username, ip), [timesteps]  
_attempts: dict[tuple[str, str], list[float]] = {}

router = APIRouter(prefix="/auth")


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
    response.set_cookie(COOKIE_NAME, token, max_age=store.SESSION_TTL, httponly=True, samesite="lax", path="/", secure=secure)


@router.post("/register")
async def register(request: Request, response: Response):
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
        store.create_user(username, body.get("password", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _set_session_cookie(request, response, store.create_session(username))
    return {"user": username}


@router.post("/login")
async def login(request: Request, response: Response):
    ip = request.client.host
    body = await request.json()
    username = body.get("username", "").strip()
    # cybersec: key the limit on (username, ip) so one user's brute-force doesn't lock out others on the same IP
    key = (username, ip)
    if _rate_limited(key):
        return JSONResponse({"error": "too many attempts, try again later"}, status_code=429)
    if not store.verify_user(username, body.get("password", "")):
        _record_attempt(key)
        return JSONResponse({"error": "wrong username or password"}, status_code=401)
    _set_session_cookie(request, response, store.create_session(username))
    return {"user": username}


@router.post("/logout")
async def logout(request: Request, response: Response):
    store.delete_session(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user = store.user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    return {"user": user}
