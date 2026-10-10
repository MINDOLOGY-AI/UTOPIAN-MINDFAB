'''thoughtgraph: the graph, the disk tree they mirror, and the two front doors (REST for the
board UI, G* tools for agents). the disk tree is the point — every structural change has to
land as real .md files and folders, and hand edits have to fold back in.'''

import asyncio
import io
import json
import zipfile

import pytest

from fab.corechat.back import commands
from fab.thoughtgraph.back import actions, storage
from fab.thoughtgraph.back.config import GRID_SIZE, MAX_CONTENT_CHARS
from hub.test.conftest import StubAgent

USER = "tester"


@pytest.fixture
def board(fab_home) -> str:
    # the world the api seeds on a user's first touch
    storage.init(USER)
    return "main"


@pytest.fixture
def tool_agent(board) -> StubAgent:
    return StubAgent(USER, "helper")


def tree(board: str, *parts):
    return storage.tree_dir(USER, board).joinpath(*parts)


def run_tool(name: str, agent: StubAgent, **args) -> str:
    return asyncio.run(commands.COMMANDS[name]["handler"](args, agent))


def grant(read=(), write=(), board: str = "main", agent: str = "helper"):
    storage.save_access(USER, {agent: {"read": [{"board": board, "id": i} for i in read],
                                       "write": [{"board": board, "id": i} for i in write]}})


# ---- boards ----

def test_init_seeds_types_and_a_main_board(board):
    assert storage.list_boards(USER) == ["main"]
    assert "axiom" in storage.load_types(USER)["doc_types"]


def test_board_rename_and_delete_move_the_whole_directory(board):
    actions.create_node(USER, "main", "note", "doc")
    storage.rename_board(USER, "main", "renamed")
    assert storage.list_boards(USER) == ["renamed"]
    assert tree("renamed", "note.md").exists()
    storage.delete_board(USER, "renamed")
    assert storage.list_boards(USER) == []


# ---- nodes and the files behind them ----

def test_creating_a_doc_writes_its_file(board):
    node = actions.create_node(USER, "main", "mission", "doc")
    assert tree("main", "mission.md").exists(), "every doc must have a file — reconcile drops fileless docs"
    assert node["node_type"] == "doc" and node["parent"] is None


def test_a_doc_inside_a_folder_nests_on_disk(board):
    folder = actions.create_node(USER, "main", "research", "folder")
    actions.create_node(USER, "main", "sae", "doc", parent=folder["id"])
    assert tree("main", "research", "sae.md").exists()


@pytest.mark.parametrize("title", ["", "   ", ".hidden", "a/b", "a\\b", "x" * 200, "bad\x01"])
def test_invalid_titles_are_refused(board, title):
    # titles become path components, so the charset is the whole safety story
    with pytest.raises(ValueError):
        actions.create_node(USER, "main", title, "doc")


def test_titles_are_unique_per_board(board):
    actions.create_node(USER, "main", "dup", "doc")
    with pytest.raises(ValueError, match="already exists"):
        actions.create_node(USER, "main", "dup", "doc")


def test_structural_rules(board):
    doc = actions.create_node(USER, "main", "plain", "doc")
    with pytest.raises(ValueError, match="kind must be"):
        actions.create_node(USER, "main", "weird", "sketch")
    with pytest.raises(ValueError, match="unknown doc type"):
        actions.create_node(USER, "main", "typed", "doc", node_type="nonsense")
    with pytest.raises(ValueError, match="parent must be a folder"):
        actions.create_node(USER, "main", "child", "doc", parent=doc["id"])


def test_root_nodes_snap_to_the_grid_but_children_do_not(board):
    root = actions.create_node(USER, "main", "root", "doc", x=310, y=90)
    assert root["x"] % GRID_SIZE == 0 and root["y"] % GRID_SIZE == 0
    folder = actions.create_node(USER, "main", "box", "folder")
    child = actions.create_node(USER, "main", "kid", "doc", parent=folder["id"], x=37, y=12)
    assert (child["x"], child["y"]) == (37, 12), "child coords are folder-relative, not snapped"


def test_rename_moves_the_file_and_reparent_moves_the_tree(board):
    folder = actions.create_node(USER, "main", "box", "folder")
    doc = actions.create_node(USER, "main", "before", "doc")
    actions.edit_node(USER, "main", doc["id"], "", "body text")

    actions.set_meta(USER, "main", doc["id"], title="after")
    assert tree("main", "after.md").read_text() == "body text"
    assert not tree("main", "before.md").exists()

    actions.set_meta(USER, "main", doc["id"], parent=folder["id"])
    assert tree("main", "box", "after.md").read_text() == "body text"
    assert not tree("main", "after.md").exists()


def test_a_folder_cannot_be_moved_into_its_own_subtree(board):
    outer = actions.create_node(USER, "main", "outer", "folder")
    inner = actions.create_node(USER, "main", "inner", "folder", parent=outer["id"])
    with pytest.raises(ValueError, match="own subtree"):
        actions.set_meta(USER, "main", outer["id"], parent=inner["id"])


def test_destroy_takes_the_subtree_its_files_and_its_edges(board):
    folder = actions.create_node(USER, "main", "box", "folder")
    child = actions.create_node(USER, "main", "kid", "doc", parent=folder["id"])
    other = actions.create_node(USER, "main", "survivor", "doc")
    actions.link(USER, "main", child["id"], other["id"], "support")

    result = actions.destroy_node(USER, "main", folder["id"])

    assert set(result["deleted"]) == {folder["id"], child["id"]}
    assert not tree("main", "box").exists()
    meta = storage.load_meta(USER, "main")
    assert list(meta["nodes"]) == [other["id"]]
    assert meta["edges"] == {}, "edges touching a deleted node must go with it"


# ---- content ----

def test_gedit_replaces_exactly_one_occurrence(board):
    doc = actions.create_node(USER, "main", "doc", "doc")
    actions.edit_node(USER, "main", doc["id"], "", "alpha beta alpha")
    with pytest.raises(ValueError, match="occurs 2 times"):
        actions.edit_node(USER, "main", doc["id"], "alpha", "gamma")
    with pytest.raises(ValueError, match="not found"):
        actions.edit_node(USER, "main", doc["id"], "missing", "x")
    actions.edit_node(USER, "main", doc["id"], "beta", "gamma")
    assert storage.read_content(USER, "main", storage.load_meta(USER, "main"), doc["id"]) == "alpha gamma alpha"


def test_gedit_refuses_folders(board):
    folder = actions.create_node(USER, "main", "box", "folder")
    with pytest.raises(ValueError, match="requires a doc"):
        actions.edit_node(USER, "main", folder["id"], "", "x")


# ---- edges ----

def test_edge_lifecycle(board):
    a = actions.create_node(USER, "main", "a", "doc")
    b = actions.create_node(USER, "main", "b", "doc")
    edge = actions.link(USER, "main", a["id"], b["id"], "support")
    # the same pair links once and gets retyped, never duplicated
    again = actions.link(USER, "main", a["id"], b["id"], "reject")
    assert again["id"] == edge["id"] and again["edge_type"] == "reject"
    assert len(storage.load_meta(USER, "main")["edges"]) == 1
    actions.unlink(USER, "main", a["id"], b["id"])
    assert storage.load_meta(USER, "main")["edges"] == {}
    with pytest.raises(ValueError, match="no edge"):
        actions.unlink(USER, "main", a["id"], b["id"])


def test_edge_rules(board):
    a = actions.create_node(USER, "main", "a", "doc")
    folder = actions.create_node(USER, "main", "box", "folder")
    with pytest.raises(ValueError, match="itself"):
        actions.link(USER, "main", a["id"], a["id"], "support")
    with pytest.raises(ValueError, match="not folders"):
        actions.link(USER, "main", a["id"], folder["id"], "support")
    b = actions.create_node(USER, "main", "b", "doc")
    with pytest.raises(ValueError, match="unknown edge type"):
        actions.link(USER, "main", a["id"], b["id"], "vibes")


def test_nodes_resolve_by_title_or_id(board):
    node = actions.create_node(USER, "main", "by title", "doc")
    meta = storage.load_meta(USER, "main")
    assert actions.resolve_node(meta, "by title") == node["id"]
    assert actions.resolve_node(meta, node["id"]) == node["id"]
    with pytest.raises(ValueError, match="not found"):
        actions.resolve_node(meta, "ghost")


# ---- reconcile: the disk is editable by hand, and the graph has to follow ----

def test_a_hand_written_file_is_adopted_with_its_folders(board):
    tree("main", "notes", "deep").mkdir(parents=True)
    tree("main", "notes", "deep", "found.md").write_text("written in neovim")
    meta = storage.load_meta(USER, "main")
    titles = {n["title"]: n for n in meta["nodes"].values()}
    assert set(titles) == {"notes", "deep", "found"}
    assert titles["notes"]["kind"] == "folder" and titles["found"]["kind"] == "doc"
    assert actions.node_path(meta, titles["found"]["id"]) == "notes/deep/found"


def test_a_hand_deleted_file_drops_its_node_and_edges(board):
    doc = actions.create_node(USER, "main", "doomed", "doc")
    other = actions.create_node(USER, "main", "keeper", "doc")
    actions.link(USER, "main", doc["id"], other["id"], "support")
    tree("main", "doomed.md").unlink()
    meta = storage.load_meta(USER, "main")
    assert list(meta["nodes"]) == [other["id"]]
    assert meta["edges"] == {}


def test_a_filename_the_graph_cannot_represent_is_skipped(board):
    actions.create_node(USER, "main", "taken", "doc")
    tree("main", "sub").mkdir()
    tree("main", "sub", "taken.md").write_text("duplicate title")  # titles are unique per board
    meta = storage.load_meta(USER, "main")
    assert len([n for n in meta["nodes"].values() if n["title"] == "taken"]) == 1


# ---- gmap: the model's picture of the graph ----

def test_gmap_scopes_to_a_folder_and_to_what_an_agent_may_see(board):
    folder = actions.create_node(USER, "main", "box", "folder")
    inside = actions.create_node(USER, "main", "inside", "doc", parent=folder["id"])
    outside = actions.create_node(USER, "main", "outside", "doc")
    actions.link(USER, "main", inside["id"], outside["id"], "support")

    scoped = actions.gmap(USER, "main", ref=folder["id"])
    assert "box/inside" in scoped and "outside (doc)" in scoped, "an edge leaving the scope still shows"

    visible = actions.gmap(USER, "main", visible={outside["id"]})
    assert "outside" in visible and "inside" not in visible
    assert "-(support)->" not in visible, "an edge needs BOTH endpoints visible"

    with pytest.raises(ValueError, match="must be a folder"):
        actions.gmap(USER, "main", ref=outside["id"])


# ---- types, access, presets ----

def test_default_types_can_be_recoloured_but_never_lost(board):
    storage.save_types(USER, {"doc_types": {"axiom": {"color": "#000000"}}, "edge_types": {}})
    types = storage.load_types(USER)
    assert types["doc_types"]["axiom"]["color"] == "#000000"
    assert "hypothesis" in types["doc_types"], "a default type must survive a partial save"
    assert "support" in types["edge_types"]


def test_presets_stamp_one_agent_s_access_onto_another(client, user):
    node = client.post("/thoughtgraph/boards/main/nodes", json={"title": "doc", "kind": "doc"}).json()
    access = {"a": {"read": [{"board": "main", "id": node["id"]}], "write": []}}
    assert client.put("/thoughtgraph/access", json=access).status_code == 200
    assert client.post("/thoughtgraph/presets/save", json={"name": "reader", "agent": "a"}).status_code == 200
    assert client.post("/thoughtgraph/presets/load", json={"name": "reader", "agent": "b"}).status_code == 200
    assert client.get("/thoughtgraph/access").json()["b"] == access["a"]


def test_access_entries_for_dead_agents_are_collected(client, user, fab_home):
    from hub.test.conftest import make_agent
    make_agent(user, "alive")
    client.put("/thoughtgraph/access", json={"alive": {"read": [], "write": []},
                                             "ghost": {"read": [], "write": []}})
    assert client.get("/thoughtgraph/agents").json()["agents"] == ["alive"]
    assert list(client.get("/thoughtgraph/access").json()) == ["alive"]


# ---- the REST door ----

def test_rest_board_and_node_round_trip(client, user):
    assert client.post("/thoughtgraph/boards", json={"board_id": "second"}).status_code == 200
    assert "second" in client.get("/thoughtgraph/boards").json()["boards"]
    node = client.post("/thoughtgraph/boards/second/nodes", json={"title": "n", "kind": "doc"}).json()
    client.put(f"/thoughtgraph/boards/second/nodes/{node['id']}/content", json={"content": "body"})
    assert client.get(f"/thoughtgraph/boards/second/nodes/{node['id']}/content").json()["content"] == "body"
    graph = client.get("/thoughtgraph/boards/second/graph").json()
    assert list(graph["nodes"]) == [node["id"]]
    assert client.delete(f"/thoughtgraph/boards/second/nodes/{node['id']}").status_code == 200
    assert client.delete("/thoughtgraph/boards/second").status_code == 200


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b"])
def test_rest_refuses_board_ids_that_escape_the_directory(client, user, bad):
    with pytest.raises(ValueError, match="invalid board id"):
        client.post("/thoughtgraph/boards", json={"board_id": bad})


def test_board_zip_round_trip(client, user):
    node = client.post("/thoughtgraph/boards/main/nodes", json={"title": "packed", "kind": "doc"}).json()
    client.put(f"/thoughtgraph/boards/main/nodes/{node['id']}/content", json={"content": "in the zip"})
    blob = client.get("/thoughtgraph/boards/main/download").content
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert "meta.json" in names and "tree/packed.md" in names

    # the board name travels inside meta.json, and an existing board is refused without override
    assert client.post("/thoughtgraph/boards/upload", content=blob).status_code == 409
    assert client.post("/thoughtgraph/boards/upload?override=1", content=blob).status_code == 200
    assert client.get(f"/thoughtgraph/boards/main/nodes/{node['id']}/content").json()["content"] == "in the zip"


def test_upload_ignores_entries_that_escape_the_board(client, user):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("meta.json", json.dumps({"board": "zipped", "nodes": {}, "edges": {}}))
        z.writestr("tree/../../escaped.md", "should never be written")  # zip slip
        z.writestr("tree/fine.md", "ok")
    assert client.post("/thoughtgraph/boards/upload", content=buf.getvalue()).status_code == 200
    assert (storage.tree_dir(user, "zipped") / "fine.md").exists()
    # "tree/../../escaped.md" resolves out of the board dir into the thoughtgraph root —
    # that exact path is what the guard has to refuse
    assert not (storage.tg_dir(user) / "escaped.md").exists()


# ---- the G* tools: the human owns structure, agents get doc-level grants ----

def test_gmap_shows_an_agent_only_its_grants(tool_agent):
    seen = actions.create_node(USER, "main", "seen", "doc")
    actions.create_node(USER, "main", "unseen", "doc")
    grant(read=[seen["id"]])
    out = run_tool("GMAP", tool_agent)
    assert "seen" in out and "unseen" not in out


def test_gread_needs_a_grant(tool_agent):
    node = actions.create_node(USER, "main", "secret", "doc")
    actions.edit_node(USER, "main", node["id"], "", "the contents")
    grant()
    with pytest.raises(ValueError, match="no read access"):
        run_tool("GREAD", tool_agent, board="main", ref="secret")
    grant(read=[node["id"]])
    assert "the contents" in run_tool("GREAD", tool_agent, board="main", ref="secret")


def test_read_access_is_not_write_access(tool_agent):
    node = actions.create_node(USER, "main", "doc", "doc")
    grant(read=[node["id"]])
    with pytest.raises(ValueError, match="no write access"):
        run_tool("GEDIT", tool_agent, board="main", ref="doc", old="", new="mine now")
    with pytest.raises(ValueError, match="no write access"):
        run_tool("GMETA", tool_agent, board="main", ref="doc", title="renamed")
    with pytest.raises(ValueError, match="no write access"):
        run_tool("GDESTROY", tool_agent, board="main", ref="doc")


def test_an_agent_writes_only_what_it_was_given(tool_agent):
    node = actions.create_node(USER, "main", "mine", "doc")
    grant(write=[node["id"]])
    run_tool("GEDIT", tool_agent, board="main", ref="mine", old="", new="first draft")
    assert "first draft" in run_tool("GREAD", tool_agent, board="main", ref="mine")
    run_tool("GMETA", tool_agent, board="main", ref="mine", title="renamed")
    assert tree("main", "renamed.md").exists()


def test_an_edge_needs_write_on_one_side_and_read_on_the_other(tool_agent):
    mine = actions.create_node(USER, "main", "mine", "doc")
    theirs = actions.create_node(USER, "main", "theirs", "doc")
    grant(write=[mine["id"]])
    with pytest.raises(ValueError, match="edge needs"):
        run_tool("GLINK", tool_agent, board="main", source="mine", target="theirs", edge_type="support")
    grant(read=[theirs["id"]], write=[mine["id"]])
    run_tool("GLINK", tool_agent, board="main", source="mine", target="theirs", edge_type="support")
    assert len(storage.load_meta(USER, "main")["edges"]) == 1
    run_tool("GDLINK", tool_agent, board="main", source="mine", target="theirs")
    assert storage.load_meta(USER, "main")["edges"] == {}


def test_agents_have_no_tool_that_creates_a_node(tool_agent):
    # structure is the human's; the tool list is the enforcement
    assert not any(name.startswith("GCREATE") or name == "GNEW" for name in commands.COMMANDS)


def test_rest_edge_and_type_routes(client, user):
    a = client.post("/thoughtgraph/boards/main/nodes", json={"title": "a", "kind": "doc"}).json()
    b = client.post("/thoughtgraph/boards/main/nodes", json={"title": "b", "kind": "doc"}).json()
    edge = client.post("/thoughtgraph/boards/main/edges",
                       json={"source": a["id"], "target": b["id"], "edge_type": "support"}).json()
    assert edge["edge_type"] == "support"
    retyped = client.put(f"/thoughtgraph/boards/main/edges/{edge['id']}",
                         json={"edge_type": "reject"}).json()
    assert retyped["id"] == edge["id"] and retyped["edge_type"] == "reject"
    assert client.delete(f"/thoughtgraph/boards/main/edges/{edge['id']}").status_code == 200
    assert client.get("/thoughtgraph/boards/main/graph").json()["edges"] == {}

    types = client.get("/thoughtgraph/types").json()
    assert "axiom" in types["doc_types"] and "support" in types["edge_types"]
    types["edge_types"]["custom"] = {"color": "#123456"}
    client.put("/thoughtgraph/types", json=types)
    assert "custom" in client.get("/thoughtgraph/types").json()["edge_types"]


def test_rest_board_rename_and_content_cap(client, user):
    assert client.put("/thoughtgraph/boards/main", json={"board_id": "renamed"}).status_code == 200
    assert client.get("/thoughtgraph/boards").json()["boards"] == ["renamed"]
    node = client.post("/thoughtgraph/boards/renamed/nodes", json={"title": "n", "kind": "doc"}).json()
    with pytest.raises(ValueError, match="content too large"):
        client.put(f"/thoughtgraph/boards/renamed/nodes/{node['id']}/content",
                   json={"content": "x" * (MAX_CONTENT_CHARS + 1)})
