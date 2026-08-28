'''thoughtgraph config: paths, layout constants, default types. see doc.md.'''

from fab.config import FAB_DIR

TG_DIR = FAB_DIR / "thoughtgraph"   # ~/.fab/thoughtgraph — boards, types.json, access.json

GRID_SIZE = 200                     # root snap + layout cell
EXPANDED_W, EXPANDED_H = 560, 360   # default expanded doc size
MAX_TITLE_CHARS = 120
MAX_CONTENT_CHARS = 100_000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# color families: purple = knowledge docs, blue = repo artifacts, orange = world
_PURPLE = "#B8A0FF"
_BLUE = "#6BC4FF"
_ORANGE = "#FF8C00"

DEFAULT_DOC_TYPES = {
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
}

DEFAULT_EDGE_TYPES = {
    "support": {"color": "#00FF41"},
    "reject": {"color": "#FF0055"},
    "causes": {"color": "#6BC4FF"},
    "training": {"color": "#FF8C00"},
}
