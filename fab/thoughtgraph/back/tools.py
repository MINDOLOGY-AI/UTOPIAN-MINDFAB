'''thoughtgraph tools: the G* commands, registered into corechat's central COMMANDS.
corechat must import this module for registration to happen (the plumbing line).
access: doc-level grants only (access.json read/write entries, write implies read).
agents can never create docs — the human owns structure. edges: write on one
endpoint + at least read on the other. violations raise; commands.dispatch turns
them into [ERROR] tool results.'''

from fab.corechat.back.commands import register
from fab.thoughtgraph.back import actions, storage


def _grants(agent_name: str) -> dict:
    return storage.load_access().get(agent_name, {})


def _can_read(agent_name: str, board: str, nid: str) -> bool:
    g = _grants(agent_name)
    return any(e["board"] == board and e["id"] == nid
               for key in ("read", "write") for e in g.get(key, []))


def _can_write(agent_name: str, board: str, nid: str) -> bool:
    g = _grants(agent_name)
    return any(e["board"] == board and e["id"] == nid for e in g.get("write", []))


def _require(agent_name: str, board: str, nid: str, write: bool = False):
    ok = _can_write(agent_name, board, nid) if write else _can_read(agent_name, board, nid)
    if not ok:
        raise ValueError(f"no {'write' if write else 'read'} access to {nid!r} on board {board!r}")


# the docs an agent may see: its read + write entries on this board
def _visible_set(agent_name: str, board: str) -> set:
    g = _grants(agent_name)
    return {e["id"] for key in ("read", "write") for e in g.get(key, []) if e["board"] == board}


# edges: you must own (write) one side and at least see (read) the other
def _require_edge(agent_name: str, board: str, src: str, tgt: str):
    for owned, other in ((src, tgt), (tgt, src)):
        if _can_write(agent_name, board, owned) and _can_read(agent_name, board, other):
            return
    raise ValueError("edge needs your write on one endpoint and at least read on the other")


async def _gmap(args: dict, agent) -> str:
    return actions.gmap(args["board"], ref=args.get("ref"), visible=_visible_set(agent.name, args["board"]))


async def _gread(args: dict, agent) -> str:
    board = args["board"]
    meta = storage.load_meta(board)
    nid = actions.resolve_node(meta, args["ref"])
    _require(agent.name, board, nid)
    r = actions.read_node(board, nid)
    n = r["node"]
    lines = [f"{actions.node_path(meta, nid)} ({n['node_type']}) id={nid}"]
    if n["ref"]:
        lines.append(f"ref: {n['ref']}")
    lines.append("---")
    lines.append(r["content"] or "(empty)")
    if r["connected"]:
        lines.append("---")
        lines.append("connected:")
        for c in r["connected"]:
            arrow = "->" if c["direction"] == "out" else "<-"
            lines.append(f"  {arrow} {c['title']} ({c['node_type']})")
    return "\n".join(lines)


async def _gedit(args: dict, agent) -> str:
    board = args["board"]
    meta = storage.load_meta(board)
    nid = actions.resolve_node(meta, args["ref"])
    _require(agent.name, board, nid, write=True)
    node = actions.edit_node(board, nid, args["old"], args["new"])
    return f"[GEDIT] '{node['title']}' updated"


async def _gmeta(args: dict, agent) -> str:
    board = args["board"]
    meta = storage.load_meta(board)
    nid = actions.resolve_node(meta, args["ref"])
    _require(agent.name, board, nid, write=True)
    fields = {k: args[k] for k in ("title", "node_type", "x", "y", "parent", "expanded", "color") if k in args}
    node = actions.set_meta(board, nid, **fields)
    return f"[GMETA] '{node['title']}' updated: {sorted(fields)}"


async def _gdestroy(args: dict, agent) -> str:
    board = args["board"]
    meta = storage.load_meta(board)
    nid = actions.resolve_node(meta, args["ref"])
    _require(agent.name, board, nid, write=True)
    r = actions.destroy_node(board, nid)
    return f"[GDESTROY] deleted {len(r['deleted'])} nodes"


async def _glink(args: dict, agent) -> str:
    board = args["board"]
    meta = storage.load_meta(board)
    src = actions.resolve_node(meta, args["source"])
    tgt = actions.resolve_node(meta, args["target"])
    _require_edge(agent.name, board, src, tgt)
    e = actions.link(board, src, tgt, args["edge_type"])
    return f"[GLINK] linked -({e['edge_type']})->"


async def _gdlink(args: dict, agent) -> str:
    board = args["board"]
    meta = storage.load_meta(board)
    src = actions.resolve_node(meta, args["source"])
    tgt = actions.resolve_node(meta, args["target"])
    _require_edge(agent.name, board, src, tgt)
    actions.unlink(board, src, tgt)
    return "[GDLINK] edge removed"


_BOARD = {"type": "string", "description": "board name, usually 'main'"}
_REF = {"type": "string", "description": "node title or id"}


def _schema(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


register("GMAP", _schema(
    "GMAP", "list the thoughtgraph docs you can see: one line per node as 'path (type)', then all edges between them. pass a folder title as ref to scope to its subtree",
    {"board": _BOARD, "ref": {"type": "string", "description": "optional folder title to scope to"}}, ["board"]), _gmap)

register("GREAD", _schema(
    "GREAD", "read one node you have access to: its meta, full markdown content, and connected nodes",
    {"board": _BOARD, "ref": _REF}, ["board", "ref"]), _gread)

register("GEDIT", _schema(
    "GEDIT", "edit a doc you have write access to: replace one occurrence of old with new (old must occur exactly once — include enough context). on an empty doc, old=\"\" writes new as the full content",
    {"board": _BOARD, "ref": _REF,
     "old": {"type": "string", "description": "exact string to replace, must occur exactly once (\"\" to fill an empty doc)"},
     "new": {"type": "string", "description": "replacement string"}},
    ["board", "ref", "old", "new"]), _gedit)

register("GMETA", _schema(
    "GMETA", "change a node's metadata: rename, retype, move/reparent, expand, color. never touches content. you cannot create nodes",
    {"board": _BOARD, "ref": _REF,
     "title": {"type": "string", "description": "new title (renames the file)"},
     "node_type": {"type": "string", "description": "new doc type"},
     "x": {"type": "number", "description": "new x (root: grid-snapped absolute; child: folder-relative)"},
     "y": {"type": "number", "description": "new y"},
     "parent": {"type": ["string", "null"], "description": "new parent folder title, or null to move to root"},
     "expanded": {"type": "boolean"},
     "color": {"type": "string", "description": "hex color override"}},
    ["board", "ref"]), _gmeta)

register("GDESTROY", _schema(
    "GDESTROY", "delete a node you have write access to and its whole subtree — files, nodes, and connected edges. irreversible",
    {"board": _BOARD, "ref": _REF}, ["board", "ref"]), _gdestroy)

register("GLINK", _schema(
    "GLINK", "create a typed edge between two docs (or retype it if it already exists). needs your write access on one endpoint and at least read on the other. edge types live in the board's type registry, e.g. support/reject/causes/training",
    {"board": _BOARD,
     "source": {"type": "string", "description": "source doc title"},
     "target": {"type": "string", "description": "target doc title"},
     "edge_type": {"type": "string", "description": "edge type"}},
    ["board", "source", "target", "edge_type"]), _glink)

register("GDLINK", _schema(
    "GDLINK", "remove the edge from source to target. same access rule as GLINK",
    {"board": _BOARD,
     "source": {"type": "string", "description": "source doc title"},
     "target": {"type": "string", "description": "target doc title"}},
    ["board", "source", "target"]), _gdlink)
