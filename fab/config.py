'''fab-wide config. everything fab writes lives under FAB_DIR (~/.fab), one subdir per module.'''

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # repo-root .env -> os.environ (MOONSHOT_API_KEY etc.)

FAB_DIR = Path.home() / ".fab"

PRESERVE_LAST = 3        # messages kept verbatim after compression
API_TIMEOUT = 180        # seconds per provider request
