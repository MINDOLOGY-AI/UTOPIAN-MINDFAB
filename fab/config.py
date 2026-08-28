'''fab-wide config. fab writes to FAB_DIR (~/.fab): auth/ and logs/ at the root,
everything user-owned under users/{user}/{module}/ — udir(user) is the one path helper.'''

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # repo-root .env -> os.environ (MOONSHOT_API_KEY etc.)

FAB_DIR = Path.home() / ".fab"


# every per-user path goes through here: ~/.fab/users/{user}/...
def udir(user: str) -> Path:
    return FAB_DIR / "users" / user

PRESERVE_LAST = 3        # messages kept verbatim after compression
API_TIMEOUT = 180        # seconds per provider request
