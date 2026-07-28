from pathlib import Path
import json

from fab.F4B.back import storage
from fab.INT3RF4CE.back.config import DATA_DIR


# prompt blocks configuration, per user: DATA_DIR / {user} / config / {prompts,specific}
def _prompts_dir(user: str) -> Path:
    return DATA_DIR / user / "config" / "prompts"


def _specific_dir(user: str) -> Path:
    return DATA_DIR / user / "config" / "specific"


def _ensure_default_prompts(user: str):
    """Create default prompt files in the user's prompts dir if they don't exist."""
    prompts = _prompts_dir(user)
    prompts.mkdir(parents=True, exist_ok=True)

    global_path = prompts / "global_prompt.md"
    if not global_path.exists():
        global_path.write_text(_DEFAULT_GLOBAL_PROMPT)

    chat_path = prompts / "chat_mode_prompt.md"
    if not chat_path.exists():
        chat_path.write_text(_DEFAULT_CHAT_MODE_PROMPT)

    auto_path = prompts / "auto_turn_prompt.md"
    if not auto_path.exists():
        auto_path.write_text(_DEFAULT_AUTO_TURN_PROMPT)

    summary_path = prompts / "summarization_prompt.md"
    if not summary_path.exists():
        summary_path.write_text(_DEFAULT_SUMMARIZATION_PROMPT)


_DEFAULT_GLOBAL_PROMPT = """\
you are connected to INT3RF4CE, a software layer that lets you use a computer.
you will be given a task by the user. work on it autonomously — think, use tools, and test your code.
context will be summarized automatically when it gets long so you don't run out.
there may be additional prompt blocks appended to this system prompt — they describe your current task and are repeated every turn so you never lose track.

## workspace

your home directory is /home/agent/. only files here persist — everything else (installed packages, files in /tmp, etc.) may be lost. feel free to create folders within /home/agent/ for different projects.

do NOT touch these system files — they are managed automatically:
- /home/agent/term.log — terminal logger used by TERM. do not edit, delete, or write to it.
- /home/agent/screenshots/ — used by LOOK. do not edit or delete.

the screen is 1920x1080. on the left edge is a vertical sidebar (tint2) with two launcher icons: terminal at ~(24, 30) and chromium at ~(24, 74). below them is a taskbar showing every open window. MOVE + LCLICK an icon to open that app directly — no terminal needed. if your terminal gets closed, click the terminal icon to reopen it; it reattaches to the term.log logger.

installed software: chromium, xterm (terminal), openbox (window manager), tint2 (sidebar), git (+ git-lfs), tmux, curl, wget, jq, rg (ripgrep), vim, nano, htop, tree, zip/unzip, sqlite3, python3 (+ ipython).

preinstalled python environment: /opt/agent-venv is on PATH and contains fastapi, uvicorn, httpx, websockets, matplotlib, pandas, torch, ipython, pytest, huggingface_hub, einops, tqdm. so `python3`, `pip`, `fastapi`, `uvicorn`, etc. work immediately. if you need additional packages, you can `pip install` them into this venv — they will last for the lifetime of the container but are lost when the container is recreated. for packages that must persist, create a venv under /home/agent.

to launch chromium: click the chromium icon in the sidebar, or TYPE `chromium &` in the terminal and press Return. the `&` backgrounds it so the terminal stays usable. the chromium wrapper at /usr/local/bin/chromium auto-adds --no-sandbox.

on startup, xterm is already open and focused. just call TYPE / KEY directly — no need to click the terminal.

## git

git is installed. manage your own credentials (HTTPS tokens or SSH keys placed under /home/agent/.ssh/).

## tools (commands)

you have access to a set of computer-control tools exposed through the API. use them naturally: explain your reasoning in the assistant text, then call the tools you need. the API handles the tool-call format; just think, speak, and invoke tools by name.

available commands:

mouse: MOVE x y, LDOWN, LUP, RDOWN, RUP, LCLICK, RCLICK, DCLICK, SCROLLUP, SCROLLDOWN
keyboard: TYPE text, KEY list-of-X11-keysyms (e.g. ["ctrl","shift","s"], ["Return"], ["BackSpace"])
perception: LOOK (screenshot), TERM (last 5000 chars of terminal)
file (workspace files): READ file [start] [end], WRITE file content, EDIT file old new which
special: WAIT secs
docker: DOCKER_START (start your computer, switches to work mode), DOCKER_STOP (release it, back to chat mode)
graph (F4B board, only if you are attached to one): GCREATE title kind node_type [parent] [state] [ref] [near], GREAD node, GUPDATE node [title] [node_type] [state] [content] [settings], GDESTROY node, GMOVE node [x] [y] [parent], GLINK source target, GUNLINK edge, GLIST

rules:
- use tools whenever you need to act on the computer.
- do not invent tool names. only use the ones listed above.
- all tool calls in one response are executed in order before you get back any results.
- after you call tools, the next turn starts with one tool_result per tool_call you made. for action tools the result is "ok"; for perception tools the result is the actual output (TERM text, LOOK image, READ file contents).

## auto-feedback

after a turn that contains any keyboard command (TYPE/KEY) but no TERM call, the agent automatically replaces the last "ok" tool_result with TERM (terminal output).
after a turn that contains any mouse command (MOVE/CLICK/SCROLL/DRAG) but no LOOK call, the agent automatically replaces the last "ok" tool_result with LOOK (screenshot).

so for typical terminal workflows you do NOT need to call TERM explicitly after typing. for GUI workflows (clicking, dragging) you usually do NOT need to call LOOK after every action — just act, and you'll get a fresh screenshot back.

## misc

screenshots show a red crosshair circle at the current mouse position so you can see the cursor.
SCROLLUP/SCROLLDOWN target the active window — your mouse position doesn't affect which window scrolls.
all tool_calls in your response are executed in order before you get back any tool_results. so don't depend on intra-turn perception unless you also call LOOK/TERM in between.
"""

_DEFAULT_CHAT_MODE_PROMPT = """\
you are now in chat mode: a conversation with the user, no computer use. you do NOT have a docker computer right now — that is fine, a docker is just a tool.
if you genuinely need a computer (to run code, browse, or use a GUI), call DOCKER_START — it starts your container and switches you to work mode with computer tools. call DOCKER_STOP to release it when done.
if you are attached to an F4B board, graph commands (GCREATE, GREAD, GUPDATE, GDESTROY, GMOVE, GLINK, GUNLINK, GLIST) still work in chat mode.
"""

_DEFAULT_AUTO_TURN_PROMPT = """\
your last response ended without any environment returns. that is fine — you can think across multiple turns without acting. continue working. whether that is more thinking, terminal control, GUI control, or file editing.
"""

_DEFAULT_SUMMARIZATION_PROMPT = """\
summarize these messages into a concise summary for YOURSELF to later read. think of this as your working memory.

IMPORTANT: after this summary, you will ONLY see this summary + the last 5 messages. everything else is GONE FOREVER.
anything you don't include in this summary, you will never remember. treat this like your only lifeline.

write maximum 16384 tokens. be thorough.

important things to include:
- user requests and goals (what are you supposed to be doing?)
- the specific problem you are solving right now
- the general structure: file architecture, what files exist, what they do
- the specific details: what functions do, what variables hold, exact paths
- your current plan: what you're working on, what you're about to do next
- past solutions you tried but FAILED and WHY — so you don't repeat them
- exact specific quotes, values, paths, names that matter

things you can discard:
- problems you already SOLVED completely
- random tangents that are done and resolved

if in doubt, include it. a slightly too long summary is better than forgetting something critical.
"""

WORK_MSG = """\
AUTOMATED MESSAGE
message triggered due to your last response being pure text with no tool calls. this is fine. you can think across multiple turns without acting.
continue working. whether that is more thinking, terminal control, GUI control, or file editing.
"""


# prompt blocks exposed in the UI. internal prompts are used by the system but not selectable.
HIDDEN_PROMPTS = {"auto_turn_prompt", "chat_mode_prompt", "summarization_prompt"}


def list_prompt_blocks(user: str) -> list[dict]:
    """Return the user's selectable prompt blocks (global + user-defined)."""
    _ensure_default_prompts(user)
    blocks = []
    for path in sorted(_prompts_dir(user).glob("*.md")):
        if path.stem in HIDDEN_PROMPTS:
            continue
        blocks.append({
            "name": path.stem,
            "filename": path.name,
            "text": path.read_text(),
            "editable": path.stem != "global_prompt",
        })
    return blocks


def save_prompt_block(user: str, name: str, text: str):
    """Create or overwrite a user prompt block."""
    _ensure_default_prompts(user)
    if name == "global_prompt":
        raise ValueError("global_prompt is not editable")
    if name in HIDDEN_PROMPTS:
        raise ValueError(f"{name} is a system prompt and cannot be edited")
    path = _prompts_dir(user) / f"{name}.md"
    path.write_text(text)


def delete_prompt_block(user: str, name: str):
    """Delete a user prompt block."""
    _ensure_default_prompts(user)
    if name == "global_prompt":
        raise ValueError("global_prompt cannot be deleted")
    if name in HIDDEN_PROMPTS:
        raise ValueError(f"{name} is a system prompt and cannot be deleted")
    path = _prompts_dir(user) / f"{name}.md"
    if path.exists():
        path.unlink()


def get_selected_prompts(user: str, agent_name: str) -> list[str]:
    """Return ordered list of selected prompt block names for an agent."""
    _ensure_default_prompts(user)
    path = _specific_dir(user) / agent_name / "prompts_selected.json"
    if not path.exists():
        return ["global_prompt"]
    import json
    selected = json.loads(path.read_text()).get("selected", ["global_prompt"])
    # global_prompt is always first and cannot be removed
    selected = [n for n in selected if n != "global_prompt"]
    return ["global_prompt"] + selected


def set_selected_prompts(user: str, agent_name: str, selected: list[str]):
    """Save ordered list of selected prompt block names for an agent."""
    path = _specific_dir(user) / agent_name
    path.mkdir(parents=True, exist_ok=True)
    import json
    # global_prompt is always first and cannot be removed
    selected = [n for n in selected if n != "global_prompt"]
    (path / "prompts_selected.json").write_text(json.dumps({"selected": ["global_prompt"] + selected}))


def _graph_context_block(user: str, agent_name: str) -> str | None:
    """Build the graph context block for an agent attached to an F4B board node.

    The attached node is the agent's node. Context comes from:
    - the func nodes the agent connects into (it is their DOER) + those funcs' inputs
    - the agent's settings: prompt docs (content appended), read access (content
      appended), write access (listed as writable) — all compiled into the prompt tail.
    Rebuilt every call so board edits are seen next turn.
    """
    attach_path = _specific_dir(user) / agent_name / "graph.json"
    if not attach_path.exists():
        return None
    try:
        attach = json.loads(attach_path.read_text())
    except Exception:
        return None
    board, node_id = attach.get("board"), attach.get("node")
    if not board or not node_id:
        return None
    try:
        meta = storage.load_meta(user, board)
    except Exception:
        return None
    if node_id not in meta["nodes"]:
        return None

    agent_node = meta["nodes"][node_id]
    settings = agent_node.get("settings") or {}
    PER_NODE_CAP = 2000
    TOTAL_CAP = 12000

    parts = [
        "## graph context",
        f"you are the agent '{agent_node['title']}' (node id {node_id}) on F4B board '{board}'.",
        "",
    ]
    total = 0

    def add(text: str) -> bool:
        nonlocal total
        if total + len(text) > TOTAL_CAP:
            return False
        parts.append(text)
        total += len(text)
        return True

    # funcs this agent does: edges agent <-> func
    func_ids = set()
    for e in meta["edges"].values():
        if e["source"] == node_id and e["target"] in meta["nodes"] and meta["nodes"][e["target"]]["kind"] == "func":
            func_ids.add(e["target"])
        if e["target"] == node_id and e["source"] in meta["nodes"] and meta["nodes"][e["source"]]["kind"] == "func":
            func_ids.add(e["source"])
    if func_ids:
        add("### you are the DOER of these funcs")
        for fid in sorted(func_ids):
            f = meta["nodes"][fid]
            add(f"- {f['title']} ({f['node_type']}, id {fid})")
        # inbound objs of those funcs (excluding the agent itself)
        input_ids = set()
        for e in meta["edges"].values():
            if e["target"] in func_ids and e["source"] != node_id and e["source"] in meta["nodes"]:
                input_ids.add(e["source"])
        for oid in sorted(input_ids):
            o = meta["nodes"][oid]
            header = f"#### input: [{o['node_type']}] {o['title']} (id {oid}, state {o['state']})"
            content = storage.read_content(user, board, oid)[:PER_NODE_CAP]
            if not add(header + ("\n" + content if content else "")):
                break
        parts.append("")

    # prompt docs dropped into the agent's prompts section
    prompt_docs = [pid for pid in settings.get("prompt_docs", []) if pid in meta["nodes"]]
    if prompt_docs:
        add("### prompts (from board docs)")
        for pid in prompt_docs:
            o = meta["nodes"][pid]
            content = storage.read_content(user, board, pid)[:PER_NODE_CAP]
            if not add(f"#### {o['title']}\n{content}"):
                break
        parts.append("")

    # read access: content appended so the agent can actually read them
    read_ids = [rid for rid in settings.get("read", []) if rid in meta["nodes"]]
    if read_ids:
        add("### you have READ access to these nodes")
        for rid in read_ids:
            o = meta["nodes"][rid]
            header = f"#### [{o['node_type']}] {o['title']} (id {rid})"
            content = storage.read_content(user, board, rid)[:PER_NODE_CAP]
            if not add(header + ("\n" + content if content else "")):
                break
        parts.append("")

    # write access: listed as writable targets
    write_ids = [wid for wid in settings.get("write", []) if wid in meta["nodes"]]
    if write_ids:
        names = ", ".join(f"'{meta['nodes'][wid]['title']}' (id {wid})" for wid in write_ids)
        add(f"### you have WRITE access to: {names}")
        parts.append("")

    parts.append("graph commands: GCREATE GREAD GUPDATE GDESTROY GMOVE GLINK GUNLINK GLIST — operate this board directly. nodes you create are auto-placed.")
    return "\n".join(parts)


def build_system_prompt(user: str, agent_name: str, chat_mode: bool = False) -> str:
    """Build the full system prompt from the user's selected blocks."""
    _ensure_default_prompts(user)
    selected = get_selected_prompts(user, agent_name)
    parts = []
    for name in selected:
        path = _prompts_dir(user) / f"{name}.md"
        if path.exists():
            parts.append(path.read_text())
    graph_block = _graph_context_block(user, agent_name)
    if graph_block:
        parts.append(graph_block)
    if chat_mode:
        parts.append((_prompts_dir(user) / "chat_mode_prompt.md").read_text())
    return "\n\n".join(parts)


CONTEXT_SUMMARIZATION_PROMPT = _DEFAULT_SUMMARIZATION_PROMPT
