'''corechat: the core loop and the websocket api.

no network anywhere — FakeModelServer stands in for the provider, so these tests need no
api key and cost nothing. the real provider round trip lives in test_e2e.'''

import asyncio

import pytest

from fab.config import PRESERVE_LAST, udir
from fab.corechat.back import commands
from fab.corechat.back import websocket as corechat_ws
from fab.corechat.back.agent import Agent
from fab.corechat.back.api import (agents_payload, delete_agent, get_agent, pin_agent,
                                   rename_agent)
from fab.corechat.back.prompt import REPAIR_NOTE, SYSTEM, WORK_MSG
from fab.dockeruse.back import containers
from fab.thoughtgraph.back import storage as thoughtgraph_storage
from fab.wiresend.back import chat as wiresend_chat
from hub.back.auth import COOKIE_NAME
from hub.test.conftest import (FakeModelServer, assistant_msg, drained, recv, recv_nothing,
                               make_agent, recv_until, register, send_cmd,
                               stores_mentioning, tool_msg, user_msg)

USER = "tester"


@pytest.fixture
def agent(fab_home) -> Agent:
    return Agent(USER, "a", FakeModelServer(), context_limit=10_000)


# ---- repair_context: tool calls and tool results must pair up in BOTH directions ----

def test_repair_drops_tool_result_with_no_call(agent):
    # what compression leaves behind when the cut lands between an assistant and its results
    agent.working_context = [{"role": "system", "content": SYSTEM}, assistant_msg("summary"),
                             tool_msg("c1"), tool_msg("c2"), assistant_msg("tail")]
    agent.repair_context()
    assert [m["role"] for m in agent.working_context] == ["system", "assistant", "assistant"]


def test_repair_fills_call_with_no_result(agent):
    # what an interrupted dispatch leaves behind
    agent.working_context = [{"role": "system", "content": SYSTEM}, assistant_msg(None, ["c1"])]
    agent.repair_context()
    assert agent.working_context[-1] == tool_msg("c1", REPAIR_NOTE)


def test_repair_leaves_a_valid_context_alone(agent):
    valid = [{"role": "system", "content": SYSTEM}, assistant_msg(None, ["c1"]),
             tool_msg("c1"), user_msg("hi")]
    agent.working_context = list(valid)
    agent.repair_context()
    assert agent.working_context == valid


def test_repair_nudges_a_bare_assistant_only_in_agent_mode(agent):
    bare = [{"role": "system", "content": SYSTEM}, assistant_msg("just thinking")]
    agent.working_context = list(bare)
    agent.repair_context()
    assert agent.working_context == bare, "chat mode must never inject the nudge"
    agent.agent_mode = True
    agent.repair_context()
    assert agent.working_context[-1] == user_msg(WORK_MSG)


# ---- context size ----

def test_count_words_across_every_content_shape(agent):
    agent.working_context = [
        {"role": "system", "content": "one two"},        # plain string
        assistant_msg(None, ["c1"]),                     # tool-call-only: content is null
        tool_msg("c1", "three"),                         # tool result string
        user_msg("four five six"),                       # text blocks
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "d"}}]},
    ]
    assert agent.count_context_words() == 2 + 1 + 3 + 1000


# ---- compression ----

def test_compress_is_a_noop_under_the_limit(agent):
    agent.context_limit = 1000
    agent.working_context = [{"role": "system", "content": SYSTEM}, user_msg("small")]
    before = list(agent.working_context)
    asyncio.run(agent.compress())
    assert agent.working_context == before
    assert agent.model_server.calls == [], "compression called the model under the limit"


def test_compress_rebuilds_around_the_summary(agent):
    agent.context_limit = 10
    agent.model_server.replies = [{"role": "assistant", "content": "the summary"}]
    tail = [user_msg(f"msg {i}") for i in range(6)]
    agent.working_context = [{"role": "system", "content": SYSTEM}] + tail
    asyncio.run(agent.compress())
    assert agent.working_context[0]["content"] == SYSTEM, "the real system prompt must survive"
    assert agent.working_context[1]["content"] == "the summary"
    assert agent.working_context[2:] == tail[-PRESERVE_LAST:]
    # the summarize call runs toolless over a COPY, so the live context keeps its system prompt
    summarize_context, tools = agent.model_server.calls[0]
    assert tools == [] and summarize_context[0]["content"] != SYSTEM


def test_compress_repairs_the_seam_it_cuts(agent):
    # two calls + two results + a final assistant: keeping the last 3 orphans both results
    agent.context_limit = 10
    agent.model_server.replies = [{"role": "assistant", "content": "the summary"}]
    agent.working_context = ([{"role": "system", "content": SYSTEM}]
                             + [user_msg("filler " * 20) for _ in range(5)]
                             + [assistant_msg(None, ["c9", "c10"]), tool_msg("c9"),
                                tool_msg("c10"), assistant_msg("done")])
    asyncio.run(agent.compress())
    roles = [m["role"] for m in agent.working_context]
    assert "tool" not in roles, f"an orphaned tool result survived: {roles}"


# ---- the turn ----

def test_turn_drains_the_inbox_and_appends_the_reply(agent):
    agent.model_server.replies = [{"role": "assistant", "content": "hello back"}]
    agent.inbox.append(user_msg("hello"))
    asyncio.run(agent.turn())
    assert agent.inbox == []
    assert agent.working_context[-2] == user_msg("hello")
    assert agent.working_context[-1]["content"] == "hello back"
    # and it is on disk, not just in memory
    saved = (udir(USER) / "agents" / "a" / "working.jsonl").read_text().splitlines()
    assert len(saved) == len(agent.working_context)


def test_turn_dispatches_tool_calls_and_appends_results(agent):
    agent.model_server.replies = [assistant_msg(None, ["c1"], arguments='{"text": "ping"}')]
    agent.inbox.append(user_msg("go"))
    asyncio.run(agent.turn())
    assert agent.working_context[-1] == tool_msg("c1", "str received: ping")


def test_a_dead_turn_broadcasts_an_error(agent):
    # the frontend renders this where the reply would have been; silence would look like
    # the agent simply said nothing
    agent.model_server.error = RuntimeError("rate limit exceeded")
    agent.inbox.append(user_msg("hi"))
    drained(corechat_ws._bus)
    asyncio.run(agent.turn())
    errors = [m for m in drained(corechat_ws._bus) if m["type"] == "error"]
    assert errors and errors[0]["msg"] == "RuntimeError: rate limit exceeded"
    assert errors[0]["name"] == "a"


def test_turn_rewakes_itself_only_when_there_is_more_to_do(agent):
    asyncio.run(agent.turn())
    assert not agent.wake.is_set(), "an idle chat-mode turn must not re-wake"
    agent.agent_mode = True
    asyncio.run(agent.turn())
    assert agent.wake.is_set(), "agent mode must keep turning"


def test_deposit_queues_a_result_and_wakes_a_turn(agent):
    agent.deposit("EXEC", "exit 0")
    assert agent.inbox == [user_msg("[tool result] EXEC: exit 0")]
    assert agent.wake.is_set()


# ---- dispatch: a bad call becomes an error result, never a crashed turn ----

@pytest.mark.parametrize("call, expected", [
    ({"id": "x", "function": {"name": "NOPE", "arguments": "{}"}}, "unknown command NOPE"),
    ({"id": "x", "function": {"name": "TEST", "arguments": "{not json}"}}, "bad arguments json"),
    ({"id": "x", "function": {"name": "TEST", "arguments": "{}"}}, "KeyError"),
])
def test_dispatch_turns_bad_calls_into_error_results(agent, call, expected):
    result = asyncio.run(commands.dispatch(agent, call))
    assert result["role"] == "tool" and result["tool_call_id"] == "x"
    assert result["content"].startswith("[ERROR]") and expected in result["content"]


def test_wait_ends_on_timeout_and_early_on_new_input(agent):
    assert "waited" in asyncio.run(commands.COMMANDS["WAIT"]["handler"]({"seconds": 0.05}, agent))
    agent.wake.set()
    assert "interrupted" in asyncio.run(commands.COMMANDS["WAIT"]["handler"]({"seconds": 30}, agent))


def test_stop_parks_the_agent(agent):
    agent.agent_mode = True
    drained(corechat_ws._bus)
    asyncio.run(commands.COMMANDS["STOP"]["handler"]({}, agent))
    assert agent.agent_mode is False
    assert any(m["type"] == "agents_changed" for m in drained(corechat_ws._bus))


# ---- agent lifecycle (the websocket commands' backing functions) ----

def test_agents_payload_sorts_pinned_first_then_newest(fab_home):
    for name, created in (("old", 100.0), ("new", 200.0), ("fav", 150.0)):
        make_agent(USER, name, created)
    pin_agent(USER, "fav", True)
    names = [a["name"] for a in agents_payload(USER)["agents"]]
    assert names[0] == "fav", names
    assert names[1:] == ["new", "old"], "within a group, newest first"


def test_rename_carries_the_name_into_every_other_module(fab_home):
    make_agent(USER, "old")
    containers.save(USER, {"box": {"novnc_port": 6080, "agent": "old"}})
    wiresend_chat.create_channel(USER, "lab", [wiresend_chat.USER_SENDER, "old"])
    wiresend_chat.ensure_dm(USER, "old")
    thoughtgraph_storage.save_access(USER, {"old": {"read": [], "write": []}})

    rename_agent(USER, "old", "new")

    assert containers.load(USER)["box"]["agent"] == "new", "the computer was left behind"
    channels = wiresend_chat.load_channels(USER)
    assert channels["lab"]["members"] == [wiresend_chat.USER_SENDER, "new"]
    assert "dm-old" not in channels and channels["dm-new"]["name"] == "new"
    assert list(thoughtgraph_storage.load_access(USER)) == ["new"]
    # and the gc that used to eat the assignment now leaves it alone
    containers.gc_assignments(USER)
    assert containers.load(USER)["box"]["agent"] == "new"


def test_delete_scrubs_shared_channels_but_keeps_the_dm(fab_home):
    make_agent(USER, "doomed")
    wiresend_chat.create_channel(USER, "lab", [wiresend_chat.USER_SENDER, "doomed", "other"])
    wiresend_chat.set_readonly(USER, "lab", "doomed", True)
    wiresend_chat.ensure_dm(USER, "doomed")
    wiresend_chat.append_message(USER, "dm-doomed", "doomed", "text", text="my last words")

    delete_agent(USER, "doomed")

    channels = wiresend_chat.load_channels(USER)
    assert channels["lab"]["members"] == [wiresend_chat.USER_SENDER, "other"]
    assert channels["lab"]["readonly"] == []
    # the DM is the user's own history: it survives whole, and a recreated agent resumes it
    assert channels["dm-doomed"]["members"] == [wiresend_chat.USER_SENDER, "doomed"]
    assert [m["text"] for m in wiresend_chat.read_messages(USER, "dm-doomed")] == ["my last words"]
    assert not (udir(USER) / "agents" / "doomed").exists()


# ---- the whole-store sweep: the guard that needs nobody to remember it ----

def build_agent_everywhere(name: str):
    '''an agent with a footprint in every store that keys by agent name.'''
    make_agent(USER, name)
    containers.save(USER, {"box": {"novnc_port": 6080, "agent": name}})
    wiresend_chat.create_channel(USER, "lab", [wiresend_chat.USER_SENDER, name, "other"])
    wiresend_chat.set_readonly(USER, "lab", name, True)
    wiresend_chat.ensure_dm(USER, name)
    wiresend_chat.append_message(USER, f"dm-{name}", name, "text", text="a word from me")
    wiresend_chat.mark_read(USER, name, f"dm-{name}", 1.0)
    thoughtgraph_storage.save_access(USER, {name: {"read": [], "write": []}})


# the one place a rename deliberately does not reach: the sender field on messages the agent
# already sent. slack and discord show the new name on old messages because they store ids;
# we store names, so the log keeps saying "oldagent". delete this filter to change that
RENAME_BLIND_SPOT = "wiresend/dm-newagent/messages.jsonl"


def test_after_a_rename_no_store_anywhere_still_holds_the_old_name(fab_home):
    build_agent_everywhere("oldagent")
    rename_agent(USER, "oldagent", "newagent")
    leftovers = [p for p in stores_mentioning(fab_home, "oldagent")
                 if not p.endswith(RENAME_BLIND_SPOT)]
    assert leftovers == [], leftovers


# the DM is kept on purpose (the user's own history), so it and the two indexes that name it
# are the only places the name may survive a delete
KEPT_AFTER_DELETE = ("wiresend/dm-", "wiresend/channels.json", "wiresend/readers.json")


def test_after_a_delete_nothing_holds_the_name_except_the_dm_we_keep(fab_home):
    build_agent_everywhere("doomedagent")
    delete_agent(USER, "doomedagent")
    leftovers = [p for p in stores_mentioning(fab_home, "doomedagent")
                 if not any(kept in p for kept in KEPT_AFTER_DELETE)]
    assert leftovers == []


# ---- the websocket api, end to end through the mounted app ----

def test_ws_rejects_a_connection_with_no_cookie(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/corechat/ws") as ws:
            ws.receive_text()


def test_ws_agent_crud_round_trip(client, user, fake_model):
    with client.websocket_connect("/corechat/ws") as ws:
        assert recv(ws)["agents"] == []
        assert send_cmd(ws, cmd="create", name="helper")["agents"][0]["name"] == "helper"
        assert send_cmd(ws, cmd="pin", name="helper", pinned=True)["agents"][0]["pinned"] is True
        payload = send_cmd(ws, cmd="set_model", name="helper",
                       model_server_name="deepseek", model_name="deepseek-v4-flash-vision-exp")
        assert payload["agents"][0]["model_server_name"] == "deepseek"
        assert send_cmd(ws, cmd="set_reasoning_effort", name="helper",
                    reasoning_effort="low")["agents"][0]["reasoning_effort"] == "low"
        assert send_cmd(ws, cmd="set_context_limit", name="helper",
                    context_limit=1234)["agents"][0]["context_limit"] == 1234
        assert send_cmd(ws, cmd="toggle_run", name="helper")["agents"][0]["agent_mode"] is True
        assert send_cmd(ws, cmd="rename", name="helper", new_name="scout")["agents"][0]["name"] == "scout"
        assert (udir(user) / "agents" / "scout").exists()
        assert send_cmd(ws, cmd="delete", name="scout")["agents"] == []
        assert not (udir(user) / "agents" / "scout").exists()


def test_ws_chat_runs_a_turn_and_pushes_the_context(client, user, fake_model):
    fake_model.replies = [{"role": "assistant", "content": "pong"}]
    with client.websocket_connect("/corechat/ws") as ws:
        recv(ws)
        send_cmd(ws, cmd="create", name="helper")
        ws.send_json({"cmd": "chat", "name": "helper", "content": [{"type": "text", "text": "ping"}]})
        payload = recv_until(ws, lambda m: m.get("type") == "messages"
                             and m["messages"][-1]["role"] == "assistant")
        assert payload["messages"][-1]["content"] == "pong"
        assert payload["words"] > 0


def test_ws_get_messages_tails_and_history_backfills(client, user, fake_model):
    with client.websocket_connect("/corechat/ws") as ws:
        recv(ws)
        send_cmd(ws, cmd="create", name="helper")
        agent = get_agent(user, "helper")
        agent.working_context += [user_msg(f"m{i}") for i in range(30)]

        ws.send_json({"cmd": "get_messages", "name": "helper"})
        tail = recv_until(ws, lambda m: m.get("type") == "messages")
        assert len(tail["messages"]) == 20 and tail["total"] == 31
        assert tail["start"] == 11

        ws.send_json({"cmd": "history", "name": "helper", "before": tail["start"]})
        older = recv_until(ws, lambda m: m.get("type") == "history")
        assert older["start"] == 0 and len(older["messages"]) == 11


def test_ws_broadcasts_stay_inside_one_account(client, fab_home, fake_model):
    a_token = register(client, "alice")
    b_token = register(client, "bob")
    client.cookies.set(COOKIE_NAME, a_token)
    with client.websocket_connect("/corechat/ws") as wsa:
        recv(wsa)
        client.cookies.set(COOKIE_NAME, b_token)
        with client.websocket_connect("/corechat/ws") as wsb:
            assert recv(wsb)["agents"] == [], "bob must not see alice's world"
            send_cmd(wsb, cmd="create", name="bobs_agent")
        client.cookies.set(COOKIE_NAME, a_token)
        # alice's socket saw nothing from bob's create
        recv_nothing(wsa)


def test_ws_list_agents_answers_only_the_asking_socket(client, user, fake_model):
    with client.websocket_connect("/corechat/ws") as ws:
        recv(ws)
        send_cmd(ws, cmd="create", name="helper")
        assert send_cmd(ws, cmd="list_agents")["agents"][0]["name"] == "helper"
