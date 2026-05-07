"""Project configuration. Edit here to point at a different property."""
import os
from pathlib import Path

# --- Target -----------------------------------------------------------------

PROPERTY_NAME = "Aberdeen Crossing"
PROPERTY_URL  = "https://www.aberdeencrossingapts.com/floorplans"

# --- Paths ------------------------------------------------------------------

PROJECT_ROOT  = Path(__file__).resolve().parent.parent
DATA_DIR      = PROJECT_ROOT / "data"
RAW_DIR       = DATA_DIR / "raw"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
DB_PATH       = DATA_DIR / "tracker.db"

# Ensure runtime directories exist.
RAW_DIR.mkdir(parents=True, exist_ok=True)
DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

# --- HTTP -------------------------------------------------------------------

# Real-browser User-Agent. Bumping this is the first remediation if fetches
# start returning 403. See .claude/skills/scraper-recovery/SKILL.md.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


# --- .env loader ------------------------------------------------------------
# Tiny dependency-free loader. Reads PROJECT_ROOT/.env if present and
# populates os.environ with any KEY=VALUE pairs that aren't already set.
# Keep this last so paths above are defined before we read.

def _load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file()
