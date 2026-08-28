'''end-to-end: a real user's day across all four modules, one account, real docker, one real model call.
run from repo root: venv/bin/python -m hub.test.test_e2e'''

import json
import shutil
import threading
import time

from fastapi.testclient import TestClient

from fab.config import FAB_DIR, udir
from hub.back.app import app
from hub.back.auth import COOKIE_NAME

USER = "tester_e2e"


def cleanup():
    shutil.rmtree(udir(USER), ignore_errors=True)
    for name in ("users.json", "sessions.json"):
        p = FAB_DIR / "auth" / name
        if p.exists():
            d = json.loads(p.read_text())
            if "users" in name:
                d.pop(USER, None)
            else:
                d = {k: v for k, v in d.items() if v.get("user") != USER}
            p.write_text(json.dumps(d))


def recv_t(ws, seconds):
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("m", ws.receive_text()), daemon=True)
    t.start()
    t.join(seconds)
    return box.get("m")


def recv_until(ws, pred, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        m = recv_t(ws, max(1, deadline - time.time()))
        if m is None:
            return None
        d = json.loads(m)
        if pred(d):
            return d
    return None


def main():
    cleanup()
    with TestClient(app) as client:
        r = client.post("/auth/register", json={"username": USER, "password": "pw123"})
        assert r.status_code == 200, r.text

        # ---- corechat: create an agent, it shows up, a real turn answers ----
        with client.websocket_connect("/corechat/ws") as ws:
            m = recv_t(ws, 5)
            assert m and json.loads(m)["agents"] == []
            ws.send_text(json.dumps({"cmd": "create", "name": "helper"}))
            m = recv_t(ws, 5)
            assert m
            p = json.loads(m)
            assert p["agents"][0]["name"] == "helper" and p["agents"][0]["agent_mode"] is False
            assert (udir(USER) / "agents" / "helper").exists()

            # tests run on deepseek — the moonshot key rate-limits too much for a test suite
            ws.send_text(json.dumps({"cmd": "set_model", "name": "helper",
                                     "model_server_name": "deepseek",
                                     "model_name": "deepseek-v4-flash-vision-exp"}))
            m = recv_t(ws, 5)
            assert m and json.loads(m)["agents"][0]["model_server_name"] == "deepseek"

            ws.send_text(json.dumps({"cmd": "chat", "name": "helper",
                                     "content": [{"type": "text", "text": "reply with exactly: pong"}]}))
            d = recv_until(ws, lambda m: m.get("type") == "messages"
                           and m["messages"][-1]["role"] == "assistant")
            assert d, "no reply arrived"
            assert "pong" in d["messages"][-1]["content"], d["messages"][-1].get("content")
            print("corechat: agent created, real turn answered")

            # ---- thoughtgraph: make a doc, grant the agent write, the agent GREADs it ----
            node = client.post("/thoughtgraph/boards/main/nodes", json={"title": "mission", "kind": "doc"}).json()
            nid = node["id"]
            client.put(f"/thoughtgraph/boards/main/nodes/{nid}/content",
                       json={"content": "the mission is testing"})
            client.put("/thoughtgraph/access",
                       json={"helper": {"read": [{"board": "main", "id": nid}], "write": []}})

            # the agent's own view of the world, via its tools (no model call needed)
            from fab.corechat.back.api import agents as live_agents
            from fab.corechat.back import commands
            agent = live_agents[USER]["helper"]
            import asyncio
            tc = {"id": "t1", "function": {"name": "GREAD", "arguments": json.dumps({"board": "main", "ref": "mission"})}}
            result = asyncio.run(commands.dispatch(agent, tc))
            assert "the mission is testing" in result["content"], result["content"]
            # and a doc it has NO grant on is refused
            node2 = client.post("/thoughtgraph/boards/main/nodes", json={"title": "hidden", "kind": "doc"}).json()
            tc = {"id": "t2", "function": {"name": "GREAD", "arguments": json.dumps({"board": "main", "ref": "hidden"})}}
            result = asyncio.run(commands.dispatch(agent, tc))
            assert "[ERROR]" in result["content"], result["content"]
            print("thoughtgraph: grant enforced — granted doc readable, ungranted refused")

        # ---- wiresend: channel with the agent; user message pings the agent's inbox ----
        # wiresend has its own ws
        with client.websocket_connect("/wiresend/ws") as wsw:
            wsw.send_text(json.dumps({"cmd": "create_channel", "name": "lab", "agents": ["helper"]}))
            d = recv_until(wsw, lambda m: m.get("type") == "channels" and m["channels"], 10)
            assert d and d["channels"][0]["name"] == "lab"
            wsw.send_text(json.dumps({"cmd": "chat_send", "channel": "lab", "text": "hi agent"}))
            d = recv_until(wsw, lambda m: m.get("type") == "chat_message", 10)
            assert d and d["message"]["text"] == "hi agent"
        # the ping wakes a turn, which drains it into the on-disk context — poll for that
        # (agent.inbox itself races with the drain)
        ctx_path = udir(USER) / "agents" / "helper" / "working.jsonl"
        deadline = time.time() + 30
        while time.time() < deadline and "[wiresend]" not in ctx_path.read_text():
            time.sleep(0.5)
        assert "[wiresend]" in ctx_path.read_text(), "the ping never reached the agent's context"
        print("wiresend: channel chat works, agent got pinged")

        # ---- dockeruse: create, assign, stop, start, destroy (real docker) ----
        r = client.post("/dockeruse/containers", json={"name": "testbox"})
        assert r.status_code == 200, r.text
        try:
            r = client.post("/dockeruse/containers/testbox/assign", json={"agent": "helper"})
            assert r.status_code == 200, r.text
            r = client.post("/dockeruse/containers/testbox/stop")
            assert r.status_code == 200, r.text
            cs = client.get("/dockeruse/containers").json()["containers"]
            assert cs[0]["running"] is False and cs[0]["agent"] == "helper"
            r = client.post("/dockeruse/containers/testbox/start")
            assert r.status_code == 200, r.text
            cs = client.get("/dockeruse/containers").json()["containers"]
            assert cs[0]["running"] is True
            print("dockeruse: create/assign/stop/start all work on real docker")
        finally:
            client.delete("/dockeruse/containers/testbox", params={"workspace": "1"})

    cleanup()
    print("test_e2e OK")


if __name__ == "__main__":
    main()
