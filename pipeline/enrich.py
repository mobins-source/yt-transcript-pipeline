"""
enrich.py — Add time metadata and AI-generated fields to stored transcripts.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta

import anthropic
from rich.console import Console

import config
import store

console = Console()

_PHOENIX_TZ = timezone(timedelta(hours=-7))
_MODEL = "claude-haiku-4-5-20251001"


def _time_of_day(hour: int) -> str:
    if 4 <= hour < 12:
        return "Fajr"
    if 12 <= hour < 17:
        return "Zuhr"
    return "Isha"


def _time_slot(day: str, tod: str) -> str:
    if day == "Friday" and tod == "Zuhr":
        return "Jumaa Khutba"
    return f"{day}-{tod}" if day and tod else ""


def compute_time_fields(actual_at: str, published_at: str = "") -> dict:
    iso_str = actual_at or published_at
    if not iso_str:
        return {}
    try:
        iso      = iso_str.replace("Z", "+00:00")
        dt_utc   = datetime.fromisoformat(iso)
        dt_local = dt_utc.astimezone(_PHOENIX_TZ)
        hour     = dt_local.hour
        tod      = _time_of_day(hour)
        day      = dt_local.strftime("%A")
        return {
            "actual_at":   actual_at or published_at,
            "post_time":   dt_local.strftime("%Y-%m-%dT%H:%M:%S"),
            "post_date":   dt_local.strftime("%Y-%m-%d"),
            "month":       dt_local.strftime("%B"),
            "month_num":   dt_local.month,
            "year":        dt_local.year,
            "month_year":  dt_local.strftime("%B %Y"),
            "time_of_day": tod,
            "day_of_week": day,
            "time_slot":   _time_slot(day, tod),
        }
    except Exception as exc:
        console.print(f"[yellow]⚠ Could not parse timestamp '{iso_str}': {exc}[/yellow]")
        return {}


_SYSTEM_PROMPT = """You are an Islamic content analyst. You will be given a YouTube video title and transcript from an Islamic center (Muslim Community Center of Tucson).

Analyze the content and return ONLY a valid JSON object with these exact fields:
{
  "summary": "2-3 paragraph summary of the content",
  "suggested_title": "A clear descriptive title based on the actual content",
  "content_type": "one of: Quran, Hadith, General, Announcement, Mixed",
  "hadith_book": "name of the specific hadith book discussed, or null if not applicable. Must be one of: Sahih Bukhari, Sahih Muslim, Sunan Abu Dawud, Jami al-Tirmidhi, Sunan al-Nasai, Sunan Ibn Majah, Riyadul Saliheen, Al-Wajeez, Other, or null",
  "hadith_chapter": "the specific chapter, section or book number discussed within the hadith collection, or null if not applicable",
  "topic_tags": ["array", "of", "relevant", "topic", "tags", "max 8 tags"]
}

Rules:
- Return ONLY the JSON object, no preamble, no markdown, no backticks
- topic_tags should be lowercase, concise, and relevant
- If the transcript is empty or too short to analyze, use "General" for content_type
- hadith_book must be null if no specific book is discussed"""


def enrich_with_ai(video_id: str, title: str, transcript_text: str, api_key: str) -> dict:
    client   = anthropic.Anthropic(api_key=api_key)
    words    = transcript_text.split()
    excerpt  = " ".join(words[:3000]) + ("… [truncated]" if len(words) > 3000 else "")
    user_msg = f"Video title: {title}\n\nTranscript:\n{excerpt}"
    try:
        response = client.messages.create(
            model=_MODEL, max_tokens=1000, system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        console.print(f"[red]✗ AI response not valid JSON for {video_id}: {exc}[/red]")
        return {}
    except Exception as exc:
        console.print(f"[red]✗ AI enrichment failed for {video_id}: {exc}[/red]")
        return {}


def enrich_transcript(channel_id: str, video_meta: dict, force: bool = False) -> bool:
    video_id = video_meta["video_id"]
    tx = store.load_transcript(channel_id, video_id)
    if tx is None:
        return False
    already_enriched = "summary" in tx and "time_of_day" in tx and "actual_at" in tx
    if already_enriched and not force:
        return False
    time_fields = compute_time_fields(
        actual_at    = video_meta.get("actual_at", ""),
        published_at = video_meta.get("published_at", ""),
    )
    tx.update(time_fields)
    if config.ANTHROPIC_API_KEY:
        tx.update(enrich_with_ai(
            video_id        = video_id,
            title           = video_meta.get("title", ""),
            transcript_text = tx.get("clean_text", ""),
            api_key         = config.ANTHROPIC_API_KEY,
        ))
    else:
        console.print("[yellow]⚠ ANTHROPIC_API_KEY not set — skipping AI enrichment[/yellow]")
    store.save_transcript(channel_id, tx)
    return True


def enrich_channel(channel_id: str, force: bool = False) -> tuple[int, int]:
    if not config.ANTHROPIC_API_KEY:
        console.print("[red]✗ ANTHROPIC_API_KEY not set in .env — cannot enrich[/red]")
        return 0, 0
    metas = store.load_channel_metadata(channel_id)
    if not metas:
        return 0, 0
    enriched = skipped = 0
    for meta in metas:
        vid_id = meta["video_id"]
        if not store.transcript_exists(channel_id, vid_id):
            skipped += 1
            continue
        console.print(f"  [dim]Enriching {vid_id}: {meta.get('title','')[:60]}[/dim]")
        ok = enrich_transcript(channel_id, meta, force=force)
        if ok:
            enriched += 1
            time.sleep(0.5)
        else:
            skipped += 1
    return enriched, skipped


def enrich_all_channels(force: bool = False) -> None:
    if not config.METADATA_DIR.exists():
        return
    for ch_dir in config.METADATA_DIR.iterdir():
        if not ch_dir.is_dir():
            continue
        channel_id = ch_dir.name
        console.rule(f"[bold blue]Enriching: {channel_id}[/bold blue]")
        enriched, skipped = enrich_channel(channel_id, force=force)
        console.print(
            f"[green]✓[/green] {channel_id} — "
            f"[green]{enriched} enriched[/green], [yellow]{skipped} skipped[/yellow]"
        )
    _rebuild_index()


def _rebuild_index() -> None:
    index_videos = []
    if not config.METADATA_DIR.exists():
        return
    for ch_dir in config.METADATA_DIR.iterdir():
        if not ch_dir.is_dir():
            continue
        metas = store.load_channel_metadata(ch_dir.name)
        for meta in metas:
            vid_id = meta["video_id"]
            meta["has_transcript"] = store.transcript_exists(ch_dir.name, vid_id)
            meta["has_clean_srt"]  = store.srt_exists(ch_dir.name, vid_id)
            meta["has_clean_txt"]  = store.clean_txt_exists(ch_dir.name, vid_id)
            tx = store.load_transcript(ch_dir.name, vid_id)
            if tx:
                for f in (
                    "actual_at", "time_of_day", "day_of_week", "time_slot",
                    "post_time", "post_date", "month", "month_num", "year", "month_year",
                    "content_type", "hadith_book", "hadith_chapter",
                    "topic_tags", "suggested_title", "summary", "srt_status",
                ):
                    if f in tx:
                        meta[f] = tx[f]
            index_videos.append(meta)

    store._write_json(store._index_path(), {
        "videos":     index_videos,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    console.print(f"[dim]Index rebuilt with {len(index_videos)} videos[/dim]")
