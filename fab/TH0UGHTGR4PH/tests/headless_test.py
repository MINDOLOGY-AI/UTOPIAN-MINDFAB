"""Headless tests for TH0UGHTGR4PH + INT3RF4CE integration.

Part 1 (agent POV, no server): graph_actions CRUD + the agent's access-enforced
graph dispatch (CHECK_GRAPH_ACCESS / GREAD / GUPDATE / GDESTROY) + the prompt
docs block, against a throwaway user. Asserts data changes on disk.

Part 2 (REST/auth): boots the hub on a test port, registers throwaway users,
exercises the TH0UGHTGR4PH REST API (boards/nodes/content/edges/types/versions)
and the INT3RF4CE WS get/set_graph_settings flow, and per-user isolation.

All test users and their data are removed afterwards. Exits non-zero on failure.

Run from repo root: venv/bin/python -m fab.TH0UGHTGR4PH.tests.headless_test
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT))

from fab.TH0UGHTGR4PH.back import graph_actions, storage
from fab.TH0UGHTGR4PH.back.config import DATA_DIR, GRID_SIZE
from fab.INT3RF4CE.back.agent import Agent
from fab.INT3RF4CE.back.models.kimi import Kimi
from fab.INT3RF4CE.back.prompt import _prompt_docs_block, build_system_prompt

AGENT_USER = "test_tg_agent"
WEB_USER_A = "test_tg_a"
WEB_USER_B = "test_tg_b"
TEST_PORT = 2999
BASE = f"http://127.0.0.1:{TEST_PORT}"

FAILURES = []


def check(label, cond):
    if cond:
        print(f"  ok  {label}")
    else:
        print(f" FAIL {label}")
        FAILURES.append(label)


def cleanup_user(user: str):
    for base in (DATA_DIR, PROJECT_ROOT / "fab" / "data" / "INT3RF4CE"):
        d = base / user
        if d.exists():
            shutil.rmtree(d)


def cleanup_auth(user: str):
    users_path = PROJECT_ROOT / "fab" / "data" / "auth" / "users.json"
    sessions_path = PROJECT_ROOT / "fab" / "data" / "auth" / "sessions.json"
    if users_path.exists():
        users = json.loads(users_path.read_text())
        if user in users:
            del users[user]
            users_path.write_text(json.dumps(users, indent=2))
    if sessions_path.exists():
        sessions = json.loads(sessions_path.read_text())
        sessions = {t: s for t, s in sessions.items() if s.get("user") != user}
        sessions_path.write_text(json.dumps(sessions, indent=2))


def make_agent(user: str, name: str) -> Agent:
    """A chat-mode agent with no container side effects (docker only starts on start())."""
    return Agent(user, name, Kimi(model="kimi-k3"), use_container=True, novnc_port=6999, chat_mode=True)


def write_graph_settings(user: str, agent: str, settings: dict):
    specific = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE" / user / "config" / "specific" / agent
    specific.mkdir(parents=True, exist_ok=True)
    (specific / "graph.json").write_text(json.dumps(settings))


# ---------------------------------------------------------------- part 1: agent POV

def test_agent_pov():
    print("part 1: agent-POV graph actions + access enforcement")
    cleanup_user(AGENT_USER)
    storage.init_user_storage(AGENT_USER)
    board = "main"

    check("main board exists", board in storage.list_boards(AGENT_USER))
    types = storage.load_types(AGENT_USER)
    check("seeded obj types include theory/doc", "theory" in types["obj_types"] and "doc" in types["obj_types"])
    check("no agent type anymore", "agent" not in types["obj_types"])

    # [theory] -> (support) -> [code]
    theory = graph_actions.create_node(AGENT_USER, board, "ML theory", "obj", "theory")
    support = graph_actions.create_node(AGENT_USER, board, "support", "func", "support")
    code = graph_actions.create_node(AGENT_USER, board, "jump_relu.py", "obj", "code", ref="mind/SYN4P5E/algorithms/jump_relu.py")

    xs = [theory["x"], support["x"], code["x"]]
    ys = [theory["y"], support["y"], code["y"]]
    check("positions grid-aligned", all(x % GRID_SIZE == 0 and y % GRID_SIZE == 0 for x, y in zip(xs, ys)))
    check("positions distinct", len(set(zip(xs, ys))) == 3)
    check("support right of theory", support["x"] > theory["x"])

    e1 = graph_actions.link(AGENT_USER, board, theory["id"], support["id"])
    e2 = graph_actions.link(AGENT_USER, board, support["id"], code["id"])
    check("two edges created", len(storage.load_meta(AGENT_USER, board)["edges"]) == 2)

    read = graph_actions.read_node(AGENT_USER, board, support["id"])
    ins = {c["title"] for c in read["connected"] if c["direction"] == "in"}
    outs = {c["title"] for c in read["connected"] if c["direction"] == "out"}
    check("support reads theory as input", ins == {"ML theory"})
    check("support reads code as output", outs == {"jump_relu.py"})

    graph_actions.update_node(AGENT_USER, board, theory["id"], content="# ML theory\ndot products and relus", state="doing")
    check("content persisted", storage.read_content(AGENT_USER, board, theory["id"]).startswith("# ML theory"))
    meta = storage.load_meta(AGENT_USER, board)
    check("state persisted", meta["nodes"][theory["id"]]["state"] == "doing")

    moved = graph_actions.move_node(AGENT_USER, board, theory["id"], x=0, y=600)
    check("move persisted + snapped", storage.load_meta(AGENT_USER, board)["nodes"][theory["id"]]["y"] == 600)

    try:
        graph_actions.create_node(AGENT_USER, board, "bad", "obj", "not_a_type")
        check("unknown type rejected", False)
    except ValueError:
        check("unknown type rejected", True)
    try:
        graph_actions.create_node(AGENT_USER, board, "agent attempt", "agent", "agent")
        check("agent kind rejected", False)
    except ValueError:
        check("agent kind rejected", True)

    # ---- access-enforced dispatch (the agent's actual command path) ----
    agent = make_agent(AGENT_USER, "agent_x")
    write_graph_settings(AGENT_USER, "agent_x", {
        "prompt_docs": [{"board": board, "id": theory["id"]}],
        "read": [{"board": board, "id": code["id"]}],
        "write": [{"board": board, "id": theory["id"]}],
    })

    out = agent._graph_dispatch("CHECK_GRAPH_ACCESS", {})
    check("CHECK_GRAPH_ACCESS lists board", f'"board": "{board}"' in out)
    check("CHECK_GRAPH_ACCESS: write implies read", "ML theory" in out and "jump_relu.py" in out)
    check("CHECK_GRAPH_ACCESS prints node_type + state", '"node_type": "theory"' in out and '"state":' in out)

    out = agent._graph_dispatch("GREAD", {"node": code["id"]})
    check("GREAD allowed on read-listed node", "jump_relu.py" in out)
    out = agent._graph_dispatch("GREAD", {"node": support["id"]})
    check("GREAD rejected on unlisted node", "no read access" in out)

    out = agent._graph_dispatch("GUPDATE", {"node": theory["id"], "state": "done"})
    check("GUPDATE allowed on write-listed node", "updated" in out)
    check("state done persisted", storage.load_meta(AGENT_USER, board)["nodes"][theory["id"]]["state"] == "done")
    out = agent._graph_dispatch("GEDIT", {"node": code["id"], "old": "x", "new": "y", "which": "0"})
    check("GEDIT rejected on read-only node", "no write access" in out)

    out = agent._graph_dispatch("GEDIT", {"node": theory["id"], "old": "dot products", "new": "matmuls", "which": "0"})
    check("GEDIT allowed on write-listed node", "done" in out)
    check("GEDIT changed the content", "matmuls and relus" in storage.read_content(AGENT_USER, board, theory["id"]))
    out = agent._graph_dispatch("GEDIT", {"node": theory["id"], "old": "not present", "new": "y", "which": "0"})
    check("GEDIT reports text not found", "text not found" in out)

    out = agent._graph_dispatch("GDESTROY", {"node": theory["id"]})
    check("GDESTROY gone (unknown command)", "unknown graph command" in out)
    out = agent._graph_dispatch("GCREATE", {"title": "x", "kind": "obj", "node_type": "doc"})
    check("GCREATE unknown to agents (no self-producing nodes)", "unknown graph command" in out)

    # prompt docs block: only prompt_docs content is injected, not access lists
    block = _prompt_docs_block(AGENT_USER, "agent_x")
    check("prompt docs block exists", block is not None)
    check("prompt docs block has doc content", "matmuls and relus" in block)
    check("prompt docs block has no access lists", "READ access" not in block and "WRITE access" not in block)
    prompt = build_system_prompt(AGENT_USER, "agent_x")
    check("system prompt includes prompt docs", "matmuls and relus" in prompt)

    res = graph_actions.destroy_node(AGENT_USER, board, theory["id"])
    meta = storage.load_meta(AGENT_USER, board)
    check("destroy removes node", theory["id"] not in meta["nodes"])
    check("edges to destroyed nodes gone", all(e["source"] in meta["nodes"] and e["target"] in meta["nodes"] for e in meta["edges"].values()))

    cleanup_user(AGENT_USER)


# ---------------------------------------------------------------- part 2: REST + WS

def wait_for_server(proc, timeout=30):
    import httpx
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            raise RuntimeError("server exited early")
        try:
            r = httpx.get(f"{BASE}/auth/me", timeout=1)
            if r.status_code in (200, 401):
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError("server did not come up")


def test_rest_ws():
    print("part 2: REST API + WS graph settings + isolation")
    import httpx
    import websockets

    for u in (WEB_USER_A, WEB_USER_B):
        cleanup_user(u)
        cleanup_auth(u)

    server = subprocess.Popen(
        [str(PROJECT_ROOT / "venv" / "bin" / "python"), "-m", "uvicorn",
         "fab.hub.back.app:app", "--host", "127.0.0.1", "--port", str(TEST_PORT)],
        cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(server)
        a = httpx.Client(base_url=BASE, timeout=10)
        b = httpx.Client(base_url=BASE, timeout=10)
        ra = a.post("/auth/register", json={"username": WEB_USER_A, "password": "testpass123"})
        rb = b.post("/auth/register", json={"username": WEB_USER_B, "password": "testpass123"})
        check("register A", ra.status_code == 200)
        check("register B", rb.status_code == 200)

        check("unauth board rejected", httpx.get(f"{BASE}/TH0UGHTGR4PH/boards").status_code == 401)
        boards = a.get("/TH0UGHTGR4PH/boards").json()["boards"]
        check("A gets main board", boards == ["main"])

        obj = a.post("/TH0UGHTGR4PH/boards/main/nodes", json={"title": "theory A", "kind": "obj", "node_type": "theory"}).json()
        func = a.post("/TH0UGHTGR4PH/boards/main/nodes", json={"title": "support", "kind": "func", "node_type": "support"}).json()
        check("REST create obj", obj["kind"] == "obj" and obj["node_type"] == "theory")
        check("REST autoplaced", func["x"] > obj["x"] or func["y"] != obj["y"])

        edge = a.post("/TH0UGHTGR4PH/boards/main/edges", json={"source": obj["id"], "target": func["id"]}).json()
        graph = a.get("/TH0UGHTGR4PH/boards/main/graph").json()
        check("REST edge in graph", edge["id"] in graph["edges"])

        a.put(f"/TH0UGHTGR4PH/boards/main/nodes/{obj['id']}/content", json={"content": "hello content"})
        content = a.get(f"/TH0UGHTGR4PH/boards/main/nodes/{obj['id']}/content").json()["content"]
        check("REST content roundtrip", content == "hello content")

        upd = a.put(f"/TH0UGHTGR4PH/boards/main/nodes/{obj['id']}", json={"state": "doing", "x": 400, "y": 200}).json()
        check("REST update state+pos", upd["state"] == "doing" and upd["x"] == 400)

        types = a.get("/TH0UGHTGR4PH/types").json()
        types["obj_types"]["custom_type"] = {"color": "#ABCDEF"}
        a.put("/TH0UGHTGR4PH/types", json=types)
        check("REST types roundtrip", "custom_type" in a.get("/TH0UGHTGR4PH/types").json()["obj_types"])

        # versions
        v = a.post("/TH0UGHTGR4PH/boards/main/versions").json()["name"]
        a.put(f"/TH0UGHTGR4PH/boards/main/nodes/{obj['id']}", json={"title": "renamed theory"})
        check("version saved", v in a.get("/TH0UGHTGR4PH/boards/main/versions").json()["versions"])
        a.post(f"/TH0UGHTGR4PH/boards/main/versions/{v}/restore")
        restored = a.get("/TH0UGHTGR4PH/boards/main/graph").json()
        check("version restore brings back title", restored["nodes"][obj["id"]]["title"] == "theory A")

        # templates are gone
        check("templates endpoint gone", a.get("/TH0UGHTGR4PH/templates").status_code in (404, 405))

        # WS: create agent (no docker side effects) + graph settings roundtrip
        async def ws_flow():
            import asyncio
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                first = json.loads(await ws.recv())
                assert first["type"] == "agents"
                await ws.send(json.dumps({"cmd": "create", "name": "agent_a"}))
                await ws.send(json.dumps({"cmd": "set_graph_settings", "name": "agent_a", "settings": {
                    "prompt_docs": [{"board": "main", "id": obj["id"]}],
                    "read": [{"board": "main", "id": func["id"]}],
                    "write": [{"board": "main", "id": obj["id"]}],
                }}))
                await ws.send(json.dumps({"cmd": "get_graph_settings", "name": "agent_a"}))
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "graph_settings" and msg.get("settings"):
                        return msg["settings"]
                return None

        import asyncio
        settings = asyncio.run(ws_flow())
        check("WS graph settings roundtrip", settings
              and settings["prompt_docs"] == [{"board": "main", "id": obj["id"]}]
              and settings["write"] == [{"board": "main", "id": obj["id"]}])
        graph_json = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE" / WEB_USER_A / "config" / "specific" / "agent_a" / "graph.json"
        check("graph.json written on disk", graph_json.exists())

        async def ws_bad_settings():
            import asyncio
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "set_graph_settings", "name": "agent_a", "settings": {
                    "prompt_docs": [], "read": [], "write": [{"board": "main", "id": "deadbeef"}],
                }}))
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "error":
                        return msg["msg"]
                return None

        check("WS rejects nodes not on board", "not on board" in (asyncio.run(ws_bad_settings()) or ""))

        # settings files: save / list / load roundtrip
        async def ws_files():
            import asyncio
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "save_settings_file", "name": "agent_a", "file_name": "preset1"}))
                await ws.send(json.dumps({"cmd": "list_settings_files"}))
                files = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "settings_files":
                        files = msg["files"]
                        break
                # wipe current settings, then load the preset back
                await ws.send(json.dumps({"cmd": "set_graph_settings", "name": "agent_a", "settings": {"prompt_docs": [], "read": [], "write": []}}))
                # drain the wipe's graph_settings response first
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "graph_settings":
                        break
                await ws.send(json.dumps({"cmd": "load_settings_file", "name": "agent_a", "file_name": "preset1"}))
                loaded = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "graph_settings" and msg.get("settings", {}).get("prompt_docs"):
                        loaded = msg["settings"]
                        break
                return files, loaded

        files, loaded = asyncio.run(ws_files())
        check("settings file saved + listed", files and "preset1" in files)
        check("settings file loads back", loaded and loaded.get("prompt_docs") == [{"board": "main", "id": obj["id"]}])

        # isolation
        check("B boards are its own", b.get("/TH0UGHTGR4PH/boards").json()["boards"] == ["main"])
        b_graph = b.get("/TH0UGHTGR4PH/boards/main/graph").json()
        check("B graph empty (isolation)", b_graph["nodes"] == {} and b_graph["edges"] == {})
        check("B types are default (isolation)", "custom_type" not in b.get("/TH0UGHTGR4PH/types").json()["obj_types"])

        a.close()
        b.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        for u in (WEB_USER_A, WEB_USER_B):
            cleanup_user(u)
            cleanup_auth(u)


def main():
    test_agent_pov()
    test_rest_ws()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
