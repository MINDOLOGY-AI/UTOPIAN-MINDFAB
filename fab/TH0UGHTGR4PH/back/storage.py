import json
import secrets
import shutil
from pathlib import Path

from fab.TH0UGHTGR4PH.back.config import (
    DATA_DIR,
    DEFAULT_DOC_TYPES,
    DEFAULT_EDGE_TYPES,
    DEFAULT_STATE_COLORS,
)

# per-user layout: fab/data/TH0UGHTGR4PH/{user}/{types.json, {board}/}
# each board is a self-contained directory: meta.json + tree/ (content) + versions/


def _user_dir(user: str) -> Path:
    return DATA_DIR / user


def _board_dir(user: str, board_id: str) -> Path:
    return _user_dir(user) / board_id


def _meta_file(user: str, board_id: str) -> Path:
    return _board_dir(user, board_id) / "meta.json"


def _content_dir(user: str, board_id: str) -> Path:
    return _board_dir(user, board_id) / "content"


def _versions_dir(user: str, board_id: str) -> Path:
    return _board_dir(user, board_id) / "versions"


def _types_file(user: str) -> Path:
    return _user_dir(user) / "types.json"


def _write_json(path: Path, data):
    # atomic write so concurrent reads never see a half-written file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def new_id(existing) -> str:
    nid = secrets.token_hex(4)
    while nid in existing:
        nid = secrets.token_hex(4)
    return nid


# ---- user / board init ----


def init_user_storage(user: str):
    """Ensure the user's data dir exists. Seed types and a 'main' board on first use."""
    d = _user_dir(user)
    first_time = not d.exists()
    d.mkdir(parents=True, exist_ok=True)
    if first_time:
        _write_json(_types_file(user), {
            "doc_types": DEFAULT_DOC_TYPES,
            "edge_types": DEFAULT_EDGE_TYPES,
            "state_colors": DEFAULT_STATE_COLORS,
        })
        init_board(user, "main")


def init_board(user: str, board_id: str):
    d = _board_dir(user, board_id)
    d.mkdir(parents=True, exist_ok=True)
    # vestigial empty dir — doc content actually lives in tree/ (see content_path)
    _content_dir(user, board_id).mkdir(exist_ok=True)
    if not _meta_file(user, board_id).exists():
        save_meta(user, board_id, {"nodes": {}, "edges": {}})


def list_boards(user: str):
    d = _user_dir(user)
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def rename_board(user: str, board_id: str, new_board_id: str):
    src = _board_dir(user, board_id)
    dst = _board_dir(user, new_board_id)
    assert src.exists()
    assert not dst.exists()
    src.rename(dst)


def delete_board(user: str, board_id: str):
    d = _board_dir(user, board_id)
    if d.exists():
        shutil.rmtree(d)


# ---- meta ----


def load_meta(user: str, board_id: str):
    return _read_json(_meta_file(user, board_id), {"nodes": {}, "edges": {}})


def save_meta(user: str, board_id: str, meta):
    _write_json(_meta_file(user, board_id), meta)


# ---- content ----
# docs live at {board}/tree/{ancestor folder titles}/{title}.md — the title IS
# the path. folders are plain directories. titles must therefore be unique per
# board and filesystem-safe (enforced in graph_actions on create/rename).

MAX_TITLE_CHARS = 120


def validate_title(title: str) -> str:
    """Normalize + validate a title for use as a file path component."""
    t = title.strip()
    if not t:
        raise ValueError("title cannot be empty")
    if len(t) > MAX_TITLE_CHARS:
        raise ValueError(f"title too long (max {MAX_TITLE_CHARS} chars)")
    if t.startswith("."):
        raise ValueError("title cannot start with '.'")
    if "/" in t or "\\" in t:
        raise ValueError("title cannot contain '/' or '\\' (titles become file paths)")
    if any(ord(c) < 32 for c in t):
        raise ValueError("title cannot contain control characters")
    return t


def require_unique_title(meta, title: str, exclude_id: str | None = None):
    for nid, n in meta["nodes"].items():
        if nid != exclude_id and n["title"] == title:
            raise ValueError(f"title already exists: {title!r} (titles must be unique — they become file paths)")


def content_path(user: str, board_id: str, meta, node_id: str) -> Path:
    # docs: tree/<folders...>/<title>.md — folders: tree/<folders...>/<title>/
    node = meta["nodes"][node_id]
    parts = [node["title"]]
    cur = node
    while cur["parent"]:
        cur = meta["nodes"][cur["parent"]]
        parts.append(cur["title"])
    parts.reverse()
    p = _board_dir(user, board_id) / "tree"
    for part in parts:
        p = p / part
    return p if node["kind"] == "folder" else p.with_suffix(".md")


def read_content(user: str, board_id: str, meta, node_id: str) -> str:
    p = content_path(user, board_id, meta, node_id)
    if not p.exists():
        return ""
    return p.read_text()


def write_content(user: str, board_id: str, meta, node_id: str, content: str):
    p = content_path(user, board_id, meta, node_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _rmdir_empty_ancestors(p: Path, stop: Path):
    # remove empty dirs upward from a deleted file's parent, never past `stop`
    cur = p.parent
    while cur != stop and cur.is_dir():
        try:
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def delete_content(user: str, board_id: str, meta, node_id: str):
    p = content_path(user, board_id, meta, node_id)
    if meta["nodes"][node_id]["kind"] == "folder":
        if p.exists():
            shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    _rmdir_empty_ancestors(p, _board_dir(user, board_id) / "tree")


def move_content(user: str, board_id: str, old_meta, meta, node_id: str):
    # old_meta = the pre-mutation meta (same node, old title/parent chain)
    old_p = content_path(user, board_id, old_meta, node_id)
    new_p = content_path(user, board_id, meta, node_id)
    if old_p == new_p or not old_p.exists():
        return
    new_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_p), str(new_p))
    _rmdir_empty_ancestors(old_p, _board_dir(user, board_id) / "tree")


# ---- types registry ----


def load_types(user: str):
    types = _read_json(_types_file(user), None)
    if not isinstance(types, dict):
        types = {}
    # backfill presets: default types can be recolored but never permanently
    # deleted — an emptied registry breaks node creation board-wide.
    # custom (user-added) types are kept as-is.
    for section, defaults in (
        ("doc_types", DEFAULT_DOC_TYPES),
        ("edge_types", DEFAULT_EDGE_TYPES),
        ("state_colors", DEFAULT_STATE_COLORS),
    ):
        disk = types.get(section) or {}
        types[section] = {**defaults, **disk}
    return types


def save_types(user: str, types):
    _write_json(_types_file(user), types)


# ---- versions ----


def list_versions(user: str, board_id: str):
    d = _versions_dir(user, board_id)
    d.mkdir(exist_ok=True)
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def _copy_data_tree(src_dir: Path, dst_dir: Path):
    # copy everything except the versions folder itself (no recursive snapshots)
    versions_dir = src_dir / "versions"
    for p in src_dir.iterdir():
        if p == versions_dir:
            continue
        if p.is_dir():
            shutil.copytree(p, dst_dir / p.name)
        else:
            shutil.copy2(p, dst_dir / p.name)


def save_version(user: str, board_id: str):
    d = _versions_dir(user, board_id)
    d.mkdir(exist_ok=True)
    nums = [int(n.split("_")[1]) for n in list_versions(user, board_id)]
    name = f"version_{max(nums) + 1 if nums else 0}"
    dst = d / name
    dst.mkdir()
    _copy_data_tree(_board_dir(user, board_id), dst)
    return name


def delete_version(user: str, board_id: str, name: str):
    if name not in list_versions(user, board_id):
        raise ValueError("version not found")
    shutil.rmtree(_versions_dir(user, board_id) / name)


def restore_version(user: str, board_id: str, name: str):
    if name not in list_versions(user, board_id):
        raise ValueError("version not found")
    board_dir = _board_dir(user, board_id)
    versions_dir = _versions_dir(user, board_id)
    for p in board_dir.iterdir():
        if p == versions_dir:
            continue
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    _copy_data_tree(versions_dir / name, board_dir)
