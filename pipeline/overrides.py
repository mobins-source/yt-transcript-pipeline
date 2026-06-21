"""
overrides.py — CSV-based manual override system for enriched transcript fields.

Workflow:
  1. python3 overrides.py export          → generate data/overrides.csv with current values
  2. Edit overrides.csv in Numbers/Excel  → fix AI-generated fields as needed
  3. python3 overrides.py apply           → write changes to transcript JSONs + rebuild index
                                            rows that are now in sync are removed automatically
  4. python3 overrides.py diff            → preview what would change before applying

Rules:
  - Blank cell  → keep existing value unchanged
  - Non-blank   → override that field
  - topic_tags  → comma or pipe separated, stored as a list
  - time_slot   → if blank AND day_of_week or time_of_day changed,
                  auto-recomputes (Friday+Zuhr → Jumaa Khutba)
"""
from __future__ import annotations

import csv
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

import config
import store
from enrich import _rebuild_index

console = Console()

OVERRIDES_PATH = config.DATA_DIR / "overrides.csv"

EXPORT_FIELDS = [
    "video_id", "channel_id", "title",
    "suggested_title", "catchy_title", "content_type", "hadith_book", "hadith_chapter",
    "topic_tags", "time_of_day", "day_of_week", "time_slot",
    "post_date", "reviewed", "notes",
]

EDITABLE_FIELDS = {
    "suggested_title", "catchy_title", "content_type", "hadith_book", "hadith_chapter",
    "topic_tags", "time_of_day", "day_of_week", "time_slot", "reviewed",
}


def _recompute_time_slot(day: str, tod: str) -> str:
    if day == "Friday" and tod == "Zuhr":
        return "Jumaa Khutba"
    return f"{day}-{tod}" if day and tod else ""


def _parse_tags(raw: str) -> list[str]:
    if not raw:
        return []
    sep = "|" if "|" in raw else ","
    return [t.strip().lower() for t in raw.split(sep) if t.strip()]


def _tx_to_row(channel_id: str, meta: dict, tx: dict | None) -> dict:
    tags = tx.get("topic_tags", []) if tx else []
    tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
    return {
        "video_id":        meta.get("video_id", ""),
        "channel_id":      channel_id,
        "title":           meta.get("title", ""),
        "suggested_title": tx.get("suggested_title", "") if tx else "",
        "catchy_title":    tx.get("catchy_title",    "") if tx else "",
        "content_type":    tx.get("content_type",    "") if tx else "",
        "hadith_book":     tx.get("hadith_book",     "") or "" if tx else "",
        "hadith_chapter":  tx.get("hadith_chapter",  "") or "" if tx else "",
        "topic_tags":      tags_str,
        "time_of_day":     tx.get("time_of_day",     "") if tx else "",
        "day_of_week":     tx.get("day_of_week",     "") if tx else "",
        "time_slot":       tx.get("time_slot",       "") if tx else "",
        "post_date":       tx.get("post_date", meta.get("post_date", "")) if tx else "",
        "reviewed":        tx.get("reviewed",        "") if tx else "",
        "notes":           tx.get("notes",           "") if tx else "",
    }


def _write_rows(rows: list[dict], path: Path = OVERRIDES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_rows(path: Path = OVERRIDES_PATH) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _row_is_synced(row: dict) -> bool:
    """
    Returns True if all non-blank editable fields in the CSV row already
    match the stored transcript JSON — meaning this row has been fully applied
    and can safely be removed from the CSV.
    Returns False if transcript not found (keep the row just in case).
    """
    vid_id     = row.get("video_id",   "").strip()
    channel_id = row.get("channel_id", "").strip()
    if not vid_id or not channel_id:
        return False

    tx = store.load_transcript(channel_id, vid_id)
    if tx is None:
        return False  # can't verify — keep row

    for field in EDITABLE_FIELDS:
        csv_val = row.get(field, "").strip()
        if not csv_val:
            continue  # blank = not an override, skip

        if field == "topic_tags":
            csv_tags = _parse_tags(csv_val)
            json_tags = tx.get(field, [])
            if isinstance(json_tags, list):
                json_tags = json_tags
            else:
                json_tags = []
            if sorted(csv_tags) != sorted(json_tags):
                return False  # still differs
        else:
            json_val = str(tx.get(field, "") or "")
            if csv_val != json_val:
                return False  # still differs

    return True  # all non-blank fields are in sync


# ── Export ────────────────────────────────────────────────────────────────────

def export_overrides(output_path: Path = OVERRIDES_PATH) -> int:
    rows = []
    for channel_id in store.list_all_channel_ids():
        for meta in store.load_channel_metadata(channel_id):
            tx = store.load_transcript(channel_id, meta["video_id"])
            rows.append(_tx_to_row(channel_id, meta, tx))
    rows.sort(key=lambda r: r.get("post_date", ""), reverse=True)
    _write_rows(rows, output_path)
    console.print(f"[green]✓ Exported {len(rows)} videos → {output_path}[/green]")
    return len(rows)


# ── Diff ──────────────────────────────────────────────────────────────────────

def diff_overrides(input_path: Path = OVERRIDES_PATH) -> list[dict]:
    rows = _read_rows(input_path)
    if not rows:
        console.print(f"[red]✗ {input_path} not found or empty.[/red]")
        return []

    changes = []
    for row in rows:
        vid_id     = row.get("video_id",   "").strip()
        channel_id = row.get("channel_id", "").strip()
        if not vid_id or not channel_id:
            continue
        tx = store.load_transcript(channel_id, vid_id)
        if tx is None:
            continue
        for field in EDITABLE_FIELDS:
            new_raw = row.get(field, "").strip()
            if not new_raw:
                continue
            if field == "topic_tags":
                new_val = _parse_tags(new_raw)
                old_val = tx.get(field, [])
                if sorted(new_val) != sorted(old_val if isinstance(old_val, list) else []):
                    changes.append({
                        "video_id": vid_id, "channel_id": channel_id,
                        "title": row.get("title", "")[:50], "field": field,
                        "old_value": ",".join(old_val) if isinstance(old_val, list) else str(old_val),
                        "new_value": ",".join(new_val),
                    })
            else:
                new_val = new_raw
                old_val = str(tx.get(field, "") or "")
                if new_val != old_val:
                    changes.append({
                        "video_id": vid_id, "channel_id": channel_id,
                        "title": row.get("title", "")[:50], "field": field,
                        "old_value": old_val, "new_value": new_val,
                    })
    return changes


def print_diff(changes: list[dict]) -> None:
    if not changes:
        console.print("[green]No changes detected.[/green]")
        return
    table = Table(title=f"{len(changes)} pending change(s)", show_header=True)
    table.add_column("Video",     max_width=40)
    table.add_column("Field",     style="cyan")
    table.add_column("Old value", style="red",   max_width=30)
    table.add_column("New value", style="green", max_width=30)
    for c in changes:
        table.add_row(
            f"{c['title']}\n[dim]{c['video_id']}[/dim]",
            c["field"],
            c["old_value"] or "[dim]empty[/dim]",
            c["new_value"],
        )
    console.print(table)


# ── Apply ─────────────────────────────────────────────────────────────────────

def apply_overrides(input_path: Path = OVERRIDES_PATH, dry_run: bool = False) -> int:
    """
    Apply CSV overrides to transcript JSON files and rebuild index.

    After applying, removes any CSV row that is now fully in sync with
    the JSON — whether just applied this run or applied in a previous run.
    This ensures the frontend 'override pending' badge always clears.
    """
    changes = diff_overrides(input_path)

    if not changes:
        # No new changes — but still clean up any already-synced rows
        synced = [row for row in _read_rows(input_path) if _row_is_synced(row)]
        if synced:
            remaining = [row for row in _read_rows(input_path) if not _row_is_synced(row)]
            _write_rows(remaining, input_path)
            console.print(
                f"[green]✓ Removed {len(synced)} already-synced row(s) from overrides.csv[/green]"
            )
        else:
            console.print("[green]Nothing to apply and no stale rows found.[/green]")
        return 0

    print_diff(changes)

    if dry_run:
        console.print("\n[yellow]Dry run — no changes written.[/yellow]")
        return 0

    # Group changes by video
    by_video: dict[tuple, list[dict]] = {}
    for c in changes:
        key = (c["channel_id"], c["video_id"])
        by_video.setdefault(key, []).append(c)

    updated = 0

    for (channel_id, vid_id), video_changes in by_video.items():
        tx = store.load_transcript(channel_id, vid_id)
        if tx is None:
            continue

        for c in video_changes:
            field   = c["field"]
            new_val = c["new_value"]
            tx[field] = _parse_tags(new_val) if field == "topic_tags" else new_val

        # Auto-recompute time_slot if day/time changed but slot not explicitly set
        changed_fields = {c["field"] for c in video_changes}
        if ("day_of_week" in changed_fields or "time_of_day" in changed_fields) \
                and "time_slot" not in changed_fields:
            tx["time_slot"] = _recompute_time_slot(
                tx.get("day_of_week", ""), tx.get("time_of_day", "")
            )

        tx["manually_reviewed"] = True
        store.save_transcript(channel_id, tx)
        updated += 1
        console.print(f"[green]✓[/green] Updated {vid_id} ({len(video_changes)} field(s))")

    # Rebuild index
    _rebuild_index()

    # ── Post-apply cleanup ─────────────────────────────────────────────────
    # Remove every row that is now in sync with the JSON — covers both:
    # (a) rows just applied this run, and
    # (b) rows applied in a previous run that were never cleaned up
    all_rows      = _read_rows(input_path)
    remaining     = [row for row in all_rows if not _row_is_synced(row)]
    removed_count = len(all_rows) - len(remaining)
    _write_rows(remaining, input_path)

    if remaining:
        console.print(
            f"[dim]{removed_count} row(s) removed, "
            f"{len(remaining)} remain (still differ from JSON)[/dim]"
        )
    else:
        console.print("[dim]overrides.csv cleared — all rows in sync[/dim]")

    console.print(f"\n[bold green]✓ Applied changes to {updated} video(s).[/bold green]")
    return updated


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Manage manual overrides for enriched transcript fields."""
    pass


@cli.command()
@click.option("--output", default=str(OVERRIDES_PATH))
def export(output):
    """Export current values to CSV for review."""
    export_overrides(Path(output))


@cli.command()
@click.option("--input", "input_path", default=str(OVERRIDES_PATH))
def diff(input_path):
    """Preview changes from CSV without applying them."""
    changes = diff_overrides(Path(input_path))
    print_diff(changes)


@cli.command()
@click.option("--input", "input_path", default=str(OVERRIDES_PATH))
@click.option("--dry-run", is_flag=True, default=False)
def apply(input_path, dry_run):
    """Apply CSV overrides to transcript JSON files and rebuild index."""
    apply_overrides(Path(input_path), dry_run=dry_run)


if __name__ == "__main__":
    cli()
