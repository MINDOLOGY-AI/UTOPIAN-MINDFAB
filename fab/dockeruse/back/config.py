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


# a container's workspace on the host — the same tree the container sees as /home/agent
def workspace_dir(user: str, name: str) -> Path:
    return du_dir(user) / "workspace" / name


# resolve a file the agent named against its workspace. shared by the dockeruse file tools
# and wiresend's upload/download, which move bytes through the same tree
def workspace_path(workspace: Path, file: str) -> Path:
    # the agent sees its workspace as /home/agent inside the container — accept
    # those absolute paths too instead of rejecting them as escapes
    if file == "/home/agent":
        file = "."
    elif file.startswith("/home/agent/"):
        file = file[len("/home/agent/"):]
    path = (workspace / file).resolve()
    # cybersec: confine to the container's own workspace — without this the LLM (or a prompt
    # injection) could read/write any file on the host, e.g. ../../.env
    if not path.is_relative_to(workspace.resolve()):
        raise ValueError(f"path escapes workspace: {file}")
    return path
