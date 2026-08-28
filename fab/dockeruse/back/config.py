'''dockeruse config: paths, ports, names. see DOC.md.'''

import re
from pathlib import Path

from fab.config import udir

PROJECT_ROOT = Path.cwd()

# every per-user dockeruse path: ~/.fab/users/{user}/dockeruse/...
def du_dir(user: str):
    return udir(user) / "dockeruse"

BASE_PORT = 6080                        # first novnc port; increments per container (host-wide, all users)
EXEC_TIMEOUT = 30                       # foreground EXEC limit in seconds, then demote to background

# names become docker container names and folder paths — docker's own rule:
# starts with a letter or digit, then letters/digits/_.-, at least 2 chars
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}$")
