import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from interp_journey.function_approximator.back.router import router as function_approximator_router
from thoughtGrvph.back.api import app as thoughtgrvph_app
from intvrface.back.server import app as intvrface_app

HOST = "0.0.0.0"
PORT = 2121

hub_front = project_root / "hub" / "front"
hub_components = project_root / "hub" / "components"
fa_front = project_root / "interp_journey" / "function_approximator" / "front"

app = FastAPI()

# backend routes
app.include_router(function_approximator_router, prefix="/api")

# specific frontend apps only — no .git, venv, or source code exposed
# more specific mounts must come before the catch-all root mount
app.mount("/thoughtgrvph", thoughtgrvph_app, name="thoughtgrvph")
app.mount("/intvrface", intvrface_app, name="intvrface")
app.mount("/interp_journey/function_approximator/front", StaticFiles(directory=fa_front, html=True), name="fa_front")
app.mount("/components", StaticFiles(directory=hub_components), name="hub_components")
app.mount("/", StaticFiles(directory=hub_front, html=True), name="hub_front")


if __name__ == "__main__":
    uvicorn.run("hub.back.app:app", host=HOST, port=PORT, reload=True)
