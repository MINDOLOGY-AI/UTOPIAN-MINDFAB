"""Headless tests for F4B + INT3RF4CE graph integration.

Part 1 (agent POV, no server): run graph_actions exactly as agent.py's graph
dispatch does, against a throwaway user, and assert data changes on disk.
Also covers autoplacement sanity and the prompt context wrapper.

Part 2 (REST/auth): boots the hub on a test port, registers throwaway users,
exercises the F4B REST API (boards/nodes/content/edges/types/templates/versions),
the INT3RF4CE WS attach/detach flow, and per-user isolation.

All test users and their data are removed afterwards. Exits non-zero on failure.

Run from repo root: venv/bin/python -m fab.F4B.tests.headless_test
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from fab.F4B.back import graph_actions, storage
from fab.F4B.back.config import DATA_DIR, GRID_SIZE
from fab.INT3RF4CE.back.prompt import _graph_context_block

AGENT_USER = "test_f4b_agent"
WEB_USER_A = "test_f4b_a"
WEB_USER_B = "test_f4b_b"
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


# ---------------------------------------------------------------- part 1: agent POV

def test_agent_pov():
    print("part 1: agent-POV graph actions")
    cleanup_user(AGENT_USER)
    storage.init_user_storage(AGENT_USER)
    board = "main"

    check("main board exists", board in storage.list_boards(AGENT_USER))
    types = storage.load_types(AGENT_USER)
    check("seeded obj types include theory/agent", "theory" in types["obj_types"] and "agent" in types["obj_types"])
    check("seeded func types include support", "support" in types["func_types"])

    # build the user's example: [theory] -> (support) -> [code], [agent] -> (support)
    theory = graph_actions.create_node(AGENT_USER, board, "ML theory", "obj", "theory")
    support = graph_actions.create_node(AGENT_USER, board, "support it", "func", "support")
    code = graph_actions.create_node(AGENT_USER, board, "jump_relu.py", "obj", "code", ref="mind/SYN4P5E/algorithms/jump_relu.py")
    agent = graph_actions.create_node(AGENT_USER, board, "agent_1", "obj", "agent", ref="agent_1")

    # autoplacement: all on grid, distinct cells, left-to-right
    xs = [theory["x"], support["x"], code["x"], agent["x"]]
    ys = [theory["y"], support["y"], code["y"], agent["y"]]
    check("positions grid-aligned", all(x % GRID_SIZE == 0 and y % GRID_SIZE == 0 for x, y in zip(xs, ys)))
    check("positions distinct", len(set(zip(xs, ys))) == 4)
    check("support right of theory", support["x"] > theory["x"])

    e1 = graph_actions.link(AGENT_USER, board, theory["id"], support["id"])
    e2 = graph_actions.link(AGENT_USER, board, support["id"], code["id"])
    e3 = graph_actions.link(AGENT_USER, board, agent["id"], support["id"])
    check("three edges created", len(storage.load_meta(AGENT_USER, board)["edges"]) == 3)

    read = graph_actions.read_node(AGENT_USER, board, support["id"])
    ins = {c["title"] for c in read["connected"] if c["direction"] == "in"}
    outs = {c["title"] for c in read["connected"] if c["direction"] == "out"}
    check("support reads theory+agent as inputs", ins == {"ML theory", "agent_1"})
    check("support reads code as output", outs == {"jump_relu.py"})

    # title resolution + ambiguity
    read_by_title = graph_actions.read_node(AGENT_USER, board, "ML theory")
    check("read by title resolves id", read_by_title["node"]["id"] == theory["id"])
    try:
        graph_actions.read_node(AGENT_USER, board, "nonexistent")
        check("missing node raises", False)
    except ValueError:
        check("missing node raises", True)

    # content write/read
    graph_actions.update_node(AGENT_USER, board, theory["id"], content="# ML theory\ndot products and relus")
    check("content persisted", storage.read_content(AGENT_USER, board, theory["id"]).startswith("# ML theory"))

    # state + move
    graph_actions.update_node(AGENT_USER, board, theory["id"], state="doing")
    moved = graph_actions.move_node(AGENT_USER, board, theory["id"], x=0, y=600)
    meta = storage.load_meta(AGENT_USER, board)
    check("state persisted", meta["nodes"][theory["id"]]["state"] == "doing")
    check("move persisted + snapped", meta["nodes"][theory["id"]]["y"] == 600)

    # folder parenting
    folder = graph_actions.create_node(AGENT_USER, board, "research", "folder", "folder")
    graph_actions.move_node(AGENT_USER, board, theory["id"], parent=folder["id"])
    meta = storage.load_meta(AGENT_USER, board)
    check("parent persisted", meta["nodes"][theory["id"]]["parent"] == folder["id"])
    try:
        graph_actions.move_node(AGENT_USER, board, folder["id"], parent=theory["id"])
        check("non-folder parent rejected", False)
    except ValueError:
        check("non-folder parent rejected", True)

    # type validation
    try:
        graph_actions.create_node(AGENT_USER, board, "bad", "obj", "not_a_type")
        check("unknown type rejected", False)
    except ValueError:
        check("unknown type rejected", True)

    # unlink + list
    graph_actions.unlink(AGENT_USER, board, e3["id"])
    listing = graph_actions.list_board(AGENT_USER, board)
    check("unlink removed edge", len(storage.load_meta(AGENT_USER, board)["edges"]) == 2)
    check("list_board summarizes nodes", len(listing["nodes"]) == 5)

    # destroy cascades to folder children + edges
    res = graph_actions.destroy_node(AGENT_USER, board, folder["id"])
    meta = storage.load_meta(AGENT_USER, board)
    check("destroy cascades into folder", theory["id"] in res["deleted"])
    check("destroyed nodes gone", theory["id"] not in meta["nodes"] and folder["id"] not in meta["nodes"])
    check("edges to destroyed nodes gone", all(e["source"] in meta["nodes"] and e["target"] in meta["nodes"] for e in meta["edges"].values()))
    check("content file removed", not (DATA_DIR / AGENT_USER / board / "content" / f"{theory['id']}.md").exists())

    # context wrapper: attach agent_1's node and verify the block names func + inputs
    agent2 = graph_actions.create_node(AGENT_USER, board, "agent_1", "obj", "agent", ref="agent_1")
    theory2 = graph_actions.create_node(AGENT_USER, board, "theory B", "obj", "theory")
    graph_actions.update_node(AGENT_USER, board, theory2["id"], content="theory B content here")
    support2 = graph_actions.create_node(AGENT_USER, board, "support B", "func", "support")
    graph_actions.link(AGENT_USER, board, agent2["id"], support2["id"])
    graph_actions.link(AGENT_USER, board, theory2["id"], support2["id"])
    specific = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE" / AGENT_USER / "config" / "specific" / "agent_1"
    specific.mkdir(parents=True, exist_ok=True)
    (specific / "graph.json").write_text(json.dumps({"board": board, "node": agent2["id"]}))
    block = _graph_context_block(AGENT_USER, "agent_1")
    check("context block exists", block is not None)
    check("context block names the func", "support B" in block)
    check("context block includes input content", "theory B content here" in block)
    check("context block documents G* commands", "GCREATE" in block)

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
    print("part 2: REST API + WS attach + isolation")
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

        check("unauth F4B rejected", httpx.get(f"{BASE}/F4B/boards").status_code == 401)
        boards = a.get("/F4B/boards").json()["boards"]
        check("A gets main board", boards == ["main"])

        obj = a.post("/F4B/boards/main/nodes", json={"title": "theory A", "kind": "obj", "node_type": "theory"}).json()
        func = a.post("/F4B/boards/main/nodes", json={"title": "support A", "kind": "func", "node_type": "support"}).json()
        check("REST create obj", obj["kind"] == "obj" and obj["node_type"] == "theory")
        check("REST autoplaced", func["x"] > obj["x"] or func["y"] != obj["y"])

        edge = a.post("/F4B/boards/main/edges", json={"source": obj["id"], "target": func["id"]}).json()
        graph = a.get("/F4B/boards/main/graph").json()
        check("REST edge in graph", edge["id"] in graph["edges"])

        a.put(f"/F4B/boards/main/nodes/{obj['id']}/content", json={"content": "hello content"})
        content = a.get(f"/F4B/boards/main/nodes/{obj['id']}/content").json()["content"]
        check("REST content roundtrip", content == "hello content")

        upd = a.put(f"/F4B/boards/main/nodes/{obj['id']}", json={"state": "doing", "x": 400, "y": 200}).json()
        check("REST update state+pos", upd["state"] == "doing" and upd["x"] == 400)

        types = a.get("/F4B/types").json()
        types["obj_types"]["custom_type"] = {"color": "#ABCDEF"}
        a.put("/F4B/types", json=types)
        check("REST types roundtrip", "custom_type" in a.get("/F4B/types").json()["obj_types"])
        custom = a.post("/F4B/boards/main/nodes", json={"title": "custom", "kind": "obj", "node_type": "custom_type"})
        check("custom type usable", custom.status_code == 200)

        # templates (workflows)
        a.put(f"/F4B/boards/main/nodes/{obj['id']}", json={"x": 0, "y": 0})
        a.put(f"/F4B/boards/main/nodes/{func['id']}", json={"x": 200, "y": 0})
        tpl = a.post("/F4B/templates", json={
            "name": "wf1",
            "nodes": [{"key": obj["id"], "title": "theory A", "kind": "obj", "node_type": "theory",
                        "state": None, "ref": None, "settings": None, "rel_x": 0, "rel_y": 0,
                        "width": 560, "height": 360, "parent_key": None}],
            "edges": [],
        })
        check("template save", tpl.status_code == 200)
        check("template listed", "wf1" in a.get("/F4B/templates").json()["templates"])
        check("template delete", a.delete("/F4B/templates/wf1").status_code == 200)

        # versions
        v = a.post("/F4B/boards/main/versions").json()["name"]
        a.put(f"/F4B/boards/main/nodes/{obj['id']}", json={"title": "renamed theory"})
        check("version saved", v in a.get("/F4B/boards/main/versions").json()["versions"])
        a.post(f"/F4B/boards/main/versions/{v}/restore")
        restored = a.get("/F4B/boards/main/graph").json()
        check("version restore brings back title", restored["nodes"][obj["id"]]["title"] == "theory A")

        # WS: create agent (no docker side effects — build only happens on start)
        agent_node = a.post("/F4B/boards/main/nodes", json={
            "title": "agent_a", "kind": "obj", "node_type": "agent", "ref": "agent_a",
        }).json()

        async def ws_flow():
            import asyncio
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                first = json.loads(await ws.recv())
                assert first["type"] == "agents"
                await ws.send(json.dumps({"cmd": "create", "name": "agent_a"}))
                await ws.send(json.dumps({"cmd": "attach_graph", "name": "agent_a", "board": "main", "node": agent_node["id"]}))
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "agents" and msg["agents"].get("agent_a", {}).get("graph"):
                        return msg["agents"]["agent_a"]["graph"]
                return None

        import asyncio
        graph_info = asyncio.run(ws_flow())
        check("WS attach_graph persisted", graph_info == {"board": "main", "node": agent_node["id"]})
        graph_json = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE" / WEB_USER_A / "config" / "specific" / "agent_a" / "graph.json"
        check("graph.json written on disk", graph_json.exists())

        async def ws_detach():
            import asyncio
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "detach_graph", "name": "agent_a"}))
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "agents" and msg["agents"].get("agent_a", {}).get("graph") is None:
                        return True
                return False

        check("WS detach_graph", asyncio.run(ws_detach()))
        check("graph.json removed", not graph_json.exists())

        # attach rejects non-agent nodes
        async def ws_bad_attach():
            import asyncio
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "attach_graph", "name": "agent_a", "board": "main", "node": obj["id"]}))
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "error":
                        return msg["msg"]
                return None

        check("attach non-agent node rejected", "not an agent" in (asyncio.run(ws_bad_attach()) or ""))

        # isolation: B sees only its own world
        check("B boards are its own", b.get("/F4B/boards").json()["boards"] == ["main"])
        b_graph = b.get("/F4B/boards/main/graph").json()
        check("B graph empty (isolation)", b_graph["nodes"] == {} and b_graph["edges"] == {})
        check("B types are default (isolation)", "custom_type" not in b.get("/F4B/types").json()["obj_types"])

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
