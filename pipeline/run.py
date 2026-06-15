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
from fetch_channel import fetch_channel_videos
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


def _fetch_transcripts_batched(
    videos, channel_id, lang, skip_available, batch_size, batch_pause
):
    need_fetch = [
        v for v in videos
        if not skip_available or store.should_retry_transcript(channel_id, v.video_id)
    ]
    skip_count = len(videos) - len(need_fetch)

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
        f"{_REQUEST_DELAY:.0f}s per request[/dim]"
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
                time.sleep(_REQUEST_DELAY)

                try:
                    raw = fetch_transcript(vid_id, preferred_lang=lang)

                except Exception as exc:
                    if _is_ip_blocked(exc):
                        if ip_retries[vid_id] >= _MAX_IP_BLOCK_RETRIES_PER_VIDEO:
                            console.print(f"\n[red]✗ {vid_id} — giving up after {ip_retries[vid_id]+1} block(s)[/red]")
                            store.mark_transcript_unavailable(channel_id, vid_id)
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
                        store.mark_transcript_unavailable(channel_id, vid_id)
                        transcripts_status[vid_id] = store.STATUS_UNAVAILABLE
                        failed += 1
                        progress.advance(task)
                        j += 1
                    continue

                ip_retries[vid_id] = 0
                progress.advance(task)
                j += 1

                if raw is None:
                    store.mark_transcript_unavailable(channel_id, vid_id)
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


def run_pipeline(channels, max_videos, skip_available, lang,
                 enrich=True, force_enrich=False,
                 clean_captions=True, force_captions=False,
                 batch_size=10, batch_pause=180.0):
    total_saved = total_skipped = total_failed = total_enriched = total_srt = 0

    for channel in channels:
        console.rule(f"[bold blue]Channel: {channel}[/bold blue]")
        try:
            videos = fetch_channel_videos(channel, max_videos=max_videos)
        except Exception as exc:
            console.print(f"[red]✗ {channel}: {exc}[/red]"); continue

        if not videos:
            console.print("[yellow]No videos found.[/yellow]"); continue

        channel_id = videos[0].channel_id or channel.lstrip("@")
        store.save_channel_metadata(channel_id, [v.to_dict() for v in videos])

        transcripts_status, saved, skipped, failed = _fetch_transcripts_batched(
            videos, channel_id, lang, skip_available, batch_size, batch_pause
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
def main(channel, max_videos, no_skip, lang,
         enrich_only, captions_only, force, no_enrich, no_captions, export_index,
         batch_size, batch_pause):
    """YouTube transcript pipeline."""

    if export_index:
        _rebuild_index(); sys.exit(0)
    if enrich_only:
        enrich_all_channels(force=force); sys.exit(0)
    if captions_only:
        clean_captions_all_channels(force=force); _rebuild_index(); sys.exit(0)

    channels = list(channel) or config.CHANNELS
    if not channels:
        console.print("[red]No channels specified.[/red]"); sys.exit(1)

    effective_max   = config.MAX_VIDEOS_PER_CHANNEL if max_videos is None else max_videos
    effective_lang  = lang        or config.TRANSCRIPT_LANG
    effective_batch = batch_size  or config.BATCH_SIZE
    effective_pause = batch_pause or config.BATCH_PAUSE

    console.print(
        f"[bold]Pipeline[/bold] | max={effective_max or 'all'} | "
        f"batch={effective_batch} | pause={effective_pause:.0f}s | "
        f"request_delay={_REQUEST_DELAY:.0f}s"
    )

    run_pipeline(
        channels=channels, max_videos=effective_max,
        skip_available=not no_skip, lang=effective_lang,
        enrich=not no_enrich, force_enrich=force,
        clean_captions=not no_captions, force_captions=force,
        batch_size=effective_batch, batch_pause=effective_pause,
    )


if __name__ == "__main__":
    main()
