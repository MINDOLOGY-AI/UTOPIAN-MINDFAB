'''wiresend config: paths and caps. see DOC.md.'''

from fab.config import FAB_DIR

WS_DIR = FAB_DIR / "wiresend"           # ~/.fab/wiresend — channels.json, readers.json, {channel}/
MAX_FILE_BYTES = 100 * 1024**3          # dataset uploads over HTTP
