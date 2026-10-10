'''dockeruse: the containers store, the lifecycle rules, and the agent's file tools.

docker itself is stubbed — FakeContainer keeps its files in a dict and answers the one shell
probe the file tools make. that is enough to exercise every branch of the tool logic; the
real daemon is covered by test_e2e.'''

import asyncio
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from fab.corechat.back import commands
from fab.dockeruse.back import containers
from fab.dockeruse.back import tools as dockeruse_tools
from fab.dockeruse.back.config import workspace_dir, workspace_path
from hub.test.conftest import StubAgent, make_agent

USER = "tester"
AGENT = "helper"
BOX = "box"


class FakeContainer:
    '''a container without a daemon. files live in a dict keyed by their in-container path,
    and run() answers only the `test -e` probe the file tools make.'''

    def __init__(self, name: str, workspace: Path, image: str = "fab_sandbox", novnc_port: int = 6080):
        self.name = name
        self.workspace = workspace
        self.image = image
        self.novnc_port = novnc_port
        self.files = {}      # {str: str} — in-container path -> contents
        self.commands = []   # [str] — every shell line run, so tests can assert on quoting
        self.actions = []    # [(str, tuple)] — mouse/keyboard calls, in order
        self.lifecycle = []  # [str] — start / stop / destroy, in order
        self.present = False       # what exists() reports
        self.rebuild_needed = False
        self.start_error = None    # an exception for the failed-first-boot case

    def run(self, cmd: str) -> str:
        self.commands.append(cmd)
        if cmd.startswith("test -e "):
            # shlex.split is the proof of correct quoting: an unquoted path with a space or
            # an apostrophe would not survive as a single token here
            return "y\n" if shlex.split(cmd)[2] in self.files else ""
        return ""

    def read_file(self, path: str) -> str:
        return self.files.get(path, "")

    def write_file(self, path: str, content: str):
        self.files[path] = content

    # every mouse/keyboard tool lands here as (method, args) instead of an xdotool call
    def __getattr__(self, attr: str):
        if attr not in ("move", "click", "double_click", "mousedown", "mouseup", "scroll",
                        "type_text", "key", "screenshot"):
            raise AttributeError(attr)
        return lambda *args: self.actions.append((attr, args))

    def exists(self) -> bool:
        return self.present

    def _needs_rebuild(self) -> bool:
        return self.rebuild_needed

    def start(self):
        if self.start_error:
            raise self.start_error
        self.lifecycle.append("start")
        self.present = True
        self.workspace.mkdir(parents=True, exist_ok=True)

    def stop(self):
        self.lifecycle.append("stop")

    def destroy(self):
        self.lifecycle.append("destroy")
        self.present = False


@pytest.fixture
def fake_docker(fab_home, monkeypatch):
    # handle() builds and caches these, so every module path gets the same object a test holds
    monkeypatch.setattr(containers, "Container", FakeContainer)
    monkeypatch.setattr(containers, "daemon_state", lambda: (set(), {}))
    return fab_home


@pytest.fixture
def assigned(fake_docker, monkeypatch) -> FakeContainer:
    '''a running container assigned to the agent — the state every file tool needs.'''
    make_agent(USER, AGENT)
    containers.save(USER, {BOX: {"novnc_port": 6080, "agent": AGENT}})
    box = containers.handle(USER, BOX)
    box.present = True
    box.workspace.mkdir(parents=True, exist_ok=True)  # a real start() would have made it
    monkeypatch.setattr(containers, "is_running", lambda name: True)
    return box


def run_tool(name: str, agent: StubAgent, **args) -> str:
    return asyncio.run(commands.COMMANDS[name]["handler"](args, agent))


@pytest.fixture
def tool_agent() -> StubAgent:
    return StubAgent(USER, AGENT)


# ---- names and paths: the two things that become docker names and host paths ----

@pytest.mark.parametrize("name", ["ok", "a-b.c_d", "x" * 64])
def test_valid_container_names(fake_docker, name):
    containers.validate_name(name)


@pytest.mark.parametrize("name", ["", "a", "-leading", ".leading", "has space", "sl/ash", "x" * 65])
def test_invalid_container_names_are_refused(fake_docker, name):
    # the name becomes a docker container name AND a folder path
    with pytest.raises(ValueError, match="invalid name"):
        containers.validate_name(name)


def test_workspace_paths_accept_the_container_view(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert workspace_path(ws, "/home/agent") == ws.resolve()
    assert workspace_path(ws, "/home/agent/deep/file.txt") == (ws / "deep" / "file.txt").resolve()
    assert workspace_path(ws, "plain.txt") == (ws / "plain.txt").resolve()


@pytest.mark.parametrize("escape", ["../../.env", "/etc/passwd", "deep/../../../outside"])
def test_workspace_paths_cannot_escape(tmp_path, escape):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(ValueError, match="escapes workspace"):
        workspace_path(ws, escape)


# ---- the store and the lifecycle ----

def test_create_allocates_a_port_and_boots_once(fake_docker):
    entry = containers.create(USER, BOX)
    assert entry == {"novnc_port": 6080, "agent": None}
    assert containers.handle(USER, BOX).lifecycle == ["start"]
    with pytest.raises(ValueError, match="already exists"):
        containers.create(USER, BOX)


def test_a_failed_first_boot_leaves_no_entry_behind(fake_docker, monkeypatch):
    # otherwise a dead dockerd would squat the name forever
    def exploding(name, workspace, image="fab_sandbox", novnc_port=6080):
        box = FakeContainer(name, workspace, image, novnc_port)
        box.start_error = RuntimeError("dockerd is down")
        return box
    monkeypatch.setattr(containers, "Container", exploding)
    with pytest.raises(RuntimeError):
        containers.create(USER, BOX)
    assert containers.load(USER) == {}
    assert (USER, BOX) not in containers._handles


def test_ports_are_allocated_across_every_user(fake_docker):
    containers.create("alice", "one")
    containers.create("bob", "two")
    assert containers.load("alice")["one"]["novnc_port"] == 6080
    assert containers.load("bob")["two"]["novnc_port"] == 6081, "ports are a host resource"


def test_destroy_removes_the_entry_and_optionally_the_workspace(fake_docker):
    containers.create(USER, BOX)
    workspace = workspace_dir(USER, BOX)
    (workspace / "artifact.txt").write_text("work output")
    containers.destroy(USER, BOX)
    assert containers.load(USER) == {}
    assert workspace.exists(), "the workspace survives unless it is explicitly asked for"

    containers.create(USER, BOX)
    containers.destroy(USER, BOX, workspace=True)
    assert not workspace.exists()


def test_destroy_refuses_a_container_that_does_not_exist(fake_docker):
    with pytest.raises(ValueError, match="no container"):
        containers.destroy(USER, "ghost")


def test_one_agent_one_computer(fake_docker):
    make_agent(USER, AGENT)
    containers.save(USER, {"first": {"novnc_port": 6080, "agent": None},
                           "second": {"novnc_port": 6081, "agent": None}})
    containers.assign(USER, "first", AGENT)
    containers.assign(USER, "second", AGENT)
    stored = containers.load(USER)
    assert stored["first"]["agent"] is None, "reassignment takes the agent off its old computer"
    assert stored["second"]["agent"] == AGENT
    assert containers.container_for_agent(USER, AGENT) == "second"
    containers.unassign(USER, "second")
    assert containers.container_for_agent(USER, AGENT) is None


def test_assign_refuses_unknown_names(fake_docker):
    containers.save(USER, {BOX: {"novnc_port": 6080, "agent": None}})
    with pytest.raises(ValueError, match="no agent named"):
        containers.assign(USER, BOX, "ghost")
    with pytest.raises(ValueError, match="no container named"):
        containers.assign(USER, "ghost_box", AGENT)


def test_assignments_to_deleted_agents_are_collected(fake_docker):
    containers.save(USER, {BOX: {"novnc_port": 6080, "agent": "vanished"}})
    containers.gc_assignments(USER)
    assert containers.load(USER)[BOX]["agent"] is None


def test_the_agent_start_is_a_strict_resume(fake_docker):
    containers.save(USER, {BOX: {"novnc_port": 6080, "agent": AGENT}})
    box = containers.handle(USER, BOX)
    with pytest.raises(ValueError, match="doesn't exist yet"):
        containers.agent_start(USER, BOX)          # never creates
    box.present, box.rebuild_needed = True, True
    with pytest.raises(ValueError, match="image changed"):
        containers.agent_start(USER, BOX)          # never rebuilds
    box.rebuild_needed = False
    containers.agent_start(USER, BOX)
    assert box.lifecycle == ["start"]


# ---- the daemon is the truth, not the json ----

# fab_home, not fake_docker: this is the one test that wants the REAL daemon_state, with
# only the docker ps call itself stubbed out
def test_daemon_state_parses_docker_ps(fab_home, monkeypatch):
    monkeypatch.setattr(containers.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout="alive running 127.0.0.1:6081->6080/tcp\ndead exited \n"))
    running, ports = containers.daemon_state()
    assert running == {"alive"} and ports == {"alive": 6081}


def test_list_containers_trusts_the_daemon_over_a_drifted_json(fake_docker, monkeypatch):
    containers.save(USER, {BOX: {"novnc_port": 9999, "agent": None}})
    monkeypatch.setattr(containers, "daemon_state", lambda: ({BOX}, {BOX: 6083}))
    listed = containers.list_containers(USER)
    assert listed == [{"name": BOX, "novnc_port": 6083, "agent": None, "running": True}]
    assert containers.load(USER)[BOX]["novnc_port"] == 6083, "the correction is persisted"


# ---- the agent's tools ----

def test_tools_explain_themselves_when_there_is_no_computer(fake_docker, tool_agent):
    assert "no docker assigned" in run_tool("LOOK", tool_agent)
    assert "no docker assigned" in run_tool("EXEC", tool_agent, command="ls")
    assert "no docker assigned" in run_tool("DOCKER_STATUS", tool_agent)


def test_tools_explain_themselves_when_the_computer_is_paused(fake_docker, tool_agent, monkeypatch):
    make_agent(USER, AGENT)
    containers.save(USER, {BOX: {"novnc_port": 6080, "agent": AGENT}})
    monkeypatch.setattr(containers, "is_running", lambda name: False)
    assert "paused" in run_tool("READ", tool_agent, file="x")
    assert "paused" in run_tool("DOCKER_STATUS", tool_agent)


def test_docker_status_start_and_stop(assigned, tool_agent, monkeypatch):
    assert "running" in run_tool("DOCKER_STATUS", tool_agent)
    assert "already running" in run_tool("DOCKER_START", tool_agent)
    assert "paused" in run_tool("DOCKER_STOP", tool_agent)
    assert assigned.lifecycle == ["stop"]


def test_write_read_and_edit_round_trip(assigned, tool_agent):
    run_tool("WRITE", tool_agent, file="notes.txt", content="alpha beta alpha")
    assert assigned.files["/home/agent/notes.txt"] == "alpha beta alpha"
    numbered = run_tool("READ", tool_agent, file="notes.txt")
    assert "   1| alpha beta alpha" in numbered
    run_tool("EDIT", tool_agent, file="notes.txt", old="alpha", new="gamma", which="1")
    assert assigned.files["/home/agent/notes.txt"] == "alpha beta gamma", "'1' is the second one"
    run_tool("EDIT", tool_agent, file="notes.txt", old="a", new="A", which="all")
    assert assigned.files["/home/agent/notes.txt"] == "AlphA betA gAmmA"


def test_read_takes_a_line_range(assigned, tool_agent):
    run_tool("WRITE", tool_agent, file="lines.txt", content="one\ntwo\nthree\nfour")
    out = run_tool("READ", tool_agent, file="lines.txt", start=2, end=3)
    assert "two" in out and "three" in out and "four" not in out


def test_file_tools_report_a_missing_file_and_a_missing_match(assigned, tool_agent):
    assert "file not found" in run_tool("READ", tool_agent, file="ghost.txt")
    assert "file not found" in run_tool("EDIT", tool_agent, file="ghost.txt",
                                        old="a", new="b", which="0")
    run_tool("WRITE", tool_agent, file="real.txt", content="contents")
    assert "text not found" in run_tool("EDIT", tool_agent, file="real.txt",
                                        old="absent", new="b", which="0")
    assert "only 1 found" in run_tool("EDIT", tool_agent, file="real.txt",
                                      old="contents", new="b", which="5")


def test_a_filename_with_an_apostrophe_survives_the_shell(assigned, tool_agent):
    # the path is interpolated into a bash line; unquoted, "don't.txt" ends the quote early
    run_tool("WRITE", tool_agent, file="don't.txt", content="tricky")
    assert "tricky" in run_tool("READ", tool_agent, file="don't.txt")
    assert any("don't.txt" in shlex.split(c)[2] for c in assigned.commands if c.startswith("test -e"))


@pytest.mark.parametrize("escape", ["../../.env", "/etc/passwd"])
def test_file_tools_cannot_escape_the_workspace(assigned, tool_agent, escape):
    with pytest.raises(ValueError, match="escapes workspace"):
        run_tool("READ", tool_agent, file=escape)


def test_tasks_reports_an_empty_registry(assigned, tool_agent):
    assert "no background tasks" in run_tool("TASKS", tool_agent)


# ---- the vnc proxy: one user must never reach another's desktop ----

def test_vnc_ports_are_owned_per_user(fake_docker):
    from fab.dockeruse.back.api import _owned_vnc_port
    containers.save("alice", {"a": {"novnc_port": 6080, "agent": None}})
    containers.save("bob", {"b": {"novnc_port": 6081, "agent": None}})
    assert _owned_vnc_port("alice", "6080") == 6080
    assert _owned_vnc_port("alice", "6081") is None, "that is bob's desktop"
    assert _owned_vnc_port("alice", "not-a-port") is None


def test_the_vnc_route_refuses_a_port_you_do_not_own(client, user, fab_home):
    assert client.get("/dockeruse/vnc/6080/vnc.html").status_code == 403


# ---- mouse and keyboard: thin wrappers, but every one has to reach the container ----

@pytest.mark.parametrize("tool, args, expected", [
    ("MOVE", {"x": 120, "y": 340}, ("move", (120, 340))),
    ("LCLICK", {}, ("click", (1,))),
    ("RCLICK", {}, ("click", (3,))),
    ("DCLICK", {}, ("double_click", ())),
    ("LDOWN", {}, ("mousedown", (1,))),
    ("LUP", {}, ("mouseup", (1,))),
    ("RDOWN", {}, ("mousedown", (3,))),
    ("RUP", {}, ("mouseup", (3,))),
    ("SCROLLUP", {}, ("scroll", ("up",))),
    ("SCROLLDOWN", {}, ("scroll", ("down",))),
    ("TYPE", {"text": "hello world"}, ("type_text", ("hello world",))),
    ("KEY", {"keys": ["ctrl", "c"]}, ("key", ("ctrl+c",))),
])
def test_input_tools_reach_the_container(assigned, tool_agent, tool, args, expected):
    assert run_tool(tool, tool_agent, **args) == "ok", "perception is explicit; actions just ack"
    assert assigned.actions == [expected]


def test_input_tools_refuse_without_a_computer(fake_docker, tool_agent):
    assert "no docker assigned" in run_tool("TYPE", tool_agent, text="into the void")


# ---- terminal perception ----

def test_term_returns_the_log_and_term_last_command_only_the_new_part(assigned, tool_agent):
    log = assigned.workspace / "term.log"
    log.write_text("old output\n")
    assert "old output" in run_tool("TERM", tool_agent)

    assigned._term_offset = log.stat().st_size       # what a TYPE/KEY marks
    log.write_text("old output\nfresh output\n")
    out = run_tool("TERM_LAST_COMMAND", tool_agent)
    assert "fresh output" in out and "old output" not in out
    assert "no new output" in run_tool("TERM_LAST_COMMAND", tool_agent), "the offset advances"


def test_term_says_so_when_there_is_no_log_yet(assigned, tool_agent):
    assert "no terminal output" in run_tool("TERM", tool_agent)


# ---- the rest routes (the watch page's door, as opposed to the functions behind it) ----

def test_container_rest_routes(client, user, fab_home, monkeypatch):
    monkeypatch.setattr(containers, "Container", FakeContainer)
    monkeypatch.setattr(containers, "daemon_state", lambda: (set(), {}))
    make_agent(user, AGENT)
    assert client.post("/dockeruse/containers", json={"name": BOX}).status_code == 200
    assert client.get("/dockeruse/agents").json()["agents"] == [AGENT]

    assert client.post(f"/dockeruse/containers/{BOX}/assign", json={"agent": AGENT}).status_code == 200
    assert client.get("/dockeruse/containers").json()["containers"][0]["agent"] == AGENT
    assert client.post(f"/dockeruse/containers/{BOX}/stop").status_code == 200
    assert client.post(f"/dockeruse/containers/{BOX}/start").status_code == 200
    assert containers.handle(user, BOX).lifecycle == ["start", "stop", "start"]
    assert client.post(f"/dockeruse/containers/{BOX}/unassign").status_code == 200
    assert client.get("/dockeruse/containers").json()["containers"][0]["agent"] is None
    assert client.delete(f"/dockeruse/containers/{BOX}").status_code == 200
    assert client.get("/dockeruse/containers").json()["containers"] == []
