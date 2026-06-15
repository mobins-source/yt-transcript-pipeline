"""
fetch_channel.py — retrieve video metadata for a YouTube channel.

Priority:
  1. YouTube Data API v3 (all videos, paginated, requires YOUTUBE_API_KEY)
  2. RSS feed (latest 15 only, no key needed)
  3. yt-dlp (fallback, may not work for all channels)

After the video list is fetched, _fetch_video_details() is called to enrich
each video with duration_seconds and actual_at (live stream start time) using
the videos?part=contentDetails,liveStreamingDetails endpoint — one API call
per 50 videos, so the whole channel costs just 1-2 extra quota units.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console

import config

console = Console()

_RSS_URL     = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_YT_API_BASE = "https://www.googleapis.com/youtube/v3"


@dataclass
class VideoMeta:
    video_id: str
    title: str
    channel_id: str
    channel_name: str
    upload_date: str       # YYYYMMDD
    published_at: str      # ISO datetime — upload/publish time from YouTube
    actual_at: str         # ISO datetime — actual live stream start time (or same as published_at for VODs)
    duration_seconds: int
    view_count: Optional[int]
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── ISO 8601 duration parser ──────────────────────────────────────────────────

def _parse_iso_duration(duration: str) -> int:
    """
    Convert ISO 8601 duration (e.g. PT1H23M45S) to total seconds.
    Returns 0 if unparseable.
    """
    if not duration:
        return 0
    pattern = re.compile(
        r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
    )
    m = pattern.match(duration)
    if not m:
        return 0
    days    = int(m.group(1) or 0)
    hours   = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = int(m.group(4) or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


# ── Video details enrichment (duration + actual_at) ──────────────────────────

def _fetch_video_details(videos: list[VideoMeta]) -> None:
    """
    Enrich a list of VideoMeta in-place with:
      - duration_seconds  (from contentDetails.duration)
      - actual_at         (from liveStreamingDetails.actualStartTime for live streams,
                           otherwise keeps published_at)

    Makes one API call per 50 videos (max batch size).
    Modifies the list in-place — no return value.
    """
    if not config.YOUTUBE_API_KEY or not videos:
        return

    # Build a lookup map for fast in-place update
    video_map = {v.video_id: v for v in videos}
    ids = list(video_map.keys())
    total_batches = (len(ids) + 49) // 50

    console.print(
        f"[cyan]Fetching video details[/cyan] "
        f"(duration + stream start time, {total_batches} batch(es))…"
    )

    for batch_num, i in enumerate(range(0, len(ids), 50), 1):
        batch = ids[i : i + 50]
        params = {
            "part": "contentDetails,liveStreamingDetails",
            "id":   ",".join(batch),
            "key":  config.YOUTUBE_API_KEY,
        }
        url = f"{_YT_API_BASE}/videos?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            console.print(f"[yellow]⚠ Video details batch {batch_num} failed: {exc}[/yellow]")
            continue

        for item in data.get("items", []):
            vid_id = item.get("id", "")
            if vid_id not in video_map:
                continue

            v = video_map[vid_id]

            # Duration
            content = item.get("contentDetails", {})
            raw_dur = content.get("duration", "")
            if raw_dur and raw_dur != "P0D":
                v.duration_seconds = _parse_iso_duration(raw_dur)

            # Actual start time for live streams
            live = item.get("liveStreamingDetails", {})
            actual_start = live.get("actualStartTime", "")
            if actual_start:
                v.actual_at = actual_start
            else:
                # Not a live stream — actual_at same as published_at
                v.actual_at = v.published_at

        console.print(
            f"  [dim]→ batch {batch_num}/{total_batches}: "
            f"{len(data.get('items', []))} videos enriched[/dim]"
        )


# ── Channel ID resolver ───────────────────────────────────────────────────────

def _resolve_channel_id(channel: str) -> str:
    """Resolve handle/@name/URL to UC… channel ID."""
    if re.match(r"^UC[\w-]{22}$", channel):
        return channel

    if config.YOUTUBE_API_KEY:
        handle = channel.lstrip("@")
        url = (f"{_YT_API_BASE}/channels?part=id"
               f"&forHandle={urllib.parse.quote(handle)}"
               f"&key={config.YOUTUBE_API_KEY}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            items = data.get("items", [])
            if items:
                return items[0]["id"]
        except Exception as exc:
            console.print(f"[yellow]⚠ API channel lookup failed: {exc}[/yellow]")

    handle = channel if channel.startswith("@") else f"@{channel}"
    url = f"https://www.youtube.com/{handle}"
    cmd = ["yt-dlp", "--flat-playlist", "--dump-single-json",
           "--no-warnings", "--quiet", "--playlist-end", "1", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout)
        return data.get("channel_id", "")
    except Exception:
        return ""


# ── YouTube Data API v3 playlist fetch ───────────────────────────────────────

def _fetch_api(channel_id: str, max_videos: int = 0) -> list[VideoMeta]:
    """Fetch ALL videos from a channel's uploads playlist."""
    if not config.YOUTUBE_API_KEY:
        return []

    playlist_id = "UU" + channel_id[2:]
    videos: list[VideoMeta] = []
    page_token = ""
    page = 1

    console.print(f"[cyan]Fetching via YouTube API (playlist {playlist_id})…[/cyan]")

    while True:
        params = {
            "part":       "snippet",
            "playlistId": playlist_id,
            "maxResults": "50",
            "key":        config.YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token

        url = f"{_YT_API_BASE}/playlistItems?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            console.print(f"[red]✗ YouTube API error on page {page}: {exc}[/red]")
            break

        items = data.get("items", [])
        console.print(f"  [dim]→ page {page}: {len(items)} videos[/dim]")

        for item in items:
            snippet      = item.get("snippet", {})
            res_id       = snippet.get("resourceId", {})
            vid_id       = res_id.get("videoId", "")
            if not vid_id:
                continue

            published_at = snippet.get("publishedAt", "")
            upload_date  = published_at[:10].replace("-", "") if published_at else ""

            videos.append(VideoMeta(
                video_id=vid_id,
                title=snippet.get("title", ""),
                channel_id=snippet.get("channelId", channel_id),
                channel_name=snippet.get("channelTitle", ""),
                upload_date=upload_date,
                published_at=published_at,
                actual_at="",           # filled by _fetch_video_details()
                duration_seconds=0,     # filled by _fetch_video_details()
                view_count=None,
                url=f"https://www.youtube.com/watch?v={vid_id}",
            ))

            if max_videos and len(videos) >= max_videos:
                break

        if max_videos and len(videos) >= max_videos:
            break

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
        page += 1

    console.print(f"  [dim]→ {len(videos)} total via YouTube API[/dim]")
    return videos


# ── RSS feed (fallback, 15 videos) ────────────────────────────────────────────

def _fetch_rss(channel_id: str) -> list[VideoMeta]:
    url = _RSS_URL.format(channel_id=channel_id)
    console.print(f"[cyan]Fetching RSS:[/cyan] {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_bytes = resp.read()
    except Exception as exc:
        console.print(f"[yellow]⚠ RSS fetch failed: {exc}[/yellow]")
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        console.print(f"[yellow]⚠ RSS parse error: {exc}[/yellow]")
        return []

    ns = {
        "atom":  "http://www.w3.org/2005/Atom",
        "yt":    "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    channel_name = ""
    name_el = root.find("atom:author/atom:name", ns)
    if name_el is not None:
        channel_name = name_el.text or ""

    videos: list[VideoMeta] = []
    for entry in root.findall("atom:entry", ns):
        vid_id_el = entry.find("yt:videoId", ns)
        title_el  = entry.find("atom:title", ns)
        date_el   = entry.find("atom:published", ns)

        vid_id       = vid_id_el.text if vid_id_el is not None else ""
        title        = title_el.text  if title_el  is not None else ""
        published_at = date_el.text   if date_el   is not None else ""
        upload_date  = published_at[:10].replace("-", "") if published_at else ""

        if not vid_id:
            continue

        videos.append(VideoMeta(
            video_id=vid_id,
            title=title,
            channel_id=channel_id,
            channel_name=channel_name,
            upload_date=upload_date,
            published_at=published_at,
            actual_at="",
            duration_seconds=0,
            view_count=None,
            url=f"https://www.youtube.com/watch?v={vid_id}",
        ))

    console.print(f"  [dim]→ {len(videos)} videos via RSS[/dim]")
    return videos


# ── yt-dlp (last resort) ──────────────────────────────────────────────────────

def _fetch_ytdlp_tab(url: str, max_videos: int = 0) -> list[dict]:
    cmd = ["yt-dlp", "--flat-playlist", "--dump-single-json",
           "--no-warnings", "--quiet", url]
    if max_videos > 0:
        cmd += ["--playlist-end", str(max_videos)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        return json.loads(r.stdout).get("entries") or []
    except Exception:
        return []


def _fetch_ytdlp(base_url: str, channel_id: str,
                 channel_name: str, max_videos: int) -> list[VideoMeta]:
    videos: list[VideoMeta] = []
    seen: set[str] = set()
    for tab in ("/videos", "/streams"):
        entries = _fetch_ytdlp_tab(base_url + tab, max_videos)
        console.print(f"  [dim]→ {len(entries)} entries via yt-dlp{tab}[/dim]")
        for e in entries:
            vid_id = e.get("id", "")
            if not vid_id or vid_id in seen:
                continue
            seen.add(vid_id)
            upload_date  = e.get("upload_date") or ""
            published_at = ""
            if len(upload_date) == 8:
                published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}T00:00:00+00:00"
            videos.append(VideoMeta(
                video_id=vid_id,
                title=e.get("title", ""),
                channel_id=channel_id or e.get("channel_id", ""),
                channel_name=channel_name or e.get("channel", ""),
                upload_date=upload_date,
                published_at=published_at,
                actual_at=published_at,   # yt-dlp flat playlist has no stream times
                duration_seconds=int(e.get("duration") or 0),
                view_count=e.get("view_count"),
                url=f"https://www.youtube.com/watch?v={vid_id}",
            ))
    return videos


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_channel_videos(channel: str, max_videos: int = 0) -> list[VideoMeta]:
    """
    Fetch all video metadata for a channel, including duration and actual
    stream start time.

    Steps:
      1. Fetch video list (YouTube API → RSS → yt-dlp)
      2. Enrich with duration_seconds + actual_at via videos API (batch of 50)
    """
    channel_id = _resolve_channel_id(channel)
    if not channel_id:
        console.print(f"[yellow]⚠ Could not resolve channel ID for {channel}[/yellow]")

    # Base URL for yt-dlp fallback
    if channel.startswith("http"):
        base_url = channel.rstrip("/")
        for tab in ("/videos", "/streams", "/shorts"):
            base_url = base_url.removesuffix(tab)
    elif re.match(r"^UC[\w-]{22}$", channel):
        base_url = f"https://www.youtube.com/channel/{channel}"
    else:
        handle = channel if channel.startswith("@") else f"@{channel}"
        base_url = f"https://www.youtube.com/{handle}"

    videos: list[VideoMeta] = []

    # 1. Fetch video list
    if channel_id and config.YOUTUBE_API_KEY:
        videos = _fetch_api(channel_id, max_videos)

    if not videos and channel_id:
        videos = _fetch_rss(channel_id)

    channel_name = videos[0].channel_name if videos else channel

    rss_count = len(videos)
    need_more = not config.YOUTUBE_API_KEY and (
        (max_videos == 0 and rss_count >= 15) or
        (max_videos > 0  and rss_count < max_videos)
    )
    if need_more:
        console.print(f"[cyan]Trying yt-dlp for full history…[/cyan]")
        yt_videos = _fetch_ytdlp(base_url, channel_id, channel_name, max_videos)
        if yt_videos:
            seen = {v.video_id for v in yt_videos}
            extras = [v for v in videos if v.video_id not in seen]
            videos = yt_videos + extras

    if max_videos > 0:
        videos = videos[:max_videos]

    # 2. Enrich with duration + actual stream start time (single batch API call)
    if config.YOUTUBE_API_KEY and videos:
        _fetch_video_details(videos)

    console.print(
        f"[green]✓[/green] Found [bold]{len(videos)}[/bold] videos "
        f"for [bold]{channel}[/bold]"
    )
    return videos
