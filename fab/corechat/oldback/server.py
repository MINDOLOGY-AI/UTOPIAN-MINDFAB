'''corechat api + static frontend. mounted at /corechat by the hub.'''

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fab.corechat.oldback import agent as agent_loop
from fab.corechat.oldback import context

app = FastAPI()


class Turn(BaseModel):
    agent: str
    text: str


@app.get("/api/history")
def history(agent: str):
    return {"messages": context.load(agent)["messages"]}


@app.post("/api/turn")
async def turn(t: Turn):
    return {"messages": await agent_loop.turn(t.agent, t.text)}


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "front", html=True))
