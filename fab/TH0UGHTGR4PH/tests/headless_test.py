"""Headless tests for TH0UGHTGR4PH + INT3RF4CE integration.

Part 1 (agent POV, no server): graph_actions CRUD + the agent's access-enforced
graph dispatch (CHECK_GRAPH_ACCESS / GREAD / GUPDATE / GDESTROY) + the prompt
docs block, against a throwaway user. Asserts data changes on disk.

Part 2 (REST/auth): boots the hub on a test port, registers throwaway users,
exercises the TH0UGHTGR4PH REST API (boards/nodes/content/edges/types/versions)
and the INT3RF4CE WS get/set_graph_settings flow, and per-user isolation.

All test users and their data are removed afterwards. Exits non-zero on failure.

Run from repo root: venv/bin/python -m fab.TH0UGHTGR4PH.tests.headless_test
"""

import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT))

from fab.TH0UGHTGR4PH.back import graph_actions, storage
from fab.TH0UGHTGR4PH.back.config import DATA_DIR, GRID_SIZE
from fab.INT3RF4CE.back.agent import Agent
from fab.INT3RF4CE.back.models.kimi import Kimi
from fab.INT3RF4CE.back.prompt import _prompt_docs_block, build_system_prompt

AGENT_USER = "test_tg_agent"
WEB_USER_A = "test_tg_a"
WEB_USER_B = "test_tg_b"
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


def make_agent(user: str, name: str) -> Agent:
    """A chat-mode agent with no container side effects (docker only starts on start())."""
    return Agent(user, name, Kimi(model="kimi-k3"), use_container=True, novnc_port=6999, chat_mode=True)


def write_graph_settings(user: str, agent: str, settings: dict):
    specific = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE" / user / "config" / "specific" / agent
    specific.mkdir(parents=True, exist_ok=True)
    (specific / "graph.json").write_text(json.dumps(settings))


# ---------------------------------------------------------------- part 1: agent POV

def test_agent_pov():
    print("part 1: agent-POV graph actions + access enforcement")
    cleanup_user(AGENT_USER)
    storage.init_user_storage(AGENT_USER)
    board = "main"

    check("main board exists", board in storage.list_boards(AGENT_USER))
    types = storage.load_types(AGENT_USER)
    check("seeded doc types include theory/doc", "theory" in types["doc_types"] and "doc" in types["doc_types"])
    check("seeded edge types", "support" in types["edge_types"] and "reject" in types["edge_types"])
    check("no agent type anymore", "agent" not in types["doc_types"])

    # [theory] -[support]-> [mid] -[inference]-> [code]
    theory = graph_actions.create_node(AGENT_USER, board, "ML theory", "doc", "theory")
    mid = graph_actions.create_node(AGENT_USER, board, "midpoint", "doc", "doc")
    code = graph_actions.create_node(AGENT_USER, board, "jump_relu.py", "doc", "code", ref="mind/SYN4P5E/algorithms/jump_relu.py")

    xs = [theory["x"], mid["x"], code["x"]]
    ys = [theory["y"], mid["y"], code["y"]]
    check("positions grid-aligned", all(x % GRID_SIZE == 0 and y % GRID_SIZE == 0 for x, y in zip(xs, ys)))
    check("positions distinct", len(set(zip(xs, ys))) == 3)
    check("mid right of theory", mid["x"] > theory["x"])

    e1 = graph_actions.link(AGENT_USER, board, theory["id"], mid["id"], "support")
    e2 = graph_actions.link(AGENT_USER, board, mid["id"], code["id"], "inference")
    check("two edges created", len(storage.load_meta(AGENT_USER, board)["edges"]) == 2)
    check("edge types persisted", e1["edge_type"] == "support" and e2["edge_type"] == "inference")
    try:
        graph_actions.link(AGENT_USER, board, theory["id"], code["id"], "not_a_type")
        check("unknown edge type rejected", False)
    except ValueError:
        check("unknown edge type rejected", True)

    read = graph_actions.read_node(AGENT_USER, board, mid["id"])
    ins = {c["title"] for c in read["connected"] if c["direction"] == "in"}
    outs = {c["title"] for c in read["connected"] if c["direction"] == "out"}
    check("mid reads theory as input", ins == {"ML theory"})
    check("mid reads code as output", outs == {"jump_relu.py"})

    graph_actions.update_node(AGENT_USER, board, theory["id"], content="# ML theory\ndot products and relus", state="doing")
    check("content persisted", storage.read_content(AGENT_USER, board, storage.load_meta(AGENT_USER, board), theory["id"]).startswith("# ML theory"))
    meta = storage.load_meta(AGENT_USER, board)
    check("state persisted", meta["nodes"][theory["id"]]["state"] == "doing")

    moved = graph_actions.move_node(AGENT_USER, board, theory["id"], x=0, y=600)
    check("move persisted + snapped", storage.load_meta(AGENT_USER, board)["nodes"][theory["id"]]["y"] == 600)

    try:
        graph_actions.create_node(AGENT_USER, board, "bad", "doc", "not_a_type")
        check("unknown type rejected", False)
    except ValueError:
        check("unknown type rejected", True)
    try:
        graph_actions.create_node(AGENT_USER, board, "agent attempt", "agent", "agent")
        check("agent kind rejected", False)
    except ValueError:
        check("agent kind rejected", True)
    try:
        graph_actions.create_node(AGENT_USER, board, "func attempt", "func", "support")
        check("func kind rejected (funcs are gone)", False)
    except ValueError:
        check("func kind rejected (funcs are gone)", True)

    # ---- title-path storage: unique titles, no path poison, disk follows renames ----
    try:
        graph_actions.create_node(AGENT_USER, board, "ML theory", "doc", "doc")
        check("duplicate title rejected on create", False)
    except ValueError:
        check("duplicate title rejected on create", True)
    try:
        graph_actions.update_node(AGENT_USER, board, mid["id"], title="ML theory")
        check("duplicate title rejected on rename", False)
    except ValueError:
        check("duplicate title rejected on rename", True)
    try:
        graph_actions.create_node(AGENT_USER, board, "bad/slash", "doc", "doc")
        check("path-poison title rejected", False)
    except ValueError:
        check("path-poison title rejected", True)

    from fab.TH0UGHTGR4PH.back.config import DATA_DIR
    tree_root = DATA_DIR / AGENT_USER / board / "tree"
    check("content lives at title path",
          (tree_root / "ML theory.md").exists())
    graph_actions.update_node(AGENT_USER, board, theory["id"], title="renamed theory")
    check("rename moves content file",
          (tree_root / "renamed theory.md").exists() and not (tree_root / "ML theory.md").exists())
    check("content survives rename", storage.read_content(
        AGENT_USER, board, storage.load_meta(AGENT_USER, board), theory["id"]).startswith("# ML theory"))
    graph_actions.update_node(AGENT_USER, board, theory["id"], title="ML theory")

    graph_actions.update_node(AGENT_USER, board, mid["id"], content="mid content")
    graph_actions.update_node(AGENT_USER, board, mid["id"], title="mid moved")
    check("doc rename moves file", (tree_root / "mid moved.md").exists())
    # folder rename moves the whole subtree's content
    f2 = graph_actions.create_node(AGENT_USER, board, "f2", "folder", "folder")
    d2 = graph_actions.create_node(AGENT_USER, board, "d2", "doc", "doc", parent=f2["id"])
    graph_actions.update_node(AGENT_USER, board, d2["id"], content="hello d2")
    graph_actions.update_node(AGENT_USER, board, f2["id"], title="f2 renamed")
    check("folder rename moves subtree content",
          (tree_root / "f2 renamed" / "d2.md").exists()
          and storage.read_content(AGENT_USER, board, storage.load_meta(AGENT_USER, board), d2["id"]) == "hello d2")
    graph_actions.destroy_node(AGENT_USER, board, f2["id"])
    check("destroy removes folder tree", not (tree_root / "f2 renamed").exists())

    # ---- access-enforced dispatch (the agent's actual command path) ----
    agent = make_agent(AGENT_USER, "agent_x")
    write_graph_settings(AGENT_USER, "agent_x", {
        "prompt_docs": [{"board": board, "id": theory["id"]}],
        "read": [{"board": board, "id": code["id"]}],
        "write": [{"board": board, "id": theory["id"]}],
    })

    out = agent._graph_dispatch("CHECK_GRAPH_ACCESS", {})
    check("CHECK_GRAPH_ACCESS lists board", f'"board": "{board}"' in out)
    check("CHECK_GRAPH_ACCESS: write implies read", "ML theory" in out and "jump_relu.py" in out)
    check("CHECK_GRAPH_ACCESS prints node_type + state", '"node_type": "theory"' in out and '"state":' in out)

    out = agent._graph_dispatch("GREAD", {"node": code["id"]})
    check("GREAD allowed on read-listed node", "jump_relu.py" in out)
    out = agent._graph_dispatch("GREAD", {"node": mid["id"]})
    check("GREAD rejected on unlisted node", "no read access" in out)

    out = agent._graph_dispatch("GUPDATE", {"node": theory["id"], "state": "done"})
    check("GUPDATE allowed on write-listed node", "updated" in out)
    check("state done persisted", storage.load_meta(AGENT_USER, board)["nodes"][theory["id"]]["state"] == "done")
    out = agent._graph_dispatch("GEDIT", {"node": code["id"], "old": "x", "new": "y", "which": "0"})
    check("GEDIT rejected on read-only node", "no write access" in out)

    out = agent._graph_dispatch("GEDIT", {"node": theory["id"], "old": "dot products", "new": "matmuls", "which": "0"})
    check("GEDIT allowed on write-listed node", "done" in out)
    check("GEDIT changed the content", "matmuls and relus" in storage.read_content(AGENT_USER, board, storage.load_meta(AGENT_USER, board), theory["id"]))
    out = agent._graph_dispatch("GEDIT", {"node": theory["id"], "old": "not present", "new": "y", "which": "0"})
    check("GEDIT reports text not found", "text not found" in out)

    out = agent._graph_dispatch("GDESTROY", {"node": theory["id"]})
    check("GDESTROY rejected without folder control (write list is not enough)", "folder total control" in out)
    out = agent._graph_dispatch("GCREATE", {"title": "x", "kind": "doc", "node_type": "doc"})
    check("GCREATE without parent folder rejected", "parent folder required" in out)

    # prompt docs block: only prompt_docs content is injected, not access lists
    block = _prompt_docs_block(AGENT_USER, "agent_x")
    check("prompt docs block exists", block is not None)
    check("prompt docs block has doc content", "matmuls and relus" in block)
    check("prompt docs block has no access lists", "READ access" not in block and "WRITE access" not in block)
    prompt = build_system_prompt(AGENT_USER, "agent_x")
    check("system prompt includes prompt docs", "matmuls and relus" in prompt)

    # ---- folder total control access ----
    folder = graph_actions.create_node(AGENT_USER, board, "project", "folder", "folder")
    inside = graph_actions.create_node(AGENT_USER, board, "inside doc", "doc", "doc", parent=folder["id"])
    subfolder = graph_actions.create_node(AGENT_USER, board, "sub", "folder", "folder", parent=folder["id"])
    deep = graph_actions.create_node(AGENT_USER, board, "deep doc", "doc", "doc", parent=subfolder["id"])
    outside = graph_actions.create_node(AGENT_USER, board, "outside doc", "doc", "doc")

    write_graph_settings(AGENT_USER, "agent_x", {
        "prompt_docs": [{"board": board, "id": theory["id"]}],
        "read": [{"board": board, "id": code["id"]}],
        "write": [{"board": board, "id": theory["id"]}],
        "folders": [{"board": board, "id": folder["id"]}],
    })

    out = agent._graph_dispatch("CHECK_GRAPH_ACCESS", {})
    check("CHECK lists folder total control", "folder_total_control" in out and "project" in out)

    out = agent._graph_dispatch("GREAD", {"node": inside["id"]})
    check("folder access: GREAD inside", "inside doc" in out)
    out = agent._graph_dispatch("GREAD", {"node": deep["id"]})
    check("folder access: GREAD nested inside", "deep doc" in out)
    out = agent._graph_dispatch("GREAD", {"node": "deep doc"})
    check("folder access: resolve by title", "deep doc" in out)
    out = agent._graph_dispatch("GREAD", {"node": outside["id"]})
    check("folder access: GREAD outside rejected", "no read access" in out)

    out = agent._graph_dispatch("GUPDATE", {"node": inside["id"], "state": "doing"})
    check("folder access: GUPDATE inside", "updated" in out)
    out = agent._graph_dispatch("GUPDATE", {"node": inside["id"], "node_type": "theory"})
    check("folder access: GUPDATE retype inside", "updated" in out)
    out = agent._graph_dispatch("GUPDATE", {"node": outside["id"], "state": "done"})
    check("folder access: GUPDATE outside rejected", "no write access" in out)

    out = agent._graph_dispatch("GEDIT", {"node": deep["id"], "old": "x", "new": "y", "which": "0"})
    check("folder access: GEDIT nested allowed", "text not found" in out)

    out = agent._graph_dispatch("GCREATE", {"title": "new idea", "kind": "doc", "node_type": "doc", "parent": folder["id"]})
    check("folder access: GCREATE inside", "created" in out)
    meta = storage.load_meta(AGENT_USER, board)
    new_idea = next(n for n in meta["nodes"].values() if n["title"] == "new idea")
    check("GCREATE child placed folder-relative", 0 <= new_idea["x"] <= 400 and 0 <= new_idea["y"] <= 400)
    out = agent._graph_dispatch("GCREATE", {"title": "bad", "kind": "doc", "node_type": "doc", "parent": outside["id"]})
    check("GCREATE outside rejected", "parent must be a folder inside your access" in out)
    out = agent._graph_dispatch("GCREATE", {"title": "bad2", "kind": "doc", "node_type": "doc", "parent": inside["id"]})
    check("GCREATE non-folder parent rejected", out.rstrip().endswith("parent must be a folder"))

    out = agent._graph_dispatch("GMOVE", {"node": inside["id"], "parent": subfolder["id"]})
    check("folder access: GMOVE within scope", "moved" in out)
    meta = storage.load_meta(AGENT_USER, board)
    check("GMOVE reparent persisted", meta["nodes"][inside["id"]]["parent"] == subfolder["id"])
    out = agent._graph_dispatch("GMOVE", {"node": inside["id"], "parent": outside["id"]})
    check("GMOVE to outside rejected", "new parent must be a folder inside" in out)

    out = agent._graph_dispatch("GLINK", {"source": deep["id"], "target": inside["id"], "edge_type": "support"})
    check("folder access: GLINK within scope", "linked" in out)
    out = agent._graph_dispatch("GLINK", {"source": deep["id"], "target": outside["id"], "edge_type": "support"})
    check("GLINK to outside rejected", "write access or total-control" in out)
    out = agent._graph_dispatch("GLINK", {"source": deep["id"], "target": folder["id"], "edge_type": "support"})
    check("GLINK to folder hard-blocked", "not folders" in out)

    # ---- GMAP: ascii layout picture + expand/collapse control ----
    out = agent._graph_dispatch("GUPDATE", {"node": inside["id"], "expanded": True})
    check("GUPDATE expanded toggle", "updated" in out)
    check("expanded persisted", storage.load_meta(AGENT_USER, board)["nodes"][inside["id"]]["expanded"] is True)
    agent._graph_dispatch("GUPDATE", {"node": inside["id"], "expanded": False})

    out = agent._graph_dispatch("GMAP", {"folder": folder["id"]})
    check("GMAP renders folder", "[GMAP]" in out and "sub" in out and "╔" in out)
    out = agent._graph_dispatch("GMAP", {"folder": subfolder["id"]})
    check("GMAP legend has ids", deep["id"] in out and inside["id"] in out)
    check("GMAP lists edges", "deep doc -[support]-> inside doc" in out)
    out = agent._graph_dispatch("GMAP", {})
    check("GMAP root renders", "root" in out and "project" in out)
    check("GMAP lists typed edges", "-[" in out or "root" in out)
    out = agent._graph_dispatch("GMAP", {"folder": inside["id"]})
    check("GMAP rejects non-folder", "must be a folder" in out)
    outfolder = graph_actions.create_node(AGENT_USER, board, "out folder", "folder", "folder")
    out = agent._graph_dispatch("GMAP", {"folder": outfolder["id"]})
    check("GMAP rejects out-of-scope folder", "no access" in out)

    # ---- GDESTROY: folder total control only ----
    out = agent._graph_dispatch("GDESTROY", {"node": "new idea"})
    check("GDESTROY inside folder scope (by title)", "deleted 1 node" in out)
    meta = storage.load_meta(AGENT_USER, board)
    check("GDESTROY removed from disk", all(n["title"] != "new idea" for n in meta["nodes"].values()))
    out = agent._graph_dispatch("GDESTROY", {"node": outfolder["id"]})
    check("GDESTROY out-of-scope folder rejected", "folder total control" in out)
    out = agent._graph_dispatch("GDESTROY", {"node": code["id"]})
    check("GDESTROY read-listed node rejected", "folder total control" in out)
    out = agent._graph_dispatch("GDESTROY", {"node": subfolder["id"]})
    check("GDESTROY folder is recursive", "deleted 3 node" in out)
    meta = storage.load_meta(AGENT_USER, board)
    check("subtree gone from disk", subfolder["id"] not in meta["nodes"] and deep["id"] not in meta["nodes"] and inside["id"] not in meta["nodes"])
    check("subtree edges cleaned", all(e["source"] in meta["nodes"] and e["target"] in meta["nodes"] for e in meta["edges"].values()))

    res = graph_actions.destroy_node(AGENT_USER, board, theory["id"])
    meta = storage.load_meta(AGENT_USER, board)
    check("destroy removes node", theory["id"] not in meta["nodes"])
    check("edges to destroyed nodes gone", all(e["source"] in meta["nodes"] and e["target"] in meta["nodes"] for e in meta["edges"].values()))

    # ---- STOP: the agent halts itself and cannot self-restart ----
    out, _ = agent._dispatch("STOP", {})
    check("STOP halts the agent", "stopped" in out and agent.stopped)
    out, _ = asyncio.run(agent._docker_control("DOCKER_START"))
    check("DOCKER_START blocked after STOP", "cannot resume" in out)

    # ---- channels: agent-to-user messaging, files, cursors, injection ----
    from fab.INT3RF4CE.back import chat as chatmod
    from fab.INT3RF4CE.back.server import inject_pending, _block_for_file

    cid = chatmod.ensure_dm(AGENT_USER, "agent_x")
    check("dm channel has both members",
          chatmod.is_member(AGENT_USER, cid, chatmod.USER_SENDER)
          and chatmod.is_member(AGENT_USER, cid, "agent_x"))

    ws_dir = agent.workspace
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / "report.md").write_text("# report\nhello")
    out = agent._chat_dispatch("CHAT_SEND", {"channel": "agent_x", "text": "done"})
    check("CHAT_SEND text by channel name", "sent to" in out)
    out = agent._chat_dispatch("CHAT_SEND", {"channel": cid, "file": "report.md"})
    check("CHAT_SEND file from workspace", "sent to" in out)
    msgs = chatmod.read_messages(AGENT_USER, cid, limit=10)
    check("dm log has both messages", len(msgs) == 2 and msgs[1]["file"]["name"] == "report.md")
    fp = chatmod.channel_file(AGENT_USER, cid, msgs[1]["file"]["path"])
    check("channel file bytes stored", fp.read_text().startswith("# report"))
    out = agent._chat_dispatch("CHAT_SEND", {"channel": cid, "file": "../meta.json"})
    check("CHAT_SEND rejects path escape", "ERROR" in out)
    try:
        chatmod.store_file(AGENT_USER, cid, "virus.exe", b"MZ")
        check("executable ext blocked", False)
    except ValueError:
        check("executable ext blocked", True)

    chatmod.append_message(AGENT_USER, cid, chatmod.USER_SENDER, "text", text="inject me")
    pend = chatmod.pending_messages(AGENT_USER, "agent_x")
    check("pending shows user message", cid in pend and pend[cid][-1]["text"] == "inject me")
    out = agent._chat_dispatch("CHAT_READ", {"channel": cid})
    check("CHAT_READ returns messages", "inject me" in out and "report.md" in out)
    check("CHAT_READ marks read", not chatmod.pending_messages(AGENT_USER, "agent_x"))
    out = agent._chat_dispatch("CHAT_READ", {"channel": "nonexistent"})
    check("CHAT_READ non-member rejected", "no access" in out)

    chatmod.append_message(AGENT_USER, cid, chatmod.USER_SENDER, "text", text="inject me too")
    inject_pending(AGENT_USER, "agent_x", {"agent": agent})
    texts = [b.get("text", "") for m in agent.context.messages for b in m.get("content", []) if b.get("type") == "text"]
    check("injection adds context message", any("inject me too" in t for t in texts))
    check("injection marks read", not chatmod.pending_messages(AGENT_USER, "agent_x"))
    from pathlib import Path as _P
    (_P("/tmp/tg_block_test.png")).write_bytes(b"\x89PNG fake")
    check("image block built", _block_for_file(_P("/tmp/tg_block_test.png"))["type"] == "image")

    # ---- secrets: user store + grant-enforced READ_SECRETS ----
    from fab.INT3RF4CE.back import secrets as secretsmod

    secretsmod.set_secret(AGENT_USER, "deepseek", "sk-test-123", cat="llm")
    secretsmod.set_secret(AGENT_USER, "github", "ghp-test-456")
    check("secret names listed", secretsmod.names(AGENT_USER) == ["deepseek", "github"])
    check("secret categories tracked", secretsmod.items(AGENT_USER) == [
        {"name": "deepseek", "cat": "llm"}, {"name": "github", "cat": "account"}])
    check("backend resolve returns value", secretsmod.resolve(AGENT_USER, "deepseek") == "sk-test-123")
    store_path = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE" / AGENT_USER / "secrets.json"
    check("store file is chmod 600", oct(store_path.stat().st_mode & 0o777) == "0o600")
    try:
        secretsmod.set_secret(AGENT_USER, "bad name!", "x")
        check("invalid secret name rejected", False)
    except ValueError:
        check("invalid secret name rejected", True)

    out, _ = agent._dispatch("READ_SECRETS", {})
    check("READ_SECRETS empty without grants", "no secrets granted" in out and "sk-test-123" not in out)

    secretsmod.save_grants(AGENT_USER, "agent_x", ["deepseek"])
    out, _ = agent._dispatch("READ_SECRETS", {})
    check("READ_SECRETS returns granted only", "sk-test-123" in out and "ghp-test-456" not in out)

    # deleting a secret strips it from the store AND every agent's grants
    secretsmod.delete_secret(AGENT_USER, "deepseek")
    check("delete removes value", secretsmod.resolve(AGENT_USER, "deepseek") is None)
    check("delete strips grants", secretsmod.load_grants(AGENT_USER, "agent_x") == [])
    out, _ = agent._dispatch("READ_SECRETS", {})
    check("READ_SECRETS empty after delete", "no secrets granted" in out)

    # git entries: forced {"account", "key"} pairs; repos live alongside (not secret)
    git_key = "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----"
    secretsmod.set_secret(AGENT_USER, "agent-main", {"account": "mindology-agent", "key": git_key}, cat="git")
    secretsmod.set_secret(AGENT_USER, "mindfab", "git@github.com:x/y.git", cat="gitrepo")
    items = {i["name"]: i for i in secretsmod.items(AGENT_USER)}
    check("git items show account only", items["agent-main"]["value"] == {"account": "mindology-agent"})
    check("gitrepo items show the url", items["mindfab"]["value"] == "git@github.com:x/y.git")
    try:
        secretsmod.set_secret(AGENT_USER, "bad-git", {"key": git_key}, cat="git")
        check("git without account rejected", False)
    except ValueError:
        check("git without account rejected", True)
    try:
        secretsmod.set_secret(AGENT_USER, "bad-git2", {"account": "a", "key": "not a key"}, cat="git")
        check("git non-private-key rejected", False)
    except ValueError:
        check("git non-private-key rejected", True)
    secretsmod.save_grants(AGENT_USER, "agent_x", ["agent-main", "mindfab"])
    out, _ = agent._dispatch("READ_SECRETS", {})
    check("READ_SECRETS git entry is an object", '"account": "mindology-agent"' in out and "OPENSSH PRIVATE KEY" in out)
    check("READ_SECRETS includes granted repos", "git@github.com:x/y.git" in out)

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
    print("part 2: REST API + WS graph settings + isolation")
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

        check("unauth board rejected", httpx.get(f"{BASE}/TH0UGHTGR4PH/boards").status_code == 401)
        boards = a.get("/TH0UGHTGR4PH/boards").json()["boards"]
        check("A gets main board", boards == ["main"])

        obj = a.post("/TH0UGHTGR4PH/boards/main/nodes", json={"title": "theory A", "kind": "doc", "node_type": "theory"}).json()
        mid2 = a.post("/TH0UGHTGR4PH/boards/main/nodes", json={"title": "midpoint", "kind": "doc", "node_type": "doc"}).json()
        folder = a.post("/TH0UGHTGR4PH/boards/main/nodes", json={"title": "proj folder", "kind": "folder", "node_type": "folder"}).json()
        check("REST create doc", obj["kind"] == "doc" and obj["node_type"] == "theory")
        check("REST autoplaced", mid2["x"] > obj["x"] or mid2["y"] != obj["y"])
        check("REST create folder", folder["kind"] == "folder")

        edge = a.post("/TH0UGHTGR4PH/boards/main/edges", json={"source": obj["id"], "target": mid2["id"], "edge_type": "support"}).json()
        graph = a.get("/TH0UGHTGR4PH/boards/main/graph").json()
        check("REST edge in graph", edge["id"] in graph["edges"])

        a.put(f"/TH0UGHTGR4PH/boards/main/nodes/{obj['id']}/content", json={"content": "hello content"})
        content = a.get(f"/TH0UGHTGR4PH/boards/main/nodes/{obj['id']}/content").json()["content"]
        check("REST content roundtrip", content == "hello content")

        upd = a.put(f"/TH0UGHTGR4PH/boards/main/nodes/{obj['id']}", json={"state": "doing", "x": 400, "y": 200}).json()
        check("REST update state+pos", upd["state"] == "doing" and upd["x"] == 400)

        types = a.get("/TH0UGHTGR4PH/types").json()
        types["doc_types"]["custom_type"] = {"color": "#ABCDEF"}
        a.put("/TH0UGHTGR4PH/types", json=types)
        check("REST types roundtrip", "custom_type" in a.get("/TH0UGHTGR4PH/types").json()["doc_types"])

        # versions
        v = a.post("/TH0UGHTGR4PH/boards/main/versions").json()["name"]
        a.put(f"/TH0UGHTGR4PH/boards/main/nodes/{obj['id']}", json={"title": "renamed theory"})
        check("version saved", v in a.get("/TH0UGHTGR4PH/boards/main/versions").json()["versions"])
        a.post(f"/TH0UGHTGR4PH/boards/main/versions/{v}/restore")
        restored = a.get("/TH0UGHTGR4PH/boards/main/graph").json()
        check("version restore brings back title", restored["nodes"][obj["id"]]["title"] == "theory A")

        # templates are gone
        check("templates endpoint gone", a.get("/TH0UGHTGR4PH/templates").status_code in (404, 405))

        # board zip download/upload roundtrip
        dl = a.get("/TH0UGHTGR4PH/boards/main/download")
        check("board download zip", dl.status_code == 200 and dl.content[:2] == b"PK")
        import io as _io
        import zipfile as _zipfile
        zin = _zipfile.ZipFile(_io.BytesIO(dl.content))
        dl_meta = json.loads(zin.read("meta.json"))
        check("board name travels in meta.json", dl_meta.get("board") == "main")
        # upload under a new name -> creates a new board
        dl_meta["board"] = "maincopy"
        buf = _io.BytesIO()
        with _zipfile.ZipFile(buf, "w") as zout:
            for item in zin.namelist():
                if item == "meta.json":
                    zout.writestr(item, json.dumps(dl_meta))
                else:
                    zout.writestr(item, zin.read(item))
        up = a.post("/TH0UGHTGR4PH/boards/upload", content=buf.getvalue(), headers={"Content-Type": "application/zip"})
        check("upload new name creates board", up.status_code == 200 and up.json()["id"] == "maincopy")
        g = a.get("/TH0UGHTGR4PH/boards/maincopy/graph").json()
        check("uploaded board nodes intact", obj["id"] in g["nodes"])
        # same-name upload -> 409 -> override (versions preserved + snapshot added)
        versions_before = a.get("/TH0UGHTGR4PH/boards/main/versions").json()["versions"]
        up2 = a.post("/TH0UGHTGR4PH/boards/upload", content=dl.content, headers={"Content-Type": "application/zip"})
        check("upload same name conflicts", up2.status_code == 409)
        up3 = a.post("/TH0UGHTGR4PH/boards/upload?override=1", content=dl.content, headers={"Content-Type": "application/zip"})
        check("upload override ok", up3.status_code == 200 and up3.json()["id"] == "main")
        versions_after = a.get("/TH0UGHTGR4PH/boards/main/versions").json()["versions"]
        check("override keeps past versions", all(v in versions_after for v in versions_before))
        check("override snapshots pre-upload state", len(versions_after) == len(versions_before) + 1)
        # illegal uploads rejected
        up4 = a.post("/TH0UGHTGR4PH/boards/upload", content=b"not a zip", headers={"Content-Type": "application/zip"})
        check("bad zip rejected", up4.status_code == 400)
        bad_meta = _io.BytesIO()
        with _zipfile.ZipFile(bad_meta, "w") as zout:
            zout.writestr("meta.json", json.dumps({"nodes": {"x": {"id": "x", "title": "bad", "kind": "func", "node_type": "doc", "x": 0, "y": 0, "parent": None}}, "edges": {}}))
        up5 = a.post("/TH0UGHTGR4PH/boards/upload", content=bad_meta.getvalue(), headers={"Content-Type": "application/zip"})
        check("illegal meta rejected", up5.status_code == 400)

        # channels: WS list/create/send + channel file roundtrip
        async def ws_channels():
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "create", "name": "agent_c"}))
                await ws.send(json.dumps({"cmd": "list_channels"}))
                chans = None
                for _ in range(10):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if m.get("type") == "channels":
                        chans = m["channels"]
                        break
                await ws.send(json.dumps({"cmd": "chat_send", "channel": "dm-agent_c", "text": "hello from user"}))
                got = None
                for _ in range(10):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if m.get("type") == "chat_message":
                        got = m["message"]
                        break
                await ws.send(json.dumps({"cmd": "get_messages", "channel": "dm-agent_c"}))
                msgs = None
                for _ in range(10):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if m.get("type") == "messages":
                        msgs = m["messages"]
                        break
                return chans, got, msgs

        chans, got, msgs = asyncio.run(ws_channels())
        check("dm channel auto-created on agent create", any(c["id"] == "dm-agent_c" for c in (chans or [])))
        check("chat_send broadcasts message", got and got["text"] == "hello from user")
        check("get_messages reads channel", msgs and msgs[-1]["text"] == "hello from user")

        fup = a.post("/INT3RF4CE/chat/dm-agent_c/files?name=note.txt", content=b"channel file")
        check("channel file message", fup.status_code == 200 and fup.json()["file"]["name"] == "note.txt")
        fdl = a.get(f"/INT3RF4CE/chat/dm-agent_c/files/{fup.json()['file']['path']}")
        check("channel file download roundtrip", fdl.status_code == 200 and fdl.content == b"channel file")
        check("unauth channel upload rejected",
              httpx.post(f"{BASE}/INT3RF4CE/chat/dm-agent_c/files?name=x.txt", content=b"x").status_code == 401)
        bad_up = a.post("/INT3RF4CE/chat/dm-agent_c/files?name=virus.exe", content=b"MZ")
        check("executable ext rejected", bad_up.status_code == 400)

        # channels are all groups: member edit + agent-delete cascade
        async def ws_groups():
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "create", "name": "agent_d"}))
                await ws.send(json.dumps({"cmd": "create_channel", "name": "squad", "agents": ["agent_c"]}))
                await ws.send(json.dumps({"cmd": "set_members", "channel": "squad", "agents": ["agent_c", "agent_d"]}))
                chans = None
                for _ in range(12):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if (m.get("type") == "channels"
                            and any(c["name"] == "squad" and len(c["members"]) == 3 for c in m["channels"])):
                        chans = m["channels"]
                        break
                await ws.send(json.dumps({"cmd": "delete", "name": "agent_d"}))
                chans2 = None
                for _ in range(12):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if m.get("type") == "agents":
                        chans2 = m
                        break
                return chans, chans2

        chans, _ = asyncio.run(ws_groups())
        squad = next(c for c in chans if c["name"] == "squad")
        check("group channel with two agents", squad["members"] == ["__user__", "agent_c", "agent_d"])

        # cascade: deleting agent_d strips it but NEVER deletes channels
        from fab.INT3RF4CE.back import chat as chatmod
        final = chatmod.load_channels(WEB_USER_A)
        check("deleted agent stripped from groups", "agent_d" not in final["squad"]["members"])
        check("dm channel survives with only the user", "dm-agent_d" in final and final["dm-agent_d"]["members"] == ["__user__"])
        check("group survives with remaining agent", "agent_c" in final["squad"]["members"])
        # explicit channel delete works
        chatmod.delete_channel(WEB_USER_A, "dm-agent_d")
        check("explicit channel delete", "dm-agent_d" not in chatmod.load_channels(WEB_USER_A))

        # ...but a deleted dm auto-recreates on get_messages (the agent view expects one)
        chatmod.delete_channel(WEB_USER_A, "dm-agent_c")
        async def ws_dm_recreate():
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "get_messages", "channel": "dm-agent_c"}))
                for _ in range(10):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if m.get("type") == "messages":
                        return m
                    if m.get("type") == "error":
                        return m
                return None

        dm_res = asyncio.run(ws_dm_recreate())
        check("deleted dm get_messages does not error", dm_res and dm_res.get("type") == "messages")
        check("deleted dm auto-recreated", "dm-agent_c" in chatmod.load_channels(WEB_USER_A))

        # WS: create agent (no docker side effects) + graph settings roundtrip
        async def ws_flow():
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                first = json.loads(await ws.recv())
                assert first["type"] == "agents"
                await ws.send(json.dumps({"cmd": "create", "name": "agent_a"}))
                await ws.send(json.dumps({"cmd": "set_graph_settings", "name": "agent_a", "settings": {
                    "prompt_docs": [{"board": "main", "id": obj["id"]}],
                    "read": [{"board": "main", "id": mid2["id"]}],
                    "write": [{"board": "main", "id": obj["id"]}],
                    "folders": [{"board": "main", "id": folder["id"]}],
                }}))
                await ws.send(json.dumps({"cmd": "get_graph_settings", "name": "agent_a"}))
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "graph_settings" and msg.get("settings"):
                        return msg["settings"]
                return None

        settings = asyncio.run(ws_flow())
        check("WS graph settings roundtrip", settings
              and settings["prompt_docs"] == [{"board": "main", "id": obj["id"]}]
              and settings["write"] == [{"board": "main", "id": obj["id"]}]
              and settings["folders"] == [{"board": "main", "id": folder["id"]}])
        graph_json = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE" / WEB_USER_A / "config" / "specific" / "agent_a" / "graph.json"
        check("graph.json written on disk", graph_json.exists())

        async def ws_bad_settings():
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "set_graph_settings", "name": "agent_a", "settings": {
                    "prompt_docs": [], "read": [], "write": [{"board": "main", "id": "deadbeef"}],
                }}))
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "error":
                        return msg["msg"]
                return None

        check("WS rejects nodes not on board", "not on board" in (asyncio.run(ws_bad_settings()) or ""))

        async def ws_bad_folder_entry():
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "set_graph_settings", "name": "agent_a", "settings": {
                    "prompt_docs": [], "read": [], "write": [], "folders": [{"board": "main", "id": obj["id"]}],
                }}))
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "error":
                        return msg["msg"]
                return None

        check("WS rejects non-folder in folders list", "must be folders" in (asyncio.run(ws_bad_folder_entry()) or ""))

        # settings files: save / list / load roundtrip
        async def ws_files():
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "save_settings_file", "name": "agent_a", "file_name": "preset1"}))
                await ws.send(json.dumps({"cmd": "list_settings_files"}))
                files = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "settings_files":
                        files = msg["files"]
                        break
                # wipe current settings, then load the preset back
                await ws.send(json.dumps({"cmd": "set_graph_settings", "name": "agent_a", "settings": {"prompt_docs": [], "read": [], "write": []}}))
                # drain the wipe's graph_settings response first
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "graph_settings":
                        break
                await ws.send(json.dumps({"cmd": "load_settings_file", "name": "agent_a", "file_name": "preset1"}))
                loaded = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "graph_settings" and msg.get("settings", {}).get("prompt_docs"):
                        loaded = msg["settings"]
                        break
                return files, loaded

        files, loaded = asyncio.run(ws_files())
        check("settings file saved + listed", files and "preset1" in files)
        check("settings file loads back", loaded and loaded.get("prompt_docs") == [{"board": "main", "id": obj["id"]}])

        # secrets: WS set/list/grants flow — values never come back over the wire
        async def ws_secrets():
            cookie = a.cookies.get("mindology_session")
            headers = [("Cookie", f"mindology_session={cookie}"), ("Origin", BASE)]
            async with websockets.connect(f"ws://127.0.0.1:{TEST_PORT}/INT3RF4CE/ws", additional_headers=headers) as ws:
                await ws.recv()
                await ws.send(json.dumps({"cmd": "set_secret", "key": "deepseek", "value": "sk-ws-test", "cat": "llm"}))
                await ws.send(json.dumps({"cmd": "set_secret", "key": "not_a_provider", "value": "x", "cat": "llm"}))
                bad = None
                items = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "error":
                        bad = msg["msg"]
                    if msg.get("type") == "secrets":
                        items = msg["secrets"]
                    if bad and items:
                        break
                await ws.send(json.dumps({"cmd": "set_secret_grants", "name": "agent_a", "grants": ["deepseek"]}))
                grants = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "secret_grants":
                        grants = msg["grants"]
                        break
                await ws.send(json.dumps({"cmd": "set_secret_grants", "name": "agent_a", "grants": ["nonexistent"]}))
                bad_grant = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "error":
                        bad_grant = msg["msg"]
                        break
                await ws.send(json.dumps({"cmd": "delete_secret", "key": "deepseek"}))
                empty = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "secrets" and msg["secrets"] == []:
                        empty = msg["secrets"]
                        break
                # git entries pass a dict value through; items expose account only
                await ws.send(json.dumps({"cmd": "set_secret", "key": "agent-main",
                                          "value": {"account": "a", "key": "x PRIVATE KEY y"}, "cat": "git"}))
                git_item = None
                for _ in range(10):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    if msg.get("type") == "secrets" and msg["secrets"]:
                        git_item = msg["secrets"][0]
                        break
                return bad, items, grants, bad_grant, empty, git_item

        bad, items, grants, bad_grant, empty, git_item = asyncio.run(ws_secrets())
        check("WS set_secret lists names+cats (no values)", items == [{"name": "deepseek", "cat": "llm"}])
        check("WS rejects non-provider llm name", "llm secret must be one of" in (bad or ""))
        check("WS grants roundtrip", grants == ["deepseek"])
        check("WS rejects granting unknown secret", "unknown secrets" in (bad_grant or ""))
        check("WS delete_secret clears store", empty == [])
        check("WS git dict value roundtrip", git_item
              and git_item["cat"] == "git" and git_item["value"] == {"account": "a"})
        grants_path = PROJECT_ROOT / "fab" / "data" / "INT3RF4CE" / WEB_USER_A / "config" / "specific" / "agent_a" / "secrets.json"
        check("delete stripped grants on disk", json.loads(grants_path.read_text())["grants"] == [])

        # isolation
        check("B boards are its own", b.get("/TH0UGHTGR4PH/boards").json()["boards"] == ["main"])
        b_graph = b.get("/TH0UGHTGR4PH/boards/main/graph").json()
        check("B graph empty (isolation)", b_graph["nodes"] == {} and b_graph["edges"] == {})
        check("B types are default (isolation)", "custom_type" not in b.get("/TH0UGHTGR4PH/types").json()["doc_types"])

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
