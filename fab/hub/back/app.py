import logging
import sys
from pathlib import Path

project_root = Path.cwd()
sys.path.insert(0, str(project_root))

LOG_DIR = project_root / "fab" / "logs"
LOG_DIR.mkdir(exist_ok=True)


class LineLimitedFileHandler(logging.FileHandler):
    """FileHandler that keeps only the last `max_lines` lines of the log file."""

    def __init__(self, filename: str, max_lines: int = 2000, **kwargs):
        self.max_lines = max_lines
        super().__init__(filename, **kwargs)
        self._trim_to(max_lines)

    def emit(self, record):
        super().emit(record)
        self._maybe_trim()

    def _maybe_trim(self):
        try:
            with open(self.baseFilename, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if len(lines) > self.max_lines:
                self._trim_to(self.max_lines)
        except Exception:
            # never let log trimming break logging
            pass

    def _trim_to(self, keep: int):
        try:
            with open(self.baseFilename, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if len(lines) <= keep:
                return
            with open(self.baseFilename, "w", encoding="utf-8") as f:
                f.writelines(lines[-keep:])
        except Exception:
            pass


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        LineLimitedFileHandler(LOG_DIR / "app.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from fab.INT3RF4CE.back.server import app as INT3RF4CE_app
from fab.TH0UGHTGR4PH.back.api import app as TH0UGHTGR4PH_app
from mind.INT3RPV1Z.back.server import app as INT3RPV1Z_app
from fab.hub.auth.routes import router as auth_router

HOST = "0.0.0.0"
PORT = 2121
# hub front page mode: "display" = public subset (interface/chat/intvrpviz/thoughtgraph/research),
# "admin" = everything. config-level only — no frontend toggle.
HUB_MODE = "display"

hub_front = project_root / "fab" / "hub" / "front"
hub_components = project_root / "fab" / "hub" / "components"

app = FastAPI(
    # cybersec: hide /docs, /redoc and /openapi.json — a public API map makes attack-surface scouting easy
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

MAX_BODY_BYTES = 1_000_000  # 1 MB — chat file uploads exempt


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    # cybersec: reject bodies over 1 MB with 413 — huge bodies are a cheap memory/CPU DoS.
    # chat file uploads are exempt — they have their own validation.
    if "/chat/" in request.url.path and request.method == "POST":
        return await call_next(request)
    content_length = request.headers.get("content-length")
    try:
        if content_length and int(content_length) > MAX_BODY_BYTES:
            return JSONResponse({"error": "request body too large"}, status_code=413)
    except (ValueError, TypeError):
        return JSONResponse({"error": "invalid content-length header"}, status_code=400)
    return await call_next(request)


@app.middleware("http")
async def revalidate_statics(request: Request, call_next):
    # statics carry no cache-busting query params; force revalidation so code
    # edits show up on a plain refresh (ETag/Last-Modified make it a cheap 304)
    response = await call_next(request)
    ext = request.url.path.rsplit(".", 1)[-1]
    if ext in ("html", "js", "css", "json"):
        response.headers["Cache-Control"] = "no-cache"
    return response

# backend routes
app.include_router(auth_router)


@app.get("/")
def hub_index():
    # index with the configured display/admin mode baked in
    from fastapi.responses import HTMLResponse
    html = (hub_front / "index.html").read_text()
    return HTMLResponse(html.replace("<body>", f'<body data-mode="{HUB_MODE}">'))


# specific frontend apps only — no .git, venv, or source code exposed
# more specific mounts must come before the catch-all root mount
app.mount("/TH0UGHTGR4PH", TH0UGHTGR4PH_app, name="TH0UGHTGR4PH")
app.mount("/INT3RPV1Z", INT3RPV1Z_app, name="INT3RPV1Z")
app.mount("/INT3RF4CE", INT3RF4CE_app, name="INT3RF4CE")
app.mount("/components", StaticFiles(directory=hub_components), name="hub_components")
app.mount("/", StaticFiles(directory=hub_front, html=True), name="hub_front")


if __name__ == "__main__":
    # log_config=None keeps the logging.basicConfig() setup above so everything
    # (uvicorn + application) writes to fab/logs/app.log as well as stdout.
    # reload=True: autoreload on code edits. note this wipes in-memory state (rate limits, open ws, agent loops) on every save
    uvicorn.run("fab.hub.back.app:app", host=HOST, port=PORT, reload=True, log_config=None)
