'''thoughtgraph config: paths, layout constants, default types. see doc.md.'''

from fab.config import udir


# every per-user thoughtgraph path: ~/.fab/users/{user}/thoughtgraph/...
def tg_dir(user: str):
    return udir(user) / "thoughtgraph"

GRID_SIZE = 200                     # root snap + layout cell
EXPANDED_W, EXPANDED_H = 560, 360   # default expanded doc size
MAX_TITLE_CHARS = 120
MAX_CONTENT_CHARS = 100_000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# color families: purple = knowledge, blue = science loop, red = directives, orange = world/self
_PURPLE = "#B8A0FF"
_BLUE = "#6BC4FF"
_ORANGE = "#FF8C00"
_RED = "#FF0055"

DEFAULT_DOC_TYPES = {
    "axiom": {"color": _PURPLE},
    "definition": {"color": _PURPLE},
    "theory": {"color": _PURPLE},
    "doc": {"color": _PURPLE},  # generic — also the backend's default node_type
    "hypothesis": {"color": _BLUE},
    "experiment": {"color": _BLUE},
    "evidence": {"color": _BLUE},
    "task": {"color": _RED},
    "guideline": {"color": _RED},
    "actuator": {"color": _ORANGE},
    "world_state": {"color": _ORANGE},
    "aesthetics": {"color": _ORANGE},
    "personal": {"color": _ORANGE},
}

DEFAULT_EDGE_TYPES = {
    "support": {"color": "#00FF41"},
    "reject": {"color": "#FF0055"},
    "causes": {"color": "#6BC4FF"},
    "training": {"color": "#FF8C00"},
}
