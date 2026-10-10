'''shared test fixtures.

every test runs against a throwaway FAB_DIR, so no test ever touches the real ~/.fab, and
against cleared in-memory registries, so tests pass in any order and in one process.

most modules resolve FAB_DIR at call time through udir() and need no patching; the two that
bound it at import time, and auth's two file paths, are patched by name in fab_home.'''

import asyncio
import copy
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fab.config
from fab.corechat.back import api as corechat_api
from fab.corechat.back import websocket as corechat_ws
from fab.dockeruse.back import containers
from fab.dockeruse.back import tools as dockeruse_tools
from fab.wiresend.back import notify
from fab.config import udir
from fab.corechat.back.api import DEFAULT_MODEL_META, load_meta, save_meta
from hub.back import auth
from hub.back.app import app

PASSWORD = "pw123"

# modules that did `from fab.config import FAB_DIR` — they hold their own binding
FAB_DIR_HOLDERS = [fab.config, containers]  # [module]

# process-global state the app keeps between requests; a leftover entry would outlive the
# temp home it belongs to and make the next test see a user/agent/socket that isn't there
LIVE_REGISTRIES = [auth._attempts, corechat_api.agents, corechat_ws.clients,
                   notify.clients, containers._handles, dockeruse_tools._bg_tasks]  # [dict]


# point every store at `home` instead of the real ~/.fab, and drop the process-global state
# that belonged to the previous one. set_attr is monkeypatch.setattr under pytest and plain
# setattr for the manual e2e script, which cannot use fixtures
def point_fab_at(home: Path, set_attr):
    for module in FAB_DIR_HOLDERS:
        set_attr(module, "FAB_DIR", home)
    set_attr(auth, "USERS_PATH", home / "auth" / "users.json")
    set_attr(auth, "SESSIONS_PATH", home / "auth" / "sessions.json")
    for registry in LIVE_REGISTRIES:
        registry.clear()


@pytest.fixture
def fab_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "fab"
    point_fab_at(home, monkeypatch.setattr)
    return home


@pytest.fixture
def client(fab_home) -> TestClient:
    # entering the context manager runs the lifespan — without it no broadcaster task exists
    # and every websocket payload would sit in the queue forever
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user(client) -> str:
    register(client, "tester")
    return "tester"


# register a user and leave their session cookie on the client; returns the token so a test
# juggling two users can switch with client.cookies.set(COOKIE_NAME, token)
def register(client, username: str) -> str:
    r = client.post("/auth/register", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client.cookies[auth.COOKIE_NAME]


# an agent as it exists ON DISK, without the live run() task. create_agent needs a running
# event loop to spawn that task, and the lifecycle tests are about the stored state — the
# real create path is covered through the websocket `create` command
def make_agent(user: str, name: str, created: float = 0.0):
    (udir(user) / "agents" / name).mkdir(parents=True)
    meta = load_meta(user)
    meta[name] = {"created": created, "pinned": False, **DEFAULT_MODEL_META}
    save_meta(user, meta)


# every path under the fab home whose name or contents mentions `name`. the point is that
# no module has to register itself: a new store that keys by agent name shows up here the
# moment someone forgets to teach it about rename or delete
def stores_mentioning(home: Path, name: str) -> list:
    hits = []  # [str] — paths relative to the fab home
    for path in home.rglob("*"):
        rel = str(path.relative_to(home))
        if name in rel or (path.is_file() and name in path.read_text(errors="replace")):
            hits.append(rel)
    return sorted(hits)


# ---- websockets ----

# a bare receive_text() blocks forever when the server never answers, turning one broken
# assertion into a hung suite — every receive in these tests goes through here
def _recv_raw(ws, timeout: float) -> dict | None:
    box = {}  # {"m": str} — filled by the reader thread if a message lands in time

    def read():
        try:
            box["m"] = ws.receive_text()
        except Exception:
            pass  # the socket closed, or the test moved on — both simply mean "no message"

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    return json.loads(box["m"]) if "m" in box else None


def recv(ws, timeout: float = 5) -> dict:
    msg = _recv_raw(ws, timeout)
    assert msg is not None, f"no websocket message within {timeout}s"
    return msg


# payloads interleave (status, agents, messages), so tests wait for the one they mean
def recv_until(ws, pred, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = _recv_raw(ws, max(0.5, deadline - time.monotonic()))
        if msg is None:
            break
        if pred(msg):
            return msg
    raise AssertionError("no websocket message matched the predicate")


# every mutating corechat command answers with a fresh agents payload — send one and
# return that payload, skipping the status/messages traffic that interleaves with it
def send_cmd(ws, **cmd) -> dict:
    ws.send_json(cmd)
    return recv_until(ws, lambda m: m.get("type") == "agents")


# nothing should arrive — used to prove a broadcast stayed scoped to the other user
def recv_nothing(ws, timeout: float = 1):
    msg = _recv_raw(ws, timeout)
    assert msg is None, f"expected silence, got {msg}"


# ---- agent stand-in ----

class StubAgent:
    '''the whole surface a tool handler touches: who it is, its inbox, its wake event.
    tool tests want none of the turn loop, and a real Agent drags a model server with it.'''

    def __init__(self, user: str, name: str):
        self.user = user
        self.name = name
        self.inbox = []                 # [dict] — messages a tool dropped for the next turn
        self.wake = asyncio.Event()

    def deposit(self, tool_name: str, result: str):
        self.inbox.append(user_msg(f"[tool result] {tool_name}: {result}"))
        self.wake.set()


# ---- model stand-in ----

class FakeModelServer:
    '''stands in for a provider: hands back queued replies and records what it was asked,
    so the whole core loop runs with no network, no key and no cost.'''

    def __init__(self):
        self.replies = []       # [dict] — assistant messages, popped in order
        self.calls = []         # [(context, tools)] — a deep copy of what each call saw
        self.error = None       # an exception to raise instead of replying

    async def call(self, context: list, tools: list) -> dict:
        self.calls.append((copy.deepcopy(context), tools))
        if self.error:
            raise self.error
        return self.replies.pop(0) if self.replies else {"role": "assistant", "content": "ok"}


@pytest.fixture
def fake_model(monkeypatch) -> FakeModelServer:
    server = FakeModelServer()
    monkeypatch.setattr(corechat_api, "new_modelserver", lambda meta: server)
    return server


# ---- message builders (the universal context shapes, spelled once) ----

def user_msg(text: str) -> dict:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant_msg(content: str | None, call_ids: list | None = None,
                  name: str = "TEST", arguments: str = "{}") -> dict:
    msg = {"role": "assistant", "content": content}
    if call_ids:
        msg["tool_calls"] = [{"id": i, "type": "function",
                              "function": {"name": name, "arguments": arguments}} for i in call_ids]
    return msg


def tool_msg(call_id: str, content: str = "ok", name: str = "TEST") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


# the messages a bus queued but no socket consumed — how a unit test sees what the server
# would have pushed, without opening a websocket
def drained(bus) -> list:
    out = []  # [dict] — decoded payloads, in send order
    while not bus._queue.empty():
        out.append(json.loads(bus._queue.get_nowait()[0]))
    return out
