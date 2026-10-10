'''end-to-end: one account through all four modules, against the real world — a real deepseek
call and a real docker container. this is the only test that leaves the process.

deliberately NOT a test_* function: it costs an api call and needs a live docker daemon, so
pytest never collects it. run it when you want it:

    venv/bin/python -m hub.test.test_e2e
'''

import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from fab.config import udir
from fab.corechat.back import commands
from fab.corechat.back.api import agents as live_agents
from fab.dockeruse.back.config import workspace_dir
from hub.back.app import app
from hub.test.conftest import point_fab_at, recv, recv_until, register, send_cmd

USER = "e2e"
BOX = "e2e-testbox"
# the moonshot key rate-limits too hard for a suite, so every real call here is deepseek
MODEL = {"model_server_name": "deepseek", "model_name": "deepseek-v4-flash-vision-exp"}

# a real model call and a real container boot are both far slower than anything in-process
REPLY_TIMEOUT = 90
PING_TIMEOUT = 30


def run_tool(agent, name: str, **args) -> str:
    call = {"id": "e2e", "function": {"name": name, "arguments": json.dumps(args)}}
    return asyncio.run(commands.dispatch(agent, call))["content"]


def corechat(client) -> str:
    '''create an agent, switch it to deepseek, and make it actually answer.'''
    with client.websocket_connect("/corechat/ws") as ws:
        assert recv(ws)["agents"] == []
        assert send_cmd(ws, cmd="create", name="helper")["agents"][0]["name"] == "helper"
        assert (udir(USER) / "agents" / "helper").exists()
        assert send_cmd(ws, cmd="set_model", name="helper", **MODEL)["agents"][0]["model_server_name"] == "deepseek"

        ws.send_json({"cmd": "chat", "name": "helper",
                      "content": [{"type": "text", "text": "reply with exactly: pong"}]})
        reply = recv_until(ws, lambda m: m.get("type") == "messages"
                           and m["messages"][-1]["role"] == "assistant", REPLY_TIMEOUT)
        assert "pong" in reply["messages"][-1]["content"], reply["messages"][-1]
    print("corechat: agent created, real deepseek turn answered")
    return "helper"


def thoughtgraph(client, agent):
    '''a granted doc is readable through the agent's own tools; an ungranted one is not.'''
    node = client.post("/thoughtgraph/boards/main/nodes",
                       json={"title": "mission", "kind": "doc"}).json()
    client.put(f"/thoughtgraph/boards/main/nodes/{node['id']}/content",
               json={"content": "the mission is testing"})
    client.post("/thoughtgraph/boards/main/nodes", json={"title": "hidden", "kind": "doc"})
    client.put("/thoughtgraph/access",
               json={"helper": {"read": [{"board": "main", "id": node["id"]}], "write": []}})

    assert "the mission is testing" in run_tool(agent, "GREAD", board="main", ref="mission")
    assert "[ERROR]" in run_tool(agent, "GREAD", board="main", ref="hidden")
    print("thoughtgraph: grant enforced — granted doc readable, ungranted refused")


def wiresend(client, agent):
    '''a channel message reaches the agent's context as a ping.'''
    with client.websocket_connect("/wiresend/ws") as ws:
        ws.send_json({"cmd": "create_channel", "name": "lab", "agents": ["helper"]})
        channels = recv_until(ws, lambda m: m.get("type") == "channels" and m["channels"])
        assert channels["channels"][0]["name"] == "lab"
        ws.send_json({"cmd": "chat_send", "channel": channels["channels"][0]["id"], "text": "hi agent"})
        assert recv_until(ws, lambda m: m.get("type") == "chat_message")["message"]["text"] == "hi agent"

    # the ping wakes a turn, which drains it into the on-disk context (agent.inbox itself
    # races with that drain, so the file is the thing to watch)
    context = udir(USER) / "agents" / "helper" / "working.jsonl"
    deadline = time.time() + PING_TIMEOUT
    while time.time() < deadline and "[wiresend]" not in context.read_text():
        time.sleep(0.5)
    assert "[wiresend]" in context.read_text(), "the ping never reached the agent's context"
    print("wiresend: channel chat works, agent got pinged")


def dockeruse(client, agent):
    '''the whole container lifecycle on real docker, then the agent working inside it.'''
    assert client.post("/dockeruse/containers", json={"name": BOX}).status_code == 200
    try:
        assert client.post(f"/dockeruse/containers/{BOX}/assign", json={"agent": "helper"}).status_code == 200

        # the agent's own tools, against a live container — the one path no stub can cover
        assert "hello from the box" in run_tool(agent, "EXEC", command="echo hello from the box")
        run_tool(agent, "WRITE", file="notes.txt", content="written by the agent")
        assert "written by the agent" in run_tool(agent, "READ", file="notes.txt")
        run_tool(agent, "EDIT", file="notes.txt", old="written", new="edited", which="0")
        assert (workspace_dir(USER, BOX) / "notes.txt").read_text() == "edited by the agent"
        assert "running" in run_tool(agent, "DOCKER_STATUS")
        print("dockeruse: EXEC/READ/WRITE/EDIT all work inside the real container")

        assert client.post(f"/dockeruse/containers/{BOX}/stop").status_code == 200
        listed = client.get("/dockeruse/containers").json()["containers"][0]
        assert listed["running"] is False and listed["agent"] == "helper"
        assert client.post(f"/dockeruse/containers/{BOX}/start").status_code == 200
        assert client.get("/dockeruse/containers").json()["containers"][0]["running"] is True
        print("dockeruse: create/assign/stop/start all work on real docker")
    finally:
        client.delete(f"/dockeruse/containers/{BOX}", params={"workspace": "1"})


def main():
    # a throwaway home, like every other suite — a test run must never touch the real ~/.fab
    home = Path(tempfile.mkdtemp(prefix="fab_e2e_"))
    point_fab_at(home, setattr)
    try:
        with TestClient(app) as client:
            register(client, USER)
            name = corechat(client)
            agent = live_agents[USER][name]
            thoughtgraph(client, agent)
            wiresend(client, agent)
            dockeruse(client, agent)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print("test_e2e OK")


if __name__ == "__main__":
    main()
