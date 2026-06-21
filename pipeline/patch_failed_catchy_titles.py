"""
patch_failed_catchy_titles.py — Retry catchy_title generation for specific
videos that failed in a previous generate_catchy_titles.py run.

This is a thin wrapper around generate_catchy_titles.py's logic — it does
NOT re-enrich anything, only retries the catchy_title call for the exact
video_ids you give it (or the default failed list below).

Usage:
  python3 patch_failed_catchy_titles.py
      → retries the default FAILED_VIDEO_IDS list below

  python3 patch_failed_catchy_titles.py --video-ids FqlPTp-aIPg,w8vVtFyr8lk
      → retries only the video_ids you specify (comma separated)
"""
from __future__ import annotations

import click
from rich.console import Console

import config
import store
from enrich import _rebuild_index
from generate_catchy_titles import _generate_one

console = Console()

# Videos that failed with JSON parsing errors before the prefill/regex fix.
# Update this list any time you want to re-patch a different set of videos.
FAILED_VIDEO_IDS = [
    "FqlPTp-aIPg",
    "w8vVtFyr8lk",
    "b8d1sP-3wb0",
]


def _find_channel_for_video(video_id: str) -> str | None:
    """Search all channels for the one that owns this video_id."""
    for channel_id in store.list_all_channel_ids():
        if store.transcript_exists(channel_id, video_id):
            return channel_id
    return None


def run(video_ids: list[str]) -> None:
    if not config.ANTHROPIC_API_KEY:
        console.print("[red]✗ ANTHROPIC_API_KEY not set in .env[/red]")
        return

    console.print(f"[bold]Patching {len(video_ids)} video(s)…[/bold]\n")

    fixed = still_failed = not_found = 0

    for video_id in video_ids:
        channel_id = _find_channel_for_video(video_id)
        if channel_id is None:
            console.print(f"[red]✗ {video_id}: not found in any channel[/red]")
            not_found += 1
            continue

        tx = store.load_transcript(channel_id, video_id)
        if tx is None:
            console.print(f"[red]✗ {video_id}: transcript file missing[/red]")
            not_found += 1
            continue

        if "summary" not in tx:
            console.print(f"[yellow]⚠ {video_id}: not enriched yet — skipping (out of scope)[/yellow]")
            continue

        title = _generate_one(video_id, channel_id, tx, config.ANTHROPIC_API_KEY)
        if title:
            tx["catchy_title"] = title
            store.save_transcript(channel_id, tx)
            console.print(f"  [green]✓[/green] {video_id}: [cyan]{title}[/cyan]")
            fixed += 1
        else:
            console.print(f"  [red]✗[/red] {video_id}: still failed — try again later")
            still_failed += 1

    _rebuild_index()
    console.print(
        f"\n[bold green]✓ Fixed {fixed}[/bold green]  "
        f"[red]{still_failed} still failed[/red]  "
        f"[yellow]{not_found} not found[/yellow]"
    )


@click.command()
@click.option(
    "--video-ids", default=None,
    help="Comma-separated video_ids to retry. Defaults to the known failed list."
)
def main(video_ids):
    ids = [v.strip() for v in video_ids.split(",")] if video_ids else FAILED_VIDEO_IDS
    run(ids)


if __name__ == "__main__":
    main()
