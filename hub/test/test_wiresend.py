'''wiresend: channels as the ACL, the append-only message log, and the file store.

the file store is where the care is: nothing may be held whole in memory, nothing may be
written outside a channel's files/ dir, and a refused upload must leave no partial file.'''

import asyncio
import json

import pytest

from fab.config import udir
from fab.corechat.back import commands
from fab.dockeruse.back.config import workspace_dir
from fab.wiresend.back import chat, notify
from fab.wiresend.back.chat import USER_SENDER
from hub.test.conftest import StubAgent, drained, make_agent, recv, recv_until

USER = "tester"
AGENT = "helper"


@pytest.fixture
def channel(fab_home) -> str:
    chat.create_channel(USER, "lab", [USER_SENDER, AGENT])
    return "lab"


@pytest.fixture
def tool_agent(channel) -> StubAgent:
    return StubAgent(USER, AGENT)


@pytest.fixture
def workspace(fab_home):
    '''the agent's computer: a container assigned to it, and the workspace tree on disk.
    wiresend's file tools move bytes between that tree and the channel store.'''
    from fab.dockeruse.back import containers
    containers.save(USER, {"box": {"novnc_port": 6080, "agent": AGENT}})
    ws = workspace_dir(USER, "box")
    ws.mkdir(parents=True)
    return ws


def files_dir(channel_id: str = "lab"):
    return udir(USER) / "wiresend" / channel_id / "files"


def run_tool(name: str, agent: StubAgent, **args) -> str:
    return asyncio.run(commands.COMMANDS[name]["handler"](args, agent))


async def stream(*chunks):
    for chunk in chunks:
        yield chunk


# ---- channels ----

def test_channel_ids_are_slugged_and_never_collide(fab_home):
    first = chat.create_channel(USER, "My Lab!", [USER_SENDER])
    second = chat.create_channel(USER, "My Lab!", [USER_SENDER])
    assert first["id"] == "my-lab" and second["id"] == "my-lab-2"


def test_channel_rename_and_delete(channel):
    chat.rename_channel(USER, channel, "renamed")
    assert chat.channel_of(USER, channel)["name"] == "renamed"
    with pytest.raises(ValueError, match="cannot be empty"):
        chat.rename_channel(USER, channel, "   ")
    chat.delete_channel(USER, channel)
    assert chat.load_channels(USER) == {}
    assert not (udir(USER) / "wiresend" / channel).exists(), "the channel's files must go with it"


def test_membership_is_the_whole_acl(channel):
    assert chat.is_member(USER, channel, AGENT) and not chat.is_member(USER, channel, "stranger")
    with pytest.raises(ValueError, match="not a member"):
        chat.set_readonly(USER, channel, "stranger", True)


def test_readonly_members_read_but_never_write(channel):
    chat.set_readonly(USER, channel, AGENT, True)
    assert chat.is_member(USER, channel, AGENT)
    assert not chat.can_write(USER, channel, AGENT)
    assert chat.can_write(USER, channel, USER_SENDER), "the user is never readonly"
    chat.set_readonly(USER, channel, AGENT, False)
    assert chat.can_write(USER, channel, AGENT)


def test_dropping_a_member_drops_their_readonly_flag(channel):
    chat.set_readonly(USER, channel, AGENT, True)
    chat.set_members(USER, channel, [USER_SENDER])
    assert chat.channel_of(USER, channel)["readonly"] == []


def test_the_dm_channel_is_deterministic_and_lazy(fab_home):
    assert chat.load_channels(USER) == {}, "a DM appears only on first touch"
    assert chat.ensure_dm(USER, AGENT) == f"dm-{AGENT}"
    assert chat.ensure_dm(USER, AGENT) == f"dm-{AGENT}", "touching it twice makes one channel"
    dm = chat.channel_of(USER, f"dm-{AGENT}")
    assert dm["dm"] is True and dm["members"] == [USER_SENDER, AGENT]


def test_channels_resolve_by_id_or_name_but_only_for_members(channel):
    assert chat.resolve_channel(USER, "lab", AGENT) == "lab"
    with pytest.raises(ValueError, match="no access"):
        chat.resolve_channel(USER, "lab", "stranger")
    # two channels sharing a NAME (their ids differ) is the ambiguous case; a bare id never is
    chat.create_channel(USER, "My Lab", [USER_SENDER, AGENT])
    chat.create_channel(USER, "My Lab", [USER_SENDER, AGENT])
    with pytest.raises(ValueError, match="ambiguous"):
        chat.resolve_channel(USER, "My Lab", AGENT)


# ---- messages ----

def test_messages_append_and_read_back_in_order(channel):
    for i in range(5):
        chat.append_message(USER, channel, AGENT, "text", text=f"m{i}")
    assert [m["text"] for m in chat.read_messages(USER, channel)] == [f"m{i}" for i in range(5)]
    assert [m["text"] for m in chat.read_messages(USER, channel, limit=2)] == ["m3", "m4"]


def test_unread_counts_ignore_your_own_messages(channel):
    chat.append_message(USER, channel, USER_SENDER, "text", text="from the user")
    mine = chat.append_message(USER, channel, AGENT, "text", text="from me")
    assert chat.unread_count(USER, AGENT, channel) == 1, "an agent's own message is not unread"
    chat.mark_read(USER, AGENT, channel, mine["ts"])
    assert chat.unread_count(USER, AGENT, channel) == 0


# ---- the file store ----

def test_a_streamed_upload_lands_whole(channel):
    ref = asyncio.run(chat.store_stream(USER, channel, "w/model.pt", stream(b"abc", b"defg")))
    assert ref == {"name": "model.pt", "size": 7, "path": "w/model.pt"}
    assert (files_dir() / "w" / "model.pt").read_bytes() == b"abcdefg"


def test_an_upload_over_the_cap_is_cut_off_and_leaves_nothing(channel, monkeypatch):
    monkeypatch.setattr(chat, "MAX_FILE_BYTES", 5)
    with pytest.raises(ValueError, match="too large"):
        asyncio.run(chat.store_stream(USER, channel, "big.bin", stream(b"x" * 4, b"y" * 4)))
    assert not (files_dir() / "big.bin").exists(), "a refused upload must leave no partial file"


def test_an_empty_upload_is_refused(channel):
    with pytest.raises(ValueError, match="empty"):
        asyncio.run(chat.store_stream(USER, channel, "nothing.bin", stream()))
    assert not (files_dir() / "nothing.bin").exists()


def test_a_copy_is_measured_with_stat_not_by_reading(channel, tmp_path, monkeypatch):
    src = tmp_path / "big.bin"
    src.write_bytes(b"z" * 100)
    monkeypatch.setattr(chat, "MAX_FILE_BYTES", 10)
    # the cap has to be decided from the size alone — reading it would defeat the point
    monkeypatch.setattr(type(src), "read_bytes", lambda self: pytest.fail("the file was read"))
    with pytest.raises(ValueError, match="100 bytes"):
        chat.store_copy(USER, channel, "copied.bin", src)


@pytest.mark.parametrize("escape", ["../../escaped", "/etc/passwd", "a/../../../b"])
def test_channel_paths_can_never_leave_the_files_dir(channel, escape):
    resolved = chat.channel_file(USER, channel, escape)
    assert resolved.is_relative_to(files_dir().resolve()), resolved


def test_the_file_tree_lists_dirs_and_sizes(channel):
    asyncio.run(chat.store_stream(USER, channel, "sub/a.bin", stream(b"12345")))
    chat.mkdir_channel(USER, channel, "empty_dir")
    entries = {e["name"]: e for e in chat.list_file_tree(USER, channel)}
    assert entries["sub"]["is_dir"] and entries["empty_dir"]["is_dir"]
    inner = chat.list_file_tree(USER, channel, "sub")
    assert inner[0]["size"] == 5 and inner[0]["path"] == "sub/a.bin"


def test_files_rename_and_delete(channel):
    asyncio.run(chat.store_stream(USER, channel, "old.bin", stream(b"data")))
    chat.rename_file(USER, channel, "old.bin", "new.bin")
    assert (files_dir() / "new.bin").exists() and not (files_dir() / "old.bin").exists()
    chat.delete_file(USER, channel, "new.bin")
    assert not (files_dir() / "new.bin").exists()
    with pytest.raises(ValueError, match="not found"):
        chat.delete_file(USER, channel, "new.bin")


# ---- notifications ----

def test_a_message_pings_every_loaded_member_except_its_sender(channel, fab_home):
    from fab.corechat.back.api import agents
    listener, speaker = StubAgent(USER, AGENT), StubAgent(USER, "speaker")
    chat.set_members(USER, channel, [USER_SENDER, AGENT, "speaker"])
    agents[USER] = {AGENT: listener, "speaker": speaker}

    msg = chat.append_message(USER, channel, "speaker", "text", text="hello")
    notify.message_posted(USER, channel, msg)

    assert listener.inbox and "[wiresend]" in listener.inbox[0]["content"][0]["text"]
    assert listener.wake.is_set(), "a ping has to wake the agent's next turn"
    assert speaker.inbox == [], "the sender must not ping itself"
    assert any(m["type"] == "chat_message" for m in drained(notify._bus))


# ---- the agent's tools ----

def test_wire_channels_tells_an_agent_with_none_what_to_do(fab_home):
    assert "no channels" in run_tool("WIRE_CHANNELS", StubAgent(USER, AGENT))


def test_wire_channels_lists_membership_with_flags(tool_agent):
    chat.append_message(USER, "lab", USER_SENDER, "text", text="unread one")
    chat.set_readonly(USER, "lab", AGENT, True)
    out = run_tool("WIRE_CHANNELS", tool_agent)
    assert "#lab" in out and "1 unread" in out and "(read-only)" in out


def test_wire_send_and_read(tool_agent):
    run_tool("WIRE_SEND", tool_agent, channel="lab", text="reporting in")
    out = run_tool("WIRE_READ", tool_agent, channel="lab")
    assert f"{AGENT}: reporting in" in out
    assert chat.unread_count(USER, AGENT, "lab") == 0, "reading marks the channel read"


def test_wire_send_respects_readonly_and_membership(tool_agent):
    chat.set_readonly(USER, "lab", AGENT, True)
    assert "read-only" in run_tool("WIRE_SEND", tool_agent, channel="lab", text="let me in")
    assert chat.read_messages(USER, "lab") == []
    with pytest.raises(ValueError, match="no access"):
        run_tool("WIRE_SEND", tool_agent, channel="nowhere", text="hi")


def test_file_tools_say_what_to_do_when_there_is_no_computer(tool_agent):
    assert "no docker assigned" in run_tool("WIRE_UPLOAD", tool_agent, channel="lab",
                                           source="x", text="why")
    assert "no docker assigned" in run_tool("WIRE_DOWNLOAD", tool_agent, channel="lab", file="x")


def test_upload_and_download_move_bytes_through_the_workspace(tool_agent, workspace):
    (workspace / "results").mkdir()
    (workspace / "results" / "out.txt").write_text("the findings")
    run_tool("WIRE_UPLOAD", tool_agent, channel="lab", source="results/out.txt",
             text="my findings")
    assert (files_dir() / "results" / "out.txt").read_text() == "the findings"
    # the message carries the file ref so the user sees what arrived and why
    msg = chat.read_messages(USER, "lab")[-1]
    assert msg["type"] == "file" and msg["text"] == "my findings"
    assert msg["file"] == {"name": "out.txt", "size": 12, "path": "results/out.txt"}

    run_tool("WIRE_DOWNLOAD", tool_agent, channel="lab", file="results/out.txt", dest="back.txt")
    assert (workspace / "back.txt").read_text() == "the findings"


def test_uploading_a_folder_preserves_its_structure(tool_agent, workspace):
    (workspace / "run" / "deep").mkdir(parents=True)
    (workspace / "run" / "deep" / "a.txt").write_text("a")
    (workspace / "run" / "b.txt").write_text("b")
    run_tool("WIRE_UPLOAD", tool_agent, channel="lab", source="run", text="the whole run")
    assert (files_dir() / "run" / "deep" / "a.txt").read_text() == "a"
    assert (files_dir() / "run" / "b.txt").read_text() == "b"


def test_upload_requires_a_reason_and_a_real_file(tool_agent, workspace):
    with pytest.raises(ValueError, match="text required"):
        run_tool("WIRE_UPLOAD", tool_agent, channel="lab", source="x", text="  ")
    assert "not found" in run_tool("WIRE_UPLOAD", tool_agent, channel="lab",
                                   source="ghost.txt", text="where is it")


@pytest.mark.parametrize("escape", ["../../../.env", "/etc/passwd"])
def test_file_tools_cannot_reach_outside_the_workspace(tool_agent, workspace, escape):
    with pytest.raises(ValueError, match="escapes workspace"):
        run_tool("WIRE_UPLOAD", tool_agent, channel="lab", source=escape, text="sneaky")


# ---- the http door ----

def test_http_upload_download_and_listing(client, user, fab_home):
    chat.create_channel(user, "lab", [USER_SENDER])
    r = client.post("/wiresend/chat/lab/files?name=deep/data.bin", content=b"hello streamed world")
    assert r.status_code == 200, r.text
    assert r.json()["file"] == {"name": "data.bin", "size": 20, "path": "deep/data.bin"}
    assert client.get("/wiresend/chat/lab/files/deep/data.bin").content == b"hello streamed world"
    listing = client.get("/wiresend/chat/lab/files-list?path=deep").json()["files"]
    assert [e["name"] for e in listing] == ["data.bin"]

    assert client.put("/wiresend/chat/lab/files/deep/data.bin",
                      json={"new_name": "deep/renamed.bin"}).status_code == 200
    assert client.delete("/wiresend/chat/lab/files/deep/renamed.bin").status_code == 200
    assert client.get("/wiresend/chat/lab/files-list?path=deep").json()["files"] == []


def test_http_upload_refuses_an_oversize_declared_length(client, user, fab_home, monkeypatch):
    chat.create_channel(user, "lab", [USER_SENDER])
    import fab.wiresend.back.api as wiresend_api
    monkeypatch.setattr(wiresend_api, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="too large"):
        client.post("/wiresend/chat/lab/files?name=big.bin", content=b"x" * 50)
    assert not (udir(user) / "wiresend" / "lab" / "files" / "big.bin").exists()


def test_ws_channel_commands(client, user, fab_home):
    make_agent(user, AGENT)
    with client.websocket_connect("/wiresend/ws") as ws:
        assert recv(ws)["channels"] == []
        ws.send_json({"cmd": "create_channel", "name": "lab", "agents": [AGENT]})
        payload = recv_until(ws, lambda m: m.get("type") == "channels" and m["channels"])
        cid = payload["channels"][0]["id"]
        assert payload["channels"][0]["members"] == [USER_SENDER, AGENT]

        ws.send_json({"cmd": "set_readonly", "channel": cid, "agent": AGENT, "readonly": True})
        assert recv_until(ws, lambda m: m.get("type") == "channels")["channels"][0]["readonly"] == [AGENT]

        ws.send_json({"cmd": "rename_channel", "channel": cid, "name": "renamed"})
        assert recv_until(ws, lambda m: m.get("type") == "channels")["channels"][0]["name"] == "renamed"

        ws.send_json({"cmd": "chat_send", "channel": cid, "text": "hi agent"})
        assert recv_until(ws, lambda m: m.get("type") == "chat_message")["message"]["text"] == "hi agent"

        ws.send_json({"cmd": "get_messages", "channel": cid})
        assert recv_until(ws, lambda m: m.get("type") == "messages")["messages"][0]["text"] == "hi agent"

        ws.send_json({"cmd": "delete_channel", "channel": cid})
        assert recv_until(ws, lambda m: m.get("type") == "channels")["channels"] == []


def test_ws_rejects_an_unknown_command_and_a_missing_cookie(client, user):
    with client.websocket_connect("/wiresend/ws") as ws:
        recv(ws)
        ws.send_json({"cmd": "nonsense"})
        assert "unknown command" in recv_until(ws, lambda m: m.get("type") == "error")["msg"]
    client.cookies.clear()
    with pytest.raises(Exception):
        with client.websocket_connect("/wiresend/ws") as ws:
            ws.receive_text()


def test_ws_list_channels_and_set_members(client, user, fab_home):
    make_agent(user, AGENT)
    make_agent(user, "second")
    chat.create_channel(user, "lab", [USER_SENDER])
    with client.websocket_connect("/wiresend/ws") as ws:
        recv(ws)
        ws.send_json({"cmd": "list_channels"})
        assert recv_until(ws, lambda m: m.get("type") == "channels")["channels"][0]["name"] == "lab"
        ws.send_json({"cmd": "set_members", "channel": "lab", "agents": [AGENT, "second"]})
        members = recv_until(ws, lambda m: m.get("type") == "channels")["channels"][0]["members"]
        assert members == [USER_SENDER, AGENT, "second"]
    # the agents endpoint is what the page offers as candidates
    assert client.get("/wiresend/agents").json()["agents"] == [AGENT, "second"]
