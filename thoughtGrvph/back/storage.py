import json
import shutil
from pathlib import Path

# Project root is two levels above this file: .../UTOPIAN-MINDFAB
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Each board is a self-contained directory under thoughts/thoughtgrvph.
BOARDS_DIR = PROJECT_ROOT / "thoughts" / "thoughtgrvph"
LEGACY_META = BOARDS_DIR / "meta.json"
GRID_SIZE = 200


def _board_dir(board_id: str) -> Path:
    return BOARDS_DIR / board_id


def _meta_file(board_id: str) -> Path:
    return _board_dir(board_id) / "meta.json"


def _versions_dir(board_id: str) -> Path:
    return _board_dir(board_id) / "versions"


def migrate_legacy():
    """Move old flat data/ layout into a 'main' board."""
    if not LEGACY_META.exists():
        return
    main_dir = _board_dir("main")
    main_dir.mkdir(parents=True, exist_ok=True)
    for p in BOARDS_DIR.iterdir():
        if p == main_dir:
            continue
        dest = main_dir / p.name
        if dest.exists():
            # Shouldn't happen in practice; skip to avoid clobbering.
            continue
        shutil.move(str(p), str(dest))


def init_storage():
    BOARDS_DIR.mkdir(parents=True, exist_ok=True)
    migrate_legacy()
    init_board("main")


def init_board(board_id: str):
    d = _board_dir(board_id)
    d.mkdir(parents=True, exist_ok=True)
    if not _meta_file(board_id).exists():
        save_meta(board_id, {"nodes": {}, "edges": {}})
    else:
        migrate_to_grid(board_id)


def migrate_to_grid(board_id: str):
    meta = load_meta(board_id)
    changed = False
    for n in meta["nodes"].values():
        sx = round(n["x"] / GRID_SIZE) * GRID_SIZE
        sy = round(n["y"] / GRID_SIZE) * GRID_SIZE
        if n["x"] != sx or n["y"] != sy:
            n["x"] = sx
            n["y"] = sy
            changed = True
    if changed:
        save_meta(board_id, meta)


def list_boards():
    return sorted(p.name for p in BOARDS_DIR.iterdir() if p.is_dir())


def rename_board(board_id: str, new_board_id: str):
    src = _board_dir(board_id)
    dst = _board_dir(new_board_id)
    assert src.exists()
    assert not dst.exists()
    src.rename(dst)


def delete_board(board_id: str):
    d = _board_dir(board_id)
    if d.exists():
        shutil.rmtree(d)


def load_meta(board_id: str):
    return json.loads(_meta_file(board_id).read_text())


def save_meta(board_id: str, meta):
    # atomic write so concurrent reads never see a half-written empty file
    p = _meta_file(board_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    tmp.replace(p)


def list_versions(board_id: str):
    d = _versions_dir(board_id)
    d.mkdir(exist_ok=True)
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def copy_data_tree(src_dir: Path, dst_dir: Path):
    # copy everything except the versions folder itself (no recursive snapshots)
    versions_dir = src_dir / "versions"
    for p in src_dir.iterdir():
        if p == versions_dir:
            continue
        if p.is_dir():
            shutil.copytree(p, dst_dir / p.name)
        else:
            shutil.copy2(p, dst_dir / p.name)


def save_version(board_id: str):
    d = _versions_dir(board_id)
    d.mkdir(exist_ok=True)
    nums = [int(n.split("_")[1]) for n in list_versions(board_id)]
    name = f"version_{max(nums) + 1 if nums else 0}"
    dst = d / name
    dst.mkdir()
    copy_data_tree(_board_dir(board_id), dst)
    return name


def delete_version(board_id: str, name: str):
    assert name in list_versions(board_id)
    shutil.rmtree(_versions_dir(board_id) / name)


def restore_version(board_id: str, name: str):
    assert name in list_versions(board_id)
    board_dir = _board_dir(board_id)
    versions_dir = _versions_dir(board_id)
    for p in board_dir.iterdir():
        if p == versions_dir:
            continue
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    copy_data_tree(versions_dir / name, board_dir)


def node_path(meta, node_id: str, board_id: str) -> Path:
    # data/<board>/<ancestor folder titles...>/<title>[.md]
    node = meta["nodes"][node_id]
    parts = [node["title"]]
    cur = node
    while True:
        if cur["parent"] is None:
            break
        cur = meta["nodes"][cur["parent"]]
        parts.append(cur["title"])
    parts.reverse()
    p = _board_dir(board_id).joinpath(*parts)
    return p.with_suffix(".md") if node["type"] == "file" else p


def create_on_disk(meta, node_id: str, board_id: str):
    p = node_path(meta, node_id, board_id)
    assert not p.exists()
    if meta["nodes"][node_id]["type"] == "folder":
        p.mkdir(parents=True)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")


def move_on_disk(old_path: Path, new_path: Path):
    assert old_path.exists()
    assert not new_path.exists()
    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_path), str(new_path))


def delete_on_disk(meta, node_id: str, board_id: str):
    p = node_path(meta, node_id, board_id)
    if meta["nodes"][node_id]["type"] == "folder":
        if p.exists():
            shutil.rmtree(p)
    else:
        if p.exists():
            p.unlink()
