# cybersec.md

security audit of the repo as it would stand if the hub were served on the public web.
verdict: **not safe to deploy as-is.** auth core is solid, but what's behind the auth is full of holes, and registration is open — so "authenticated attacker" = anyone. fix criticals 1–4 before anything leaves localhost/LAN.

## critical

### 1. open remote desktop to agent containers (no auth at all)
- `INT3RF4CE/back/container.py:46-48,155`
- x11vnc runs with `-nopw`, websockify has no auth, containers publish `-p {port}:6080` bound to `0.0.0.0`.
- anyone port-scanning the host gets full keyboard/mouse into every agent container. no login required.
- frontend loads it as plain `http://host:port/vnc.html` (`INT3RF4CE/front/app.js:187`).
- **patch:** bind to `127.0.0.1`, proxy noVNC through the authenticated FastAPI app (or VNC password / websockify token auth).

### 2. path traversal via agent name → delete anything on the host
- `INT3RF4CE/back/server.py:227-258` — agent `name` never validated.
- `{"cmd":"delete","name":"../../../whatever"}` hits `shutil.rmtree` (`server.py:335-340`); `rename` relocates dirs anywhere (`:368-375`); `context.py:97-98` mkdirs traversal paths.
- same bug in prompt-block names: `server.py:469-479` → `INT3RF4CE/back/prompt.py:163-164` — arbitrary `.md` file write anywhere on disk.
- **patch:** allowlist regex `^[a-zA-Z0-9_-]{1,32}$` on every name, like `hub/auth/store.py:50` does for usernames.

### 3. TH0UGHTGR4PH `board_id=".."` wipes everyone's data / disk fill
- `TH0UGHTGR4PH/back/api.py:351-370` — version routes (GET/POST versions, delete, restore) never validate `board_id`.
- browsers normalize `..` away but `curl --path-as-is` / `requests` send it raw.
- `save_version(user, "..")` (`storage.py:111`) copies the entire `data/TH0UGHTGR4PH/` tree into `versions/version_N` — repeatable unbounded disk fill.
- `restore_version(user, "..", ...)` (`storage.py:127`) `rmtree`s everything except `versions/` — any registered user destroys all users' data.
- **patch:** run the existing `validate_title` on `board_id` in every route that takes it.

### 4. agent file tools escape the docker sandbox onto the host
- `INT3RF4CE/back/agent.py:197-236` — `READ`/`WRITE`/`EDIT` resolve `workspace / file` with no `..` check.
- the LLM (or anything that prompt-injects it — a webpage it browses, a repo it clones) can `READ ../../../../.env` (MOONSHOT_API_KEY) or `WRITE` over any repo `.py` → RCE.
- chained with `torch.load` pickle deserialization at `INT3RF4CE/back/context.py:378` (plant `kv_cache.pt` → RCE on next agent load).
- **patch:** `path.resolve().is_relative_to(workspace.resolve())` on every file op; `torch.load(..., weights_only=True)`.

## high

### 5. plain HTTP + session cookie without `Secure`
- `hub/auth/routes.py:27-28` (comment admits it), `hub/back/app.py:64` binds `0.0.0.0` no TLS.
- public web → session tokens and passwords sniffable / MITM-able. everything above becomes attacker-usable.
- also `uvicorn.run(..., reload=True)` in the prod entrypoint (`app.py:89`) — dev mode in prod; restarts wipe in-memory rate-limit state.
- **patch:** TLS-terminating proxy, `secure=True`, drop reload.

### 6. stored XSS in MarkdownEditor
- `hub/components/MarkdownEditor/MarkdownEditor.js:43` (`html: true`) + `:108` (`preview.innerHTML`).
- wikilink renderer interpolates `title`/`id` unescaped (`:133-139`): `[[x"><img src=x onerror=alert(1)>]]` injects script.
- executes in site origin → can call `/auth/*` and act as the victim. becomes a worm once TH0UGHTGR4PH goes multi-user/social.
- **patch:** DOMPurify the output (or `html: false`), escape wikilink title.

### 7. unbounded resource burn by any registered user
- open registration (`hub/auth/routes.py:31`), no per-user agent cap.
- each agent spawns a `--gpus all` container with no `--memory`/CPU limits (`container.py:149-158`) and burns paid Kimi API tokens (`server.py:176-199`).
- TH0UGHTGR4PH write endpoints also have no size/rate limits (`api.py:281` etc.) → disk fill.
- **patch:** per-user agent limit, container `--memory`/CPU limits, request body-size caps, maybe invite-only registration.

## medium

- **weak password floor** — `MIN_PASSWORD_LEN = 4` (`hub/auth/store.py:26`). brute-forceable from rotating IPs; trivially crackable if `users.json` leaks.
- **per-IP in-memory rate limiter** — `hub/auth/routes.py:12-23`. bypassed by IP rotation (IPv6/botnet), `_attempts` dict never pruned (slow memory DoS), resets on restart. behind a proxy all users share one IP → self-DoS. limit by username+IP, bound the dict.
- **no WebSocket Origin check** — `INT3RF4CE/back/server.py:202-216`. SameSite=Lax mostly covers it; add an origin allowlist anyway.
- **unlimited account creation + unbounded request bodies** — `hub/auth/routes.py:31-44`. successful registrations never count against the rate limit; no body-size cap → CPU (scrypt) and disk hammering.
- **containers as root, `--gpus all`, chromium `--no-sandbox`** — `container.py:153`, `docker_build/Dockerfile:81`. moderate alone; bad combined with #1.
- **username enumeration** — `hub/auth/store.py:66-69` timing (instant return for unknown users vs scrypt for real ones), register echoes "username taken".

## low

- session tokens stored plaintext in `data/auth/sessions.json` — any future file-read bug = instant session hijack. hash tokens at rest.
- stored self-XSS via agent/prompt names in `INT3RF4CE/front/app.js:133-141,313-316` (innerHTML) — use `textContent`.
- full conversation payload logged on Kimi API errors — `INT3RF4CE/back/models/kimi.py:87-88` → leaks chat content into `logs/app.log` (key not logged, good).
- FastAPI `/docs` + `/openapi.json` enabled on hub and sub-apps — minor info disclosure.
- bare `assert` validation in `TH0UGHTGR4PH/back/api.py` (e.g. `:180,204`) — 500s instead of 4xx, gone under `python -O`.
- `data/auth/users.json` is 0664 — `chmod 600`.
- docker-name regex injection — `INT3RF4CE/back/server.py:100` (`-f name=^{docker_name}$` with unsanitized name). cosmetic.
- `build_docker.sh` — infinite retry loop, unbounded `build.log`. babysit it.
- `docker_build/Dockerfile` — tsinghua pip mirror with `PIP_TRUSTED_HOST`. mild supply-chain note.
- attribute-interpolated innerHTML in `hub/components/TechnoParadisalComponents.js:15-27,45-55` — static data today, DOM-XSS sink if ever fed user data. AuthBox is safe only because usernames are charset-restricted — keep that invariant.

## what's fine (don't touch)

- **auth core** (`hub/auth/store.py`): scrypt w/ OWASP params + per-user salt, `compare_digest`, 256-bit session tokens from `secrets`, 30-day expiry + pruning, HttpOnly + SameSite=Lax (CSRF largely covered), atomic JSON writes.
- **no `shell=True`** anywhere; all subprocess calls use list form.
- **no permissive CORS** middleware; static mounts only expose intended dirs (no `.git`/`venv`/`data` leak); Starlette handles static traversal.
- **secrets hygiene**: `.env`, `data/`, `weights/`, `INT3RF4CE/secrets` all gitignored, never committed; `MOONSHOT_API_KEY` env-only.
- **TH0UGHTGR4PH node titles** properly validated (blocks `/`, `\`, NUL, `.`, `..`) and rendered via `textContent`; `/data/{path}` endpoint correctly confined per-user (`resolve()` + `is_relative_to` + `is_file`).
- **model id whitelist** validated before use (`INT3RF4CE/back/server.py:240-242,522-524`); agents/broadcasts scoped per-user.
- no SQL, no eval, no subprocess-in-hub → whole injection classes absent.

## patch order

1. **#1** (needs no account at all)
2. **#2/#3/#4** (one allowlist regex + one `resolve()` confinement covers most of it)
3. **#5** (TLS + Secure cookie)
4. **#6** (DOMPurify)
5. **#7** (resource caps)

until 1–4 land: localhost/LAN only.
