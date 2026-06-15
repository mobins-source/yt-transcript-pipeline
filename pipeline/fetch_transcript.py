"""
fetch_transcript.py — download transcript/captions for a YouTube video.
Compatible with youtube-transcript-api v1.x

Cookie support (bypasses IP blocks):
  Set COOKIES_FILE in .env to a Netscape cookies.txt exported from your browser.
  Cookies injected via http_client=requests.Session() — works with v1.x.

  Refresh cookies when IP blocks reappear (every ~2 months):
    yt-dlp --cookies-from-browser safari --cookies ../data/cookies.txt "https://www.youtube.com"
  Or export from Chrome using the "Get cookies.txt LOCALLY" extension.

Retry strategy with cookies active:
  If cookies are fresh → IP blocks should not happen at all.
  If cookies expired  → IP block on first request → 1 internal retry → raise immediately.
  This fails fast (360s max) instead of wasting 39 minutes per video.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Optional

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from rich.console import Console

import config

console = Console()

_MAX_RETRIES      = 3
_BASE_DELAY       = 5.0
_IP_BLOCK_PAUSE   = 60.0   # reduced from 180s — cookies should fix IP blocks; if not, fail fast
_IP_BLOCK_RETRIES = 1      # reduced from 2 — one retry, then raise to batch handler


def _make_api() -> YouTubeTranscriptApi:
    """Create API instance with optional cookie auth."""
    cookies_path = getattr(config, "COOKIES_FILE", "").strip()

    if not cookies_path or not Path(cookies_path).exists():
        return YouTubeTranscriptApi()

    try:
        jar = MozillaCookieJar(cookies_path)
        jar.load(ignore_discard=True, ignore_expires=True)
        session = requests.Session()
        session.cookies.update(jar)
        api = YouTubeTranscriptApi(http_client=session)
        console.print("[green]✓ Cookies loaded — IP blocks bypassed[/green]")
        return api
    except Exception as e:
        console.print(f"[yellow]⚠ Could not load cookies ({e}) — running without[/yellow]")
        return YouTubeTranscriptApi()


_api = _make_api()


@dataclass
class TranscriptSegment:
    text: str
    start: float
    duration: float


@dataclass
class Transcript:
    video_id: str
    language: str
    is_generated: bool
    segments: list[TranscriptSegment] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["full_text"] = self.full_text
        return d


def _is_ip_blocked(exc: Exception) -> bool:
    msg  = str(exc)
    name = type(exc).__name__
    return (
        "IPBlocked"      in name or
        "RequestBlocked" in name or
        "blocking requests from your IP" in msg or
        "your IP has been blocked"       in msg
    )


def _is_permanent(exc: Exception) -> bool:
    msg  = str(exc).lower()
    name = type(exc).__name__
    return (
        any(w in name for w in ("TranscriptsDisabled", "VideoUnavailable", "NotTranslatable")) or
        any(w in msg  for w in ("disabled", "unavailable", "private", "no transcript",
                                "live event will begin"))
    )


def _call_with_retry(fn, *args, **kwargs):
    delay       = _BASE_DELAY
    ip_attempts = 0

    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if _is_permanent(exc):
                raise
            if _is_ip_blocked(exc):
                ip_attempts += 1
                if ip_attempts > _IP_BLOCK_RETRIES:
                    raise   # give up quickly — cookies should prevent this
                console.print(
                    f"[yellow]⚠ IP blocked — pausing {_IP_BLOCK_PAUSE:.0f}s "
                    f"({ip_attempts}/{_IP_BLOCK_RETRIES})…[/yellow]"
                )
                time.sleep(_IP_BLOCK_PAUSE)
                continue
            if attempt < _MAX_RETRIES - 1:
                console.print(f"[yellow]⚠ Transient error, waiting {delay:.0f}s…[/yellow]")
                time.sleep(delay)
                delay *= 2
            else:
                raise

    raise RuntimeError("Max retries exceeded")


def fetch_transcript(video_id: str, preferred_lang: str = "en") -> Optional[Transcript]:
    try:
        transcript_list = _call_with_retry(_api.list, video_id)
    except Exception as exc:
        if _is_permanent(exc):
            console.print(f"[yellow]⚠ No transcript for {video_id}: {type(exc).__name__}[/yellow]")
            return None
        raise

    available = [(t.language_code, t.is_generated, t) for t in transcript_list]
    if not available:
        return None

    chosen = None
    for lang, generated, t in available:
        if not generated and lang == preferred_lang:
            chosen = (t, False); break
    if not chosen:
        for lang, generated, t in available:
            if not generated:
                chosen = (t, False); break
    if not chosen:
        for lang, generated, t in available:
            if generated and lang == preferred_lang:
                chosen = (t, True); break
    if not chosen:
        _, _, t = available[0]
        chosen = (t, True)

    transcript_obj, is_generated = chosen

    try:
        raw = _call_with_retry(transcript_obj.fetch)
    except Exception as exc:
        if _is_permanent(exc):
            return None
        raise

    return Transcript(
        video_id=video_id,
        language=transcript_obj.language_code,
        is_generated=is_generated,
        segments=[
            TranscriptSegment(text=item.text, start=item.start, duration=item.duration)
            for item in raw
        ],
    )
