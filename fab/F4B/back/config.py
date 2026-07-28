from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "fab" / "data" / "F4B"

# per-user layout: DATA_DIR / {username} / {types.json, templates.json, {board}/}
# per-board layout: {board}/{meta.json, content/{node_id}.md, versions/}

GRID_SIZE = 200

# color families: purple = knowledge docs, blue = links to repo artifacts,
# orange = world, red = prompt, green = agent
_PURPLE = "#B8A0FF"
_BLUE = "#6BC4FF"
_ORANGE = "#FF8C00"

DEFAULT_OBJ_TYPES = {
    "axiom": {"color": _PURPLE},
    "definition": {"color": _PURPLE},
    "theory": {"color": _PURPLE},
    "evidence": {"color": _PURPLE},
    "hypothesis": {"color": _PURPLE},
    "doc": {"color": _PURPLE},
    "algorithm": {"color": _BLUE},
    "weights": {"color": _BLUE},
    "dataset": {"color": _BLUE},
    "benchmark": {"color": _BLUE},
    "code": {"color": _BLUE},
    "model": {"color": _BLUE},
    "actuator": {"color": _ORANGE},
    "world_state": {"color": _ORANGE},
    "aesthetics": {"color": _ORANGE},
    "prompt": {"color": "#FF0055"},
    "agent": {"color": "#00FF41"},
}

DEFAULT_FUNC_TYPES = {
    "support": {"color": "#00FF41"},
    "reject": {"color": "#FF0055"},
    "inference": {"color": "#6BC4FF"},
    "training": {"color": "#FF8C00"},
}

DEFAULT_STATE_COLORS = {
    "todo": "#94A3B8",
    "doing": "#00FF41",
    "done": "#475569",
}
