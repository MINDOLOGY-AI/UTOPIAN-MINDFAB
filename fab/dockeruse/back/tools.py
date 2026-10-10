'''dockeruse tools: the computer commands, registered into corechat's central COMMANDS.
corechat must import this module for registration to happen (the plumbing line).
schemas copied from old_fab adapter.py; the auto-feedback claims are gone — every
action returns plain "ok", perception is explicit (LOOK/TERM/TERM_LAST_COMMAND).

handlers resolve the agent's container through containers.json: the container whose
"agent" is this agent's name. no assignment / paused containers get guidance strings,
never exceptions. everything docker-touching runs in asyncio.to_thread so a slow
xdotool or screenshot never stalls corechat's event loop for the other agents.'''

import asyncio
import base64
import shlex

from fab.corechat.back.commands import register, schema
from fab.dockeruse.back import containers
from fab.dockeruse.back.config import EXEC_TIMEOUT, workspace_path

# background EXEC tasks, per container name: id -> {command, log, status, exit, task}
_bg_tasks: dict[str, dict[int, dict]] = {}
_bg_next_id: dict[str, int] = {}


# ---- the guard every computer tool shares ----

# returns (container, None) or (None, guidance string)
def _computer(user: str, agent_name: str) -> tuple:
    name = containers.container_for_agent(user, agent_name)
    if name is None:
        return None, "[no docker assigned to you — the user assigns one on the dockeruse page]"
    c = containers.handle(user, name)
    if not containers.is_running(c.name):
        return None, "[your computer is paused — DOCKER_START resumes it]"
    return c, None


# ---- file tools (through docker exec as root, confined to the workspace) ----

def _container_file(c, file: str) -> str:
    # workspace host path -> the same file's path inside the container.
    # ALL file ops go through the container (docker exec as root): the container
    # is the single writer, so ownership is uniform and host-side permission
    # mismatches can't happen.
    rel = workspace_path(c.workspace, file).relative_to(c.workspace.resolve())
    return f"/home/agent/{rel}"


def _read_file(c, args: dict) -> str:
    cpath = _container_file(c, args["file"])
    if c.run(f"test -e {shlex.quote(cpath)} && echo y").strip() != "y":
        return f"[READ {args['file']}] file not found"
    content = c.read_file(cpath)
    lines = content.split("\n")
    start = int(args["start"]) - 1 if "start" in args else 0
    end = int(args["end"]) if "end" in args else len(lines)
    numbered = [f"{i + 1 + start:4d}| {line}" for i, line in enumerate(lines[start:end])]
    return f"[READ {args['file']}]\n" + "\n".join(numbered)


def _edit_file(c, args: dict) -> str:
    file, old, new, which = args["file"], args["old"], args["new"], args["which"]
    cpath = _container_file(c, file)
    if c.run(f"test -e {shlex.quote(cpath)} && echo y").strip() != "y":
        return f"[EDIT {file}] file not found"
    content = c.read_file(cpath)
    count = content.count(old)
    if count == 0:
        return f"[EDIT {file}] text not found"
    if which == "all":
        result = content.replace(old, new)
    else:
        n = int(which)
        if n >= count:
            return f"[EDIT {file}] occurrence {n} requested but only {count} found (0-indexed)"
        idx = -1
        for _ in range(n + 1):
            idx = content.index(old, idx + 1)
        result = content[:idx] + new + content[idx + len(old):]
    c.write_file(cpath, result)
    return f"[EDIT {file}] done"


# ---- background EXEC (the deposit-based task registry) ----

async def _exec_bg_spawn(agent, c, command: str, notify: bool) -> int:
    """Spawn a docker exec as an asyncio task; stream output to workspace/exec_logs/{id}.log.
    notify=True: agent.deposit the finish note. foreground callers spawn with False and
    flip it on only if the command outlives EXEC_TIMEOUT (demotion) — no double-report."""
    tasks = _bg_tasks.setdefault(c.name, {})
    tid = _bg_next_id.get(c.name, 1)
    _bg_next_id[c.name] = tid + 1
    log_rel = f"exec_logs/{tid}.log"
    log_host = c.workspace / log_rel
    log_host.parent.mkdir(parents=True, exist_ok=True)
    entry: dict = {"command": command, "log": log_rel, "status": "running", "exit": None,
                   "notify": notify}
    tasks[tid] = entry

    async def runner():
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", c.name, "bash", "-c", command,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        with open(log_host, "wb") as f:
            f.write(f"$ {command}\n".encode())
            while True:
                assert proc.stdout
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                f.flush()
            f.write(f"\n[exit {await proc.wait()}]\n".encode())
        entry["exit"] = proc.returncode
        entry["status"] = "done"
        # user visibility: note the finish in the VNC terminal log too
        await asyncio.to_thread(
            c.append_file, "/home/agent/term.log",
            f"\n$ {command}\n[background exec {tid} finished, exit {proc.returncode}] log: /home/agent/{log_rel}")
        # the agent finds out via deposit — it reacts on its own next turn.
        # the notify check is LAST so a demoted foreground exec flips it before we get here
        if entry["notify"]:
            agent.deposit("EXEC", f"[EXEC BG {tid} finished, exit {proc.returncode}] log: /home/agent/{log_rel}\n"
                                  f"last output:\n{_bg_log_tail(c, entry)}")

    entry["task"] = asyncio.create_task(runner())
    return tid


def _bg_log_tail(c, entry: dict, chars: int = 1500) -> str:
    log_host = c.workspace / entry["log"]
    if not log_host.exists():
        return ""
    return log_host.read_text(errors="replace")[-chars:]


async def _exec(args: dict, agent) -> str:
    """foreground: wait up to EXEC_TIMEOUT; over the limit the command keeps
    running as a background task instead of being killed."""
    c, err = _computer(agent.user, agent.name)
    if err:
        return err
    command = args["command"]
    if args.get("background"):
        tid = await _exec_bg_spawn(agent, c, command, notify=True)
        return (f"[EXEC BG started: id {tid}] log: /home/agent/exec_logs/{tid}.log — "
                f"you'll be notified when it finishes; peek with EXEC 'tail /home/agent/exec_logs/{tid}.log'")

    tid = await _exec_bg_spawn(agent, c, command, notify=False)
    entry = _bg_tasks[c.name][tid]
    done, _ = await asyncio.wait({entry["task"]}, timeout=EXEC_TIMEOUT)
    if not done:
        # demote to background — asyncio.wait does not cancel the runner
        entry["notify"] = True
        note = (f"[EXEC $ {command}]\nstill running after {EXEC_TIMEOUT}s — moved to background id {tid}. "
                f"you'll be notified when it finishes; peek with EXEC 'tail /home/agent/{entry['log']}'\n"
                f"output so far:\n{_bg_log_tail(c, entry)}")
        await asyncio.to_thread(c.append_file, "/home/agent/term.log",
                                f"\n$ {command}\n[moved to background exec {tid}]")
        return note

    # foreground completion: return the output (minus the log's "$ cmd" header).
    # notify stays False — the tool result IS the notification
    raw = _bg_log_tail(c, entry, chars=10_000_000)
    output = raw.split("\n", 1)[1] if "\n" in raw else raw
    await asyncio.to_thread(c.append_file, "/home/agent/term.log", f"\n$ {command}\n{output}")
    trimmed = output[-5000:] if len(output) > 5000 else output
    return f"[EXEC $ {command}]\n{trimmed}"


async def _tasks(args: dict, agent) -> str:
    name = containers.container_for_agent(agent.user, agent.name)
    tasks = _bg_tasks.get(name, {}) if name else {}
    if not tasks:
        return "[TASKS] no background tasks"
    lines = ["[TASKS]"]
    for tid, e in tasks.items():
        lines.append(f"  {tid}: {e['status']} (exit {e['exit']}) log /home/agent/{e['log']} — {e['command'][:80]}")
    return "\n".join(lines)


# ---- perception ----

async def _look(args: dict, agent) -> str:
    c, err = _computer(agent.user, agent.name)
    if err:
        return err
    path = await asyncio.to_thread(c.screenshot)
    png = await asyncio.to_thread(path.read_bytes)
    # tool messages carry strings only — the image rides the inbox as a user
    # message with a "[screenshot]" marker, seen on the very next turn
    agent.inbox.append({"role": "user", "content": [
        {"type": "text", "text": "[screenshot]"},
        {"type": "image_url", "image_url": {
            "url": f"data:image/png;base64,{base64.standard_b64encode(png).decode('utf-8')}"}},
    ]})
    return "[image result]"


async def _term(args: dict, agent) -> str:
    c, err = _computer(agent.user, agent.name)
    if err:
        return err
    log = c.workspace / "term.log"
    output = log.read_text()[-5000:] if log.exists() else "[no terminal output]"
    return f"[TERM]\n{output}"


async def _term_last_command(args: dict, agent) -> str:
    c, err = _computer(agent.user, agent.name)
    if err:
        return err
    log = c.workspace / "term.log"
    if not log.exists():
        return "[TERM_LAST_COMMAND]\n[no terminal output]"
    with open(log, "rb") as f:
        f.seek(c._term_offset)
        new_bytes = f.read()
    c._term_offset = log.stat().st_size
    if not new_bytes:
        return "[TERM_LAST_COMMAND]\n(no new output since last keyboard command)"
    return f"[TERM_LAST_COMMAND]\n{new_bytes.decode('utf-8', errors='replace')[-5000:]}"


# ---- mouse / keyboard (plain "ok" — perception is explicit) ----

def _action(fn, *fn_args):
    # every mouse/keyboard handler is this: guard, run in a thread, "ok"
    async def handler(args: dict, agent) -> str:
        c, err = _computer(agent.user, agent.name)
        if err:
            return err
        await asyncio.to_thread(fn, c, *fn_args[0](args))
        return "ok"
    return handler


# ---- files ----

async def _read(args: dict, agent) -> str:
    c, err = _computer(agent.user, agent.name)
    if err:
        return err
    return await asyncio.to_thread(_read_file, c, args)


async def _write(args: dict, agent) -> str:
    c, err = _computer(agent.user, agent.name)
    if err:
        return err
    await asyncio.to_thread(c.write_file, _container_file(c, args["file"]), args["content"])
    return f"[WRITE {args['file']}] {len(args['content'])} chars written"


async def _edit(args: dict, agent) -> str:
    c, err = _computer(agent.user, agent.name)
    if err:
        return err
    return await asyncio.to_thread(_edit_file, c, args)


# ---- computer lifecycle (the agent's share: status, strict-resume start, pause) ----

async def _docker_status(args: dict, agent) -> str:
    name = containers.container_for_agent(agent.user, agent.name)
    if name is None:
        return "[DOCKER_STATUS] no docker assigned to you"
    state = "running" if containers.is_running(name) else "paused"
    return f"[DOCKER_STATUS] {name} — {state}"


async def _docker_start(args: dict, agent) -> str:
    name = containers.container_for_agent(agent.user, agent.name)
    if name is None:
        return "[DOCKER_START] no docker assigned to you — the user assigns one on the dockeruse page"
    if containers.is_running(name):
        return f"[DOCKER_START] {name} is already running"
    try:
        await asyncio.to_thread(containers.agent_start, agent.user, name)
    except ValueError as e:
        return f"[DOCKER_START] {e}"
    return (f"[DOCKER_START] {name} running. you have computer tools: "
            f"LOOK, TERM, TYPE, KEY, mouse commands, EXEC, READ/WRITE/EDIT.")


async def _docker_stop(args: dict, agent) -> str:
    name = containers.container_for_agent(agent.user, agent.name)
    if name is None:
        return "[DOCKER_STOP] no docker assigned to you"
    if not containers.is_running(name):
        return f"[DOCKER_STOP] {name} was not running"
    await asyncio.to_thread(containers.stop, agent.user, name)
    return f"[DOCKER_STOP] {name} paused — state preserved, DOCKER_START resumes it in seconds."


# ---- schemas (wording copied from old adapter.py COMMANDS) ----

_X = {"type": "integer"}
_S = {"type": "string"}

register("MOVE", schema("MOVE", "Move cursor to absolute screen position (pixels).",
    {"x": _X, "y": _X}, ["x", "y"]), _action(lambda c, x, y: c.move(x, y), lambda a: (int(a["x"]), int(a["y"]))))
register("LCLICK", schema("LCLICK", "Left click at current cursor position.", {}),
    _action(lambda c: c.click(1), lambda a: ()))
register("RCLICK", schema("RCLICK", "Right click at current cursor position.", {}),
    _action(lambda c: c.click(3), lambda a: ()))
register("DCLICK", schema("DCLICK", "Double-click left mouse at current cursor position.", {}),
    _action(lambda c: c.double_click(), lambda a: ()))
register("LDOWN", schema("LDOWN", "Press and hold left mouse button.", {}),
    _action(lambda c: c.mousedown(1), lambda a: ()))
register("LUP", schema("LUP", "Release left mouse button.", {}),
    _action(lambda c: c.mouseup(1), lambda a: ()))
register("RDOWN", schema("RDOWN", "Press and hold right mouse button.", {}),
    _action(lambda c: c.mousedown(3), lambda a: ()))
register("RUP", schema("RUP", "Release right mouse button.", {}),
    _action(lambda c: c.mouseup(3), lambda a: ()))
register("SCROLLUP", schema("SCROLLUP", "Scroll up in the active window.", {}),
    _action(lambda c: c.scroll("up"), lambda a: ()))
register("SCROLLDOWN", schema("SCROLLDOWN", "Scroll down in the active window.", {}),
    _action(lambda c: c.scroll("down"), lambda a: ()))

register("TYPE", schema("TYPE", "Type literal text via keyboard. No escaping needed.",
    {"text": _S}, ["text"]), _action(lambda c, t: c.type_text(t), lambda a: (a.get("text", ""),)))
register("KEY", schema("KEY", "Press a key combo. Each entry is one X11 keysym (Return, BackSpace, Tab, Escape, Delete, Up, Down, Left, Right, ctrl, shift, alt, etc.). All keys are pressed together.",
    {"keys": {"type": "array", "items": _S}}, ["keys"]),
    _action(lambda c, k: c.key(k), lambda a: ("+".join(a.get("keys", [])),)))

register("LOOK", schema("LOOK", "Take a screenshot and return it as the tool_result.", {}), _look)
register("TERM", schema("TERM", "Return the last 5000 chars of terminal output (full log, including history).", {}), _term)
register("TERM_LAST_COMMAND", schema("TERM_LAST_COMMAND", "Return only terminal output since your last keyboard command (TYPE/KEY). Use this to see what a command printed without getting old output mixed in.", {}), _term_last_command)

register("EXEC", schema("EXEC", "Run a shell command directly inside your docker container. Returns stdout+stderr. Use this for ALL terminal work (ls, pip install, git, python, curl, etc.) — do NOT TYPE commands into the terminal. Foreground calls have a 30s limit: over that the command is NOT killed — it's moved to a background task (you get an id + log path) and you're notified when it finishes. For long jobs (training, downloads, big installs) pass background:true from the start. Output is also logged to term.log so the user can see it in the VNC terminal later.",
    {"command": _S, "background": {"type": "boolean"}}, ["command"]), _exec)
register("TASKS", schema("TASKS", "List your background EXEC tasks: id, status (running/done), exit code, command, log path.", {}), _tasks)

register("READ", schema("READ", "Read file in workspace with line numbers. Optional 1-indexed start/end.",
    {"file": _S, "start": _X, "end": _X}, ["file"]), _read)
register("WRITE", schema("WRITE", "Overwrite a file in workspace with content. No escaping needed.",
    {"file": _S, "content": _S}, ["file", "content"]), _write)
register("EDIT", schema("EDIT", "Replace text in a workspace file. 'which' is '0','1',... (0-indexed occurrence) or 'all'.",
    {"file": _S, "old": _S, "new": _S, "which": _S}, ["file", "old", "new", "which"]), _edit)

register("DOCKER_STATUS", schema("DOCKER_STATUS", "Show your assigned computer: its name and whether it is running or paused — or that you have no docker assigned.", {}), _docker_status)
register("DOCKER_START", schema("DOCKER_START", "Resume your assigned computer (it keeps all its state and installed packages). Only resumes — the user creates computers on the dockeruse page. Errors if you have no docker assigned or it was never created.", {}), _docker_start)
register("DOCKER_STOP", schema("DOCKER_STOP", "Pause your assigned computer when you no longer need it, to save resources. State is preserved — DOCKER_START resumes it in seconds.", {}), _docker_stop)
