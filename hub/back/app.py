import logging
import sys
from pathlib import Path

from fab.config import FAB_DIR

project_root = Path.cwd()

LOG_DIR = FAB_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class LineLimitedFileHandler(logging.FileHandler):
    """FileHandler that keeps only the last `max_lines` lines of the log file."""

    def __init__(self, filename: Path, max_lines: int = 500):
        self.max_lines = max_lines
        super().__init__(filename)

    def emit(self, record):
        super().emit(record)
        with open(self.baseFilename, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > self.max_lines:
            with open(self.baseFilename, "w", encoding="utf-8") as f:
                f.writelines(lines[-self.max_lines:])


logging.basicConfig(
    # flip to DEBUG for library chatter (asyncio, httpx internals)
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        LineLimitedFileHandler(LOG_DIR / "app.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fab.corechat.back.api import app as corechat_app
from fab.corechat.back.websocket import start_broadcaster

HOST = "0.0.0.0"
PORT = 2121

hub_front = project_root / "hub" / "front"

# mounted sub-app lifespans don't run — background tasks of mounted apps start here
@asynccontextmanager
async def lifespan(app):
    start_broadcaster()
    yield

app = FastAPI(lifespan=lifespan)

# dev: force revalidation every load so stale css/js never survives an edit
@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response

# sub-app mounts land here as they're built:
# app.mount("/dockeruse", dockeruse_app)
# app.mount("/thoughtgraph", thoughtgraph_app)
# more specific mounts must come before the catch-all root mount since it matches in order of registration
app.mount("/corechat", corechat_app)
app.mount("/", StaticFiles(directory=hub_front, html=True))


if __name__ == "__main__":
    # log_config=None keeps the logging.basicConfig() setup above
    # reload=True: autoreload on code edits
    uvicorn.run("hub.back.app:app", host=HOST, port=PORT, reload=True, log_config=None)
