"""
run.py — CLI entry point for the YouTube transcript pipeline.
"""
from __future__ import annotations

import sys
import time

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

import config
import store
from fetch_channel import fetch_channel_videos, fetch_playlist_videos
from fetch_transcript import fetch_transcript, _is_ip_blocked
from process import process_transcript
from enrich import enrich_transcript, enrich_all_channels, _rebuild_index
from clean_captions import clean_captions_all_channels, generate_clean_captions, already_cleaned

console = Console()

# Rate limiting constants
# Cookies help bypass IP bans but YouTube still has per-session rate limits.
# 10s between requests + 5min between batches = ~50 videos/hour max sustainable rate.
_REQUEST_DELAY                  = 10.0   # seconds between individual requests (was 5s)
_IP_BLOCK_PAUSE                 = 120.0  # pause before retrying a blocked video
_MAX_IP_BLOCK_RETRIES_PER_VIDEO = 1      # give up after 1 retry — don't waste time

# ── Backfill mode constants ─────────────────────────────────────────
# Lesson learned (July 2026): a full backfill (~70 transcript requests in one
# session) tripped YouTube's volume-based rate limiter on a residential IP,
# and every request after ~request 65 was blocked. Backfill mode is designed
# to drain a large backlog across many scheduled runs without ever hitting
# that wall:
#   • hard request budget per run (stay well under the ~65 block threshold)
#   • slower pacing between requests and batches
#   • circuit breaker — consecutive blocks abort the run instead of burning
#     through the backlog marking everything unavailable
#   • blocked videos are NOT marked unavailable (they stay pending for the
#     next run — a block is not evidence the transcript doesn't exist)
_BACKFILL_REQUEST_DELAY   = 15.0   # gentler than regular mode
_BACKFILL_BATCH_SIZE      = 5
_BACKFILL_BATCH_PAUSE     = 300.0  # 5 min between batches
_BACKFILL_REQUEST_BUDGET  = 40     # max transcript fetch attempts per run, ALL sources combined
_BACKFILL_BLOCK_THRESHOLD = 3      # consecutive IP blocks → abort the run


def _fetch_transcripts_batched(
    videos, channel_id, lang, skip_available, batch_size, batch_pause,
    backfill=False, budget=None,
):
    """
    budget: shared dict across all sources in one run (backfill mode only):
      {"remaining": int, "consecutive_blocks": int, "aborted": bool}
    """
    request_delay = _BACKFILL_REQUEST_DELAY if backfill else _REQUEST_DELAY

    need_fetch = [
        v for v in videos
        if not skip_available or store.should_retry_transcript(channel_id, v.video_id)
    ]

    # Backfill drains the NEVER-TRIED backlog only. Retrying previously-failed
    # videos is left to regular runs — otherwise a source with many failed
    # videos (e.g. old videos with captions disabled) starves the budget
    # before fresh videos are ever attempted.
    if backfill:
        need_fetch = [
            v for v in need_fetch
            if store.get_transcript_status(channel_id, v.video_id) == store.STATUS_NEVER_TRIED
        ]

    skip_count = len(videos) - len(need_fetch)

    # Backfill: respect the remaining global request budget up front
    if backfill and budget is not None:
        if budget["remaining"] <= 0 or budget["aborted"]:
            console.print("[yellow]⚠ Backfill budget exhausted — leaving remaining videos pending[/yellow]")
            transcripts_status = {
                v.video_id: store.STATUS_AVAILABLE
                for v in videos
                if not store.should_retry_transcript(channel_id, v.video_id)
            }
            return transcripts_status, 0, skip_count, 0
        if len(need_fetch) > budget["remaining"]:
            console.print(
                f"[dim]Backfill budget: fetching {budget['remaining']} of "
                f"{len(need_fetch)} pending (rest stay pending for next run)[/dim]"
            )
            need_fetch = need_fetch[:budget["remaining"]]

    transcripts_status = {
        v.video_id: store.STATUS_AVAILABLE
        for v in videos
        if not store.should_retry_transcript(channel_id, v.video_id)
    }

    saved = failed = 0
    total_batches = (len(need_fetch) + batch_size - 1) // batch_size if need_fetch else 0

    console.print(
        f"[dim]{len(videos)} total | {len(need_fetch)} to fetch | "
        f"{skip_count} already available | "
        f"{total_batches} batch(es) of {batch_size} | "
        f"{batch_pause:.0f}s pause between batches | "
        f"{request_delay:.0f}s per request"
        + (" | [bold]BACKFILL MODE[/bold]" if backfill else "")
        + "[/dim]"
    )

    if getattr(config, "COOKIES_FILE", "") and __import__("pathlib").Path(config.COOKIES_FILE).exists():
        console.print("[green]✓ Using cookies[/green]")

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  BarColumn(), TaskProgressColumn(), console=console) as progress:
        task = progress.add_task("Fetching…", total=len(need_fetch))

        i = 0
        batch_num = 0
        ip_retries = {}   # track retries per video_id

        while i < len(need_fetch):
            batch_num += 1
            batch_end = min(i + batch_size, len(need_fetch))
            batch     = need_fetch[i:batch_end]

            if batch_num > 1:
                console.print(f"\n[dim]Batch {batch_num}/{total_batches} — pausing {batch_pause:.0f}s…[/dim]")
                time.sleep(batch_pause)

            console.print(f"[cyan]Batch {batch_num}/{total_batches}[/cyan] [dim]({len(batch)} videos)[/dim]")

            j = 0
            while j < len(batch):
                video  = batch[j]
                vid_id = video.video_id
                ip_retries.setdefault(vid_id, 0)
                progress.update(task, description=f"[cyan]{video.title[:50]}[/cyan]")
                time.sleep(request_delay)

                if backfill and budget is not None:
                    budget["remaining"] -= 1

                try:
                    raw = fetch_transcript(vid_id, preferred_lang=lang)

                except Exception as exc:
                    if _is_ip_blocked(exc):
                        if backfill:
                            # Backfill: a block is NOT evidence the transcript
                            # doesn't exist — leave the video pending and count
                            # toward the circuit breaker.
                            budget["consecutive_blocks"] += 1
                            console.print(
                                f"\n[red]⚠ IP blocked on {vid_id} — leaving pending "
                                f"({budget['consecutive_blocks']}/{_BACKFILL_BLOCK_THRESHOLD} "
                                f"consecutive)[/red]"
                            )
                            progress.advance(task)
                            j += 1
                            if budget["consecutive_blocks"] >= _BACKFILL_BLOCK_THRESHOLD:
                                budget["aborted"] = True
                                console.print(
                                    "[bold red]✗ Circuit breaker: "
                                    f"{_BACKFILL_BLOCK_THRESHOLD} consecutive blocks — "
                                    "aborting backfill fetch for this run. "
                                    "Remaining videos stay pending.[/bold red]"
                                )
                                return transcripts_status, saved, skip_count, failed
                        elif ip_retries[vid_id] >= _MAX_IP_BLOCK_RETRIES_PER_VIDEO:
                            console.print(f"\n[red]✗ {vid_id} — giving up after {ip_retries[vid_id]+1} block(s)[/red]")
                            store.mark_transcript_unavailable(channel_id, vid_id, reason="IPBlocked")
                            transcripts_status[vid_id] = store.STATUS_UNAVAILABLE
                            failed += 1
                            progress.advance(task)
                            j += 1
                        else:
                            ip_retries[vid_id] += 1
                            console.print(
                                f"\n[red]IP blocked — pausing {_IP_BLOCK_PAUSE:.0f}s "
                                f"({ip_retries[vid_id]}/{_MAX_IP_BLOCK_RETRIES_PER_VIDEO})…[/red]"
                            )
                            time.sleep(_IP_BLOCK_PAUSE)
                    else:
                        console.print(f"[red]✗ {vid_id}: {exc}[/red]")
                        store.mark_transcript_unavailable(channel_id, vid_id, reason=type(exc).__name__)
                        transcripts_status[vid_id] = store.STATUS_UNAVAILABLE
                        failed += 1
                        progress.advance(task)
                        j += 1
                    continue

                ip_retries[vid_id] = 0
                if backfill and budget is not None:
                    budget["consecutive_blocks"] = 0
                progress.advance(task)
                j += 1

                if raw is None:
                    store.mark_transcript_unavailable(channel_id, vid_id, reason="NoTranscript")
                    transcripts_status[vid_id] = store.STATUS_UNAVAILABLE
                    failed += 1
                    continue

                processed = process_transcript(raw)
                d = processed.to_dict()
                d["transcript_status"] = store.STATUS_AVAILABLE
                store.save_transcript(channel_id, d)
                transcripts_status[vid_id] = store.STATUS_AVAILABLE
                saved += 1

            i = batch_end

    return transcripts_status, saved, skip_count, failed


def run_pipeline(channels, playlists, max_videos, skip_available, lang,
                 enrich=True, force_enrich=False,
                 clean_captions=True, force_captions=False,
                 batch_size=10, batch_pause=180.0, backfill=False):
    total_saved = total_skipped = total_failed = total_enriched = total_srt = 0

    # Backfill: one shared budget across ALL sources in this run
    budget = None
    if backfill:
        budget = {
            "remaining":          _BACKFILL_REQUEST_BUDGET,
            "consecutive_blocks": 0,
            "aborted":            False,
        }
        console.print(
            f"[bold yellow]BACKFILL MODE[/bold yellow] — "
            f"budget {_BACKFILL_REQUEST_BUDGET} fetches this run, "
            f"circuit breaker at {_BACKFILL_BLOCK_THRESHOLD} consecutive blocks"
        )

    # Build a unified list of (label, videos_fetcher) to process identically
    sources = []
    for channel in channels:
        sources.append((channel, lambda ch=channel: fetch_channel_videos(ch, max_videos=max_videos)))
    for playlist_id in playlists:
        sources.append((playlist_id, lambda pl=playlist_id: fetch_playlist_videos(pl, max_videos=max_videos)))

    for source_label, fetch_fn in sources:
        channel = source_label  # kept for logging compatibility below
        console.rule(f"[bold blue]Channel: {channel}[/bold blue]")
        try:
            videos = fetch_fn()
        except Exception as exc:
            console.print(f"[red]✗ {channel}: {exc}[/red]"); continue

        if not videos:
            console.print("[yellow]No videos found.[/yellow]"); continue

        channel_id = videos[0].channel_id or channel.lstrip("@")
        store.save_channel_metadata(channel_id, [v.to_dict() for v in videos])

        transcripts_status, saved, skipped, failed = _fetch_transcripts_batched(
            videos, channel_id, lang, skip_available, batch_size, batch_pause,
            backfill=backfill, budget=budget,
        )
        total_saved += saved; total_skipped += skipped; total_failed += failed

        if enrich and config.ANTHROPIC_API_KEY:
            console.print(f"\n[bold]Enriching…[/bold]")
            for video in videos:
                vid_id = video.video_id
                if transcripts_status.get(vid_id) != store.STATUS_AVAILABLE: continue
                if not store.should_enrich(channel_id, vid_id, force=force_enrich): continue
                if enrich_transcript(channel_id, video.to_dict(), force=force_enrich):
                    total_enriched += 1
                    time.sleep(0.5)

        if clean_captions:
            console.print(f"\n[bold]Generating clean captions…[/bold]")
            for video in videos:
                vid_id = video.video_id
                if not store.transcript_exists(channel_id, vid_id): continue
                if not force_captions and already_cleaned(channel_id, vid_id): continue
                if generate_clean_captions(channel_id, vid_id, force=force_captions):
                    total_srt += 1

        store.update_index([v.to_dict() for v in videos], transcripts_status)
        console.print(
            f"\n[green]✓[/green] {channel} — "
            f"[green]{saved} saved[/green]  [yellow]{skipped} skipped[/yellow]  "
            f"[red]{failed} unavailable[/red]  [blue]{total_enriched} enriched[/blue]  "
            f"[magenta]{total_srt} SRTs[/magenta]"
        )

    _rebuild_index()
    table = Table(title="Pipeline Summary", show_header=True)
    table.add_column("Result", style="bold"); table.add_column("Count", justify="right")
    table.add_row("[green]Transcripts saved[/green]",             str(total_saved))
    table.add_row("[yellow]Already available (skipped)[/yellow]", str(total_skipped))
    table.add_row("[red]Unavailable — will retry[/red]",          str(total_failed))
    table.add_row("[blue]Enriched[/blue]",                        str(total_enriched))
    table.add_row("[magenta]Clean SRTs generated[/magenta]",      str(total_srt))
    console.print(table)
    store.backup_index()


@click.command()
@click.option("--channel", "-c", multiple=True)
@click.option("--playlist", "-p", multiple=True, help="Fetch a specific playlist ID (can be used multiple times)")
@click.option("--max", "max_videos", default=None, type=int)
@click.option("--no-skip", is_flag=True, default=False)
@click.option("--lang", default=None)
@click.option("--enrich-only", is_flag=True, default=False)
@click.option("--captions-only", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
@click.option("--no-enrich", is_flag=True, default=False)
@click.option("--no-captions", is_flag=True, default=False)
@click.option("--export-index", is_flag=True)
@click.option("--batch-size", default=0)
@click.option("--batch-pause", default=0.0)
@click.option("--backfill", is_flag=True, default=False,
              help="Backfill mode for large backlogs: gentler pacing, "
                   "global request budget per run, circuit breaker on repeated "
                   "IP blocks, and blocked videos stay pending (not marked "
                   "unavailable). Run repeatedly (or on schedule) until the "
                   "backlog drains. Regular daily runs are unaffected.")
def main(channel, playlist, max_videos, no_skip, lang,
         enrich_only, captions_only, force, no_enrich, no_captions, export_index,
         batch_size, batch_pause, backfill):
    """YouTube transcript pipeline."""

    if export_index:
        _rebuild_index(); sys.exit(0)
    if enrich_only:
        enrich_all_channels(force=force); sys.exit(0)
    if captions_only:
        clean_captions_all_channels(force=force); _rebuild_index(); sys.exit(0)

    channels  = list(channel)  or config.CHANNELS
    playlists = list(playlist) or config.PLAYLISTS

    if not channels and not playlists:
        console.print("[red]No channels or playlists specified.[/red]"); sys.exit(1)

    effective_max   = config.MAX_VIDEOS_PER_CHANNEL if max_videos is None else max_videos
    effective_lang  = lang        or config.TRANSCRIPT_LANG

    if backfill:
        # Backfill pacing defaults — explicit CLI values still win
        effective_batch = batch_size  or _BACKFILL_BATCH_SIZE
        effective_pause = batch_pause or _BACKFILL_BATCH_PAUSE
    else:
        effective_batch = batch_size  or config.BATCH_SIZE
        effective_pause = batch_pause or config.BATCH_PAUSE

    console.print(
        f"[bold]Pipeline[/bold] | max={effective_max or 'all'} | "
        f"batch={effective_batch} | pause={effective_pause:.0f}s | "
        f"request_delay={_REQUEST_DELAY:.0f}s"
    )
    if channels:
        console.print(f"[dim]Channels:  {', '.join(channels)}[/dim]")
    if playlists:
        console.print(f"[dim]Playlists: {len(playlists)} playlist(s)[/dim]")

    run_pipeline(
        channels=channels, playlists=playlists, max_videos=effective_max,
        skip_available=not no_skip, lang=effective_lang,
        enrich=not no_enrich, force_enrich=force,
        clean_captions=not no_captions, force_captions=force,
        batch_size=effective_batch, batch_pause=effective_pause,
        backfill=backfill,
    )


if __name__ == "__main__":
    main()
