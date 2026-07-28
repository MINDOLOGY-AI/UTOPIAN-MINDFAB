import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
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

from mind.interp_journey.function_approximator.back.router import router as function_approximator_router
from fab.TH0UGHTGR4PH.back.api import app as TH0UGHTGR4PH_app
from fab.INT3RF4CE.back.server import app as INT3RF4CE_app
from fab.F4B.back.api import app as F4B_app
from fab.hub.auth.routes import router as auth_router

HOST = "0.0.0.0"
PORT = 2121

hub_front = project_root / "fab" / "hub" / "front"
hub_components = project_root / "fab" / "hub" / "components"
fa_front = project_root / "mind" / "interp_journey" / "function_approximator" / "front"

app = FastAPI(
    # cybersec: hide /docs, /redoc and /openapi.json — a public API map makes attack-surface scouting easy
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

MAX_BODY_BYTES = 1_000_000  # 1 MB — the site only ever sends small JSON


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    # cybersec: reject bodies over 1 MB with 413 — huge bodies are a cheap memory/CPU DoS
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return JSONResponse({"error": "request body too large"}, status_code=413)
    return await call_next(request)

# backend routes
app.include_router(function_approximator_router, prefix="/api")
app.include_router(auth_router)

# specific frontend apps only — no .git, venv, or source code exposed
# more specific mounts must come before the catch-all root mount
app.mount("/TH0UGHTGR4PH", TH0UGHTGR4PH_app, name="TH0UGHTGR4PH")
app.mount("/INT3RF4CE", INT3RF4CE_app, name="INT3RF4CE")
app.mount("/F4B", F4B_app, name="F4B")
app.mount("/interp_journey/function_approximator/front", StaticFiles(directory=fa_front, html=True), name="fa_front")
app.mount("/components", StaticFiles(directory=hub_components), name="hub_components")
app.mount("/", StaticFiles(directory=hub_front, html=True), name="hub_front")


if __name__ == "__main__":
    # log_config=None keeps the logging.basicConfig() setup above so everything
    # (uvicorn + application) writes to fab/logs/app.log as well as stdout.
    # reload=True: autoreload on code edits. note this wipes in-memory state (rate limits, open ws, agent loops) on every save
    uvicorn.run("fab.hub.back.app:app", host=HOST, port=PORT, reload=True, log_config=None)
