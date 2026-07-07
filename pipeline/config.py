"""
config.py — centralised settings loaded from .env
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Channels ─────────────────────────────────────────────────────────────────
RAW_CHANNELS = os.getenv("YOUTUBE_CHANNELS", "")
CHANNELS: list[str] = [c.strip() for c in RAW_CHANNELS.split(",") if c.strip()]

# ── Playlists (fetch specific playlist IDs instead of full channel uploads) ───
# Comma-separated list of YouTube playlist IDs (e.g. PLxxx,PLyyy)
# Each playlist is fetched independently and stored under its channel's folder.
RAW_PLAYLISTS = os.getenv("YOUTUBE_PLAYLISTS", "")
PLAYLISTS: list[str] = [p.strip() for p in RAW_PLAYLISTS.split(",") if p.strip()]

# ── Transcript preferences ────────────────────────────────────────────────────
TRANSCRIPT_LANG: str = os.getenv("TRANSCRIPT_LANG", "en")

# ── Limits ────────────────────────────────────────────────────────────────────
MAX_VIDEOS_PER_CHANNEL: int = int(os.getenv("MAX_VIDEOS_PER_CHANNEL", "0"))

# ── Batch strategy ────────────────────────────────────────────────────────────
BATCH_SIZE:  int   = int(os.getenv("BATCH_SIZE",  "10"))
BATCH_PAUSE: float = float(os.getenv("BATCH_PAUSE", "180"))

# ── Auth ──────────────────────────────────────────────────────────────────────
COOKIE_BROWSER:    str = os.getenv("COOKIE_BROWSER", "")
COOKIES_FILE:      str = os.getenv("COOKIES_FILE", "")   # path to Netscape cookies.txt
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY:   str = os.getenv("YOUTUBE_API_KEY", "")

# ── Paths ─────────────────────────────────────────────────────────────────────
_pipeline_dir = Path(__file__).parent
DATA_DIR: Path        = (_pipeline_dir / os.getenv("DATA_DIR", "../data")).resolve()
TRANSCRIPTS_DIR: Path = DATA_DIR / "transcripts"
METADATA_DIR: Path    = DATA_DIR / "metadata"
BACKUPS_DIR: Path     = DATA_DIR / "backups"

for _d in (TRANSCRIPTS_DIR, METADATA_DIR, BACKUPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
