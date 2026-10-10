'''per-user isolation: two accounts, two separate worlds.

every module stores under users/{user}/ and every broadcast is scoped to one account. these
tests only ask one question, from both sides: can A reach, see, or hear anything of B's?'''

import pytest

from fab.config import udir
from fab.dockeruse.back import containers
from fab.dockeruse.back.api import _owned_vnc_port
from hub.back.auth import COOKIE_NAME
from hub.test.conftest import recv, recv_nothing, recv_until, register, send_cmd

UA, UB = "user_a", "user_b"


@pytest.fixture
def act_as(client, fab_home):
    '''two accounts on one client; the returned function picks which one is acting.'''
    tokens = {}  # {str: str} — username -> session token
    for name in (UA, UB):
        tokens[name] = register(client, name)
        client.cookies.clear()
    return lambda name: client.cookies.set(COOKIE_NAME, tokens[name])


def test_thoughtgraph_worlds_are_separate(client, act_as):
    act_as(UA)
    assert client.get("/thoughtgraph/boards").json()["boards"] == ["main"]
    node = client.post("/thoughtgraph/boards/main/nodes",
                       json={"title": "a's note", "kind": "doc"}).json()
    client.put(f"/thoughtgraph/boards/main/nodes/{node['id']}/content",
               json={"content": "secret of A"})

    act_as(UB)
    # B's "main" is B's own board, seeded fresh on first touch
    assert client.get("/thoughtgraph/boards").json()["boards"] == ["main"]
    assert client.get("/thoughtgraph/boards/main/graph").json()["nodes"] == {}

    act_as(UA)
    assert client.get(f"/thoughtgraph/boards/main/nodes/{node['id']}/content"
                      ).json()["content"] == "secret of A"


def test_corechat_agents_are_invisible_across_accounts(client, act_as, fake_model):
    act_as(UA)
    with client.websocket_connect("/corechat/ws") as wsa:
        assert recv(wsa)["agents"] == []
        assert send_cmd(wsa, cmd="create", name="aa")["agents"][0]["name"] == "aa"
        assert (udir(UA) / "agents" / "aa").exists()
        assert not (udir(UB) / "agents" / "aa").exists()

        act_as(UB)
        with client.websocket_connect("/corechat/ws") as wsb:
            assert recv(wsb)["agents"] == [], "B sees A's agent"
            # A pins their agent: a user-scoped broadcast that B must never hear
            act_as(UA)
            assert send_cmd(wsa, cmd="pin", name="aa", pinned=True)["agents"][0]["pinned"] is True
            recv_nothing(wsb)


def test_dockeruse_stores_are_separate_but_ports_are_host_wide(client, act_as):
    containers.save(UA, {"pc1": {"novnc_port": 6080, "agent": None}})
    containers.save(UB, {"pc1": {"novnc_port": containers._next_port(), "agent": None}})
    assert containers.load(UB)["pc1"]["novnc_port"] == 6081, "two users must not collide on a port"

    act_as(UA)
    assert [c["name"] for c in client.get("/dockeruse/containers").json()["containers"]] == ["pc1"]
    assert _owned_vnc_port(UA, "6080") == 6080 and _owned_vnc_port(UB, "6080") is None
    act_as(UB)
    assert client.get("/dockeruse/vnc/6080/vnc.html").status_code == 403, "B reached A's desktop"


def test_wiresend_channels_and_events_are_separate(client, act_as):
    act_as(UA)
    with client.websocket_connect("/wiresend/ws") as wsa:
        assert recv(wsa)["channels"] == []
        wsa.send_json({"cmd": "create_channel", "name": "lab", "agents": []})
        assert recv_until(wsa, lambda m: m.get("type") == "channels")["channels"][0]["name"] == "lab"
        wsa.send_json({"cmd": "chat_send", "channel": "lab", "text": "hello from A"})
        assert recv_until(wsa, lambda m: m.get("type") == "chat_message")

        act_as(UB)
        with client.websocket_connect("/wiresend/ws") as wsb:
            assert recv(wsb)["channels"] == [], "B sees A's channels"
            act_as(UA)
            wsa.send_json({"cmd": "chat_send", "channel": "lab", "text": "another one"})
            recv_nothing(wsb)

    assert (udir(UA) / "wiresend" / "lab" / "messages.jsonl").exists()
    assert not (udir(UB) / "wiresend" / "lab").exists()
    # the http file routes are per user too: B has no "lab", so the listing is empty
    act_as(UB)
    assert client.get("/wiresend/chat/lab/files-list").json()["files"] == []
