import logging
import logging.handlers
import sys
from pathlib import Path

from fab.config import FAB_DIR

project_root = Path.cwd()

LOG_DIR = FAB_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_BYTES = 256 * 1024   # per file; one old file is kept, so the log never exceeds 2x this

logging.basicConfig(
    # flip to DEBUG for library chatter (asyncio, httpx internals)
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        # rotation checks a cached byte offset per record and only touches the file at the
        # limit — a line-count cap means reading and rewriting the whole log on every line
        logging.handlers.RotatingFileHandler(LOG_DIR / "app.log", maxBytes=LOG_BYTES, backupCount=1),
        logging.StreamHandler(sys.stdout),
    ],
)

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from hub.back.auth import COOKIE_NAME, router as auth_router, user_for_token
from fab.corechat.back.api import app as corechat_app
from fab.corechat.back.websocket import start_broadcaster
from fab.thoughtgraph.back.api import app as thoughtgraph_app
from fab.dockeruse.back.api import app as dockeruse_app
from fab.wiresend.back.api import app as wiresend_app

HOST = "0.0.0.0"
PORT = 2121

hub_front = project_root / "hub" / "front"

# mounted sub-app lifespans don't run — background tasks of mounted apps start here
@asynccontextmanager
async def lifespan(app):
    start_broadcaster()
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)


@app.get("/login")
def login_page():
    return FileResponse(hub_front / "login.html")


# auth gate: everything needs a session except the login page, its assets, and the auth routes
# (websockets are NOT covered here — the ws endpoints check the cookie themselves)
def _public(path: str) -> bool:
    return path == "/login" or path.startswith("/auth/") or path in ("/TechnoParadisal.css", "/hub.css", "/orbital.png")

@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if _public(request.url.path):
        return await call_next(request)
    if user_for_token(request.cookies.get(COOKIE_NAME)):
        return await call_next(request)
    # browser page loads redirect to login; api calls get a plain 401
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"error": "not logged in"}, status_code=401)

# dev: force revalidation every load so stale css/js never survives an edit
@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response

# more specific mounts must come before the catch-all root mount since it matches in order of registration
app.mount("/corechat", corechat_app)
app.mount("/thoughtgraph", thoughtgraph_app)
app.mount("/dockeruse", dockeruse_app)
app.mount("/wiresend", wiresend_app)
app.mount("/", StaticFiles(directory=hub_front, html=True))


if __name__ == "__main__":
    # log_config=None keeps the logging.basicConfig() setup above
    # reload=True: autoreload on code edits
    uvicorn.run("hub.back.app:app", host=HOST, port=PORT, reload=True, log_config=None)
