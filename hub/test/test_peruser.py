'''per-user isolation tests: two users, separate worlds. corechat agents + ws scoping,
thoughtgraph boards, dockeruse containers + ports. run from repo root: venv/bin/python hub/test/test_peruser.py'''

import json
import shutil
import threading

from fastapi.testclient import TestClient

from fab.config import FAB_DIR, udir
from fab.dockeruse.back import containers
from hub.back.app import app
from hub.back.auth import COOKIE_NAME

UA, UB = "test_iso_a", "test_iso_b"


def cleanup():
    for u in (UA, UB):
        shutil.rmtree(udir(u), ignore_errors=True)
    p = FAB_DIR / "auth" / "users.json"
    if p.exists():
        data = json.loads(p.read_text())
        for u in (UA, UB):
            data.pop(u, None)
        p.write_text(json.dumps(data))
    p = FAB_DIR / "auth" / "sessions.json"
    if p.exists():
        data = {k: v for k, v in json.loads(p.read_text()).items() if v.get("user") not in (UA, UB)}
        p.write_text(json.dumps(data))


def recv_t(ws, seconds):
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("m", ws.receive_text()), daemon=True)
    t.start()
    t.join(seconds)
    return box.get("m")


def recv(ws, seconds=5):
    m = recv_t(ws, seconds)
    assert m is not None, "timed out waiting for a message"
    return m


def main():
    cleanup()
    with TestClient(app) as client:
        tokens = {}
        for u in (UA, UB):
            r = client.post("/auth/register", json={"username": u, "password": "pw123"})
            assert r.status_code == 200, r.text
            tokens[u] = client.cookies.get(COOKIE_NAME)
            client.cookies.clear()

        def as_a():
            client.cookies.set(COOKIE_NAME, tokens[UA])

        def as_b():
            client.cookies.set(COOKIE_NAME, tokens[UB])

        # ---- thoughtgraph: separate boards, separate content ----
        as_a()
        assert client.get("/thoughtgraph/boards").json()["boards"] == ["main"]
        node = client.post("/thoughtgraph/boards/main/nodes", json={"title": "a's note", "kind": "doc"}).json()
        nid = node["id"]
        client.put(f"/thoughtgraph/boards/main/nodes/{nid}/content", json={"content": "secret of A"})
        as_b()
        assert client.get("/thoughtgraph/boards").json()["boards"] == ["main"]
        graph = client.get("/thoughtgraph/boards/main/graph").json()
        assert all(n["title"] != "a's note" for n in graph["nodes"].values()), "B sees A's node"
        as_a()
        assert client.get(f"/thoughtgraph/boards/main/nodes/{nid}/content").json()["content"] == "secret of A"
        print("thoughtgraph isolated")

        # ---- corechat: unauthenticated ws rejected; A's agents invisible to B; broadcasts scoped ----
        try:
            with client.websocket_connect("/corechat/ws") as ws:
                ws.receive_text()
            raise AssertionError("unauthenticated ws was accepted")
        except Exception:
            pass  # rejected before accept, as designed
        print("ws rejected without cookie")

        as_a()
        with client.websocket_connect("/corechat/ws") as wsa:
            assert json.loads(recv(wsa))["agents"] == []
            wsa.send_text(json.dumps({"cmd": "create", "name": "aa"}))
            payload = json.loads(recv(wsa))
            assert payload["agents"][0]["name"] == "aa"
            assert (udir(UA) / "agents" / "aa").exists()
            assert not (udir(UB) / "agents" / "aa").exists()

            as_b()
            with client.websocket_connect("/corechat/ws") as wsb:
                assert json.loads(recv(wsb))["agents"] == []
                # A pins the agent — a user-scoped broadcast; B must hear nothing
                as_a()
                wsa.send_text(json.dumps({"cmd": "pin", "name": "aa", "pinned": True}))
                assert json.loads(recv(wsa))["agents"][0]["pinned"] is True
                assert recv_t(wsb, 3) is None, "B received A's broadcast"
        print("corechat isolated, broadcasts scoped per user")

        # ---- dockeruse: per-user store, host-wide ports, per-user vnc ownership ----
        containers.save(UA, {"pc1": {"novnc_port": 6080, "agent": None}})
        containers.save(UB, {"pc1": {"novnc_port": containers._next_port(), "agent": None}})
        assert containers.load(UB)["pc1"]["novnc_port"] == 6081, "ports must not collide across users"
        assert containers.load(UA)["pc1"]["novnc_port"] == 6080
        as_a()
        assert [c["name"] for c in client.get("/dockeruse/containers").json()["containers"]] == ["pc1"]
        # B gets 403 on A's port, and the ownership check itself is per-user
        from fab.dockeruse.back.api import _owned_vnc_port
        assert _owned_vnc_port(UA, "6080") == 6080
        assert _owned_vnc_port(UB, "6080") is None
        as_b()
        r = client.get("/dockeruse/vnc/6080/vnc.html")
        assert r.status_code == 403, r.status_code
        print("dockeruse isolated, ports host-wide, vnc ownership per user")

        # ---- wiresend: separate channels, unauthenticated ws rejected, events scoped ----
        try:
            with client.websocket_connect("/wiresend/ws") as ws:
                ws.receive_text()
            raise AssertionError("unauthenticated wiresend ws was accepted")
        except Exception:
            pass
        as_a()
        with client.websocket_connect("/wiresend/ws") as wsa:
            assert json.loads(recv(wsa))["channels"] == []
            wsa.send_text(json.dumps({"cmd": "create_channel", "name": "lab", "agents": []}))
            payload = json.loads(recv(wsa))
            assert payload["channels"][0]["name"] == "lab"
            wsa.send_text(json.dumps({"cmd": "chat_send", "channel": "lab", "text": "hello from A"}))
            assert json.loads(recv(wsa))["type"] == "chat_message"
            as_b()
            with client.websocket_connect("/wiresend/ws") as wsb:
                assert json.loads(recv(wsb))["channels"] == [], "B sees A's channels"
                as_a()
                wsa.send_text(json.dumps({"cmd": "chat_send", "channel": "lab", "text": "another one"}))
                assert recv_t(wsb, 3) is None, "B received A's wiresend event"
        assert (udir(UA) / "wiresend" / "lab" / "messages.jsonl").exists()
        assert not (udir(UB) / "wiresend").exists() or not (udir(UB) / "wiresend" / "lab").exists()
        # the http file routes are per user too: B's world has no "lab" channel, so the listing is empty
        as_b()
        assert client.get("/wiresend/chat/lab/files-list").json()["files"] == [], "B must not see A's channel files"
        print("wiresend isolated, events scoped per user")

    cleanup()
    print("test_peruser OK")


if __name__ == "__main__":
    main()
