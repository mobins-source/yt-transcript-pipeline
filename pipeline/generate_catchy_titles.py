"""
generate_catchy_titles.py — Lightweight backfill for the catchy_title field.

This is intentionally NOT a re-enrichment pass. It does NOT touch summary,
content_type, hadith_book, hadith_chapter, topic_tags, or suggested_title.

It only reads data that ALREADY EXISTS on disk:
  - summary           (from prior enrichment)
  - suggested_title    (for context)
  - a short excerpt of the clean transcript (.clean_en.txt, or clean_text fallback)

...and writes back a single new field: catchy_title.

Why this is cheap:
  - No full-transcript pass through Claude (enrich.py sends up to 3000 words;
    this script sends summary + ~600 chars, roughly 5-10% of the token cost)
  - max_tokens=100 since a title is short
  - Skips any video that hasn't been enriched yet (no summary = no catchy_title)
  - Skips any video that already has a catchy_title, unless --force

JSON parsing robustness (fixed June 2026):
  Small models occasionally add a preamble before the JSON ("I'll create a
  title...") or trailing commentary after it, even when told not to. Two
  defenses are used here:
    1. Assistant-prefill: we seed the assistant turn with "{" so the model
       continues directly into the JSON object instead of writing a sentence
       first. This eliminates the "Expecting value: line 1 column 1" failure.
    2. Regex extraction: after getting the response, we search for the first
       {...} block rather than assuming the entire string is valid JSON. This
       eliminates the "Extra data" failure caused by trailing commentary or
       a truncated sentence after the closing brace.

Usage:
  python3 generate_catchy_titles.py                  # backfill missing catchy_titles
  python3 generate_catchy_titles.py --force           # regenerate ALL catchy_titles
  python3 generate_catchy_titles.py --limit 10        # test on first 10 only
  python3 generate_catchy_titles.py --channel UCxxxxx # restrict to one channel
"""
from __future__ import annotations

import json
import re
import time

import anthropic
import click
from rich.console import Console

import config
import store
from enrich import _rebuild_index

console = Console()

_MODEL      = "claude-haiku-4-5-20251001"
_MAX_CHARS  = 600   # transcript excerpt length — kept small, this is a lightweight call

_SYSTEM_PROMPT = """You write short, catchy YouTube titles for clips from Islamic lectures \
(Muslim Community Center of Tucson). You will be given an existing descriptive title, \
a summary, and a short transcript excerpt — use these to write ONE alternative title.

Style:
- Under 8 words
- Hook-style: a question, a surprising image/moment from the content, or direct address
- Must accurately represent the lecture — no clickbait that misleads
- Respectful tone appropriate for Islamic religious content
- No quotation marks inside the title itself

Respond with ONLY the JSON object below. No preamble, no explanation, no text
before or after it — your entire response must be exactly this one line:
{"catchy_title": "..."}"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _transcript_excerpt(channel_id: str, video_id: str, tx: dict) -> str:
    """Pull a short excerpt from the clean transcript file, falling back to clean_text."""
    text = store.load_clean_txt(channel_id, video_id) or tx.get("clean_text", "") or ""
    return text[:_MAX_CHARS]


def _extract_title(raw: str) -> tuple[str | None, str | None]:
    """
    Extract catchy_title from a model response that may have leading/trailing
    noise around the JSON object. Returns (title, error_reason).
    """
    raw = raw.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        return None, "no JSON object found in response"

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return None, f"malformed JSON — {exc}"

    title = (data.get("catchy_title") or "").strip().strip('"')
    if not title:
        return None, "JSON parsed but catchy_title was empty"
    return title, None


def _generate_one(video_id: str, channel_id: str, tx: dict, api_key: str) -> str | None:
    summary   = tx.get("summary", "") or ""
    suggested = tx.get("suggested_title", "") or ""
    excerpt   = _transcript_excerpt(channel_id, video_id, tx)

    if not summary and not excerpt:
        return None  # nothing to work with

    user_msg = (
        f"Existing descriptive title: {suggested}\n\n"
        f"Summary:\n{summary}\n\n"
        f"Transcript excerpt:\n{excerpt}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=_MODEL, max_tokens=100, system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": '{"catchy_title": "'},  # prefill — forces pure JSON, no preamble
            ],
        )
        # The API returns only the NEW tokens generated after our prefill,
        # so we must prepend it back before parsing.
        raw = '{"catchy_title": "' + response.content[0].text
        title, error = _extract_title(raw)
        if error:
            console.print(f"[red]✗ {video_id}: {error}[/red]")
            return None
        return title
    except Exception as exc:
        console.print(f"[red]✗ {video_id}: {exc}[/red]")
        return None


def _should_generate(tx: dict, force: bool) -> bool:
    if "summary" not in tx:
        return False  # not enriched yet — out of scope for this script, by design
    if force:
        return True
    return not tx.get("catchy_title")


def run(channel_filter: str | None = None, force: bool = False, limit: int | None = None) -> None:
    if not config.ANTHROPIC_API_KEY:
        console.print("[red]✗ ANTHROPIC_API_KEY not set in .env[/red]")
        return

    channel_ids = [channel_filter] if channel_filter else store.list_all_channel_ids()
    generated = skipped = not_enriched = failed = 0

    for channel_id in channel_ids:
        metas = store.load_channel_metadata(channel_id)
        console.print(f"[dim]Channel {channel_id}: {len(metas)} videos[/dim]")

        for meta in metas:
            if limit is not None and generated >= limit:
                break

            video_id = meta["video_id"]
            tx = store.load_transcript(channel_id, video_id)
            if tx is None:
                continue

            if "summary" not in tx:
                not_enriched += 1
                continue

            if not _should_generate(tx, force):
                skipped += 1
                continue

            title = _generate_one(video_id, channel_id, tx, config.ANTHROPIC_API_KEY)
            if title:
                tx["catchy_title"] = title
                store.save_transcript(channel_id, tx)
                console.print(f"  [green]✓[/green] {video_id}: [cyan]{title}[/cyan]")
                generated += 1
                time.sleep(0.3)   # light delay — this is a cheap call, not the heavy enrichment pass
            else:
                failed += 1
                console.print(f"  [yellow]⚠[/yellow] {video_id}: could not generate — will retry next run")

        if limit is not None and generated >= limit:
            break

    _rebuild_index()
    console.print(
        f"\n[bold green]✓ Generated {generated} catchy title(s)[/bold green]  "
        f"[yellow]{skipped} already had one[/yellow]  "
        f"[red]{failed} failed[/red]  "
        f"[dim]{not_enriched} not yet enriched (skipped by design)[/dim]"
    )


@click.command()
@click.option("--channel", default=None, help="Restrict to a single channel_id")
@click.option("--force", is_flag=True, default=False, help="Regenerate even if catchy_title already exists")
@click.option("--limit", default=None, type=int, help="Only process the first N videos (for testing)")
def main(channel, force, limit):
    """Backfill catchy_title for already-enriched videos, without re-enriching them."""
    run(channel_filter=channel, force=force, limit=limit)


if __name__ == "__main__":
    main()
