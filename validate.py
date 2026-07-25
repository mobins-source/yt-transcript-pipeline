#!/usr/bin/env python3
"""
validate.py — Full-stack data integrity tests for the yt-transcript-pipeline.

Runs on any platform (Mac or Windows). Exits with code 0 on success,
code 1 on any failure — safe to use as a GitHub Actions job step.

Usage:
  python3 validate.py            # local run from repo root
  python3 validate.py --local    # skip live URL checks (offline mode)
  python3 validate.py --verbose  # print every check as it runs

Checks:
  LOCAL  (reads files from data/ on disk):
    1.  Per-channel index files exist for all known channels
    2.  Combined index.json exists
    3.  Per-channel index files are under 2MB (Next.js cache limit)
    4.  Combined index.json retains full fields (admin viewer protection)
    5.  Required site fields present on every video in per-channel indexes
    6.  Forbidden heavy fields absent from per-channel indexes
    7.  Video counts are sane (no catastrophic drop vs transcript file count)
    8.  All videos in per-channel index have a matching transcript JSON file
    9.  Overrides CSV is valid (parseable, has expected columns)

  LIVE   (fetches from GitHub raw URLs, mirrors what the site fetches):
    10. Per-channel index URLs return HTTP 200
    11. Per-channel index sizes under 2MB over the wire
    12. Required fields present in live index data
    13. Combined fallback index URL returns HTTP 200

Exit codes:
  0  all checks passed
  1  one or more checks failed
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).resolve().parent
DATA_DIR     = REPO_ROOT / "data"
METADATA_DIR = DATA_DIR / "metadata"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
OVERRIDES_CSV   = DATA_DIR / "overrides.csv"

GITHUB_RAW = "https://raw.githubusercontent.com/mobins-source/yt-transcript-pipeline/main/data"

KNOWN_CHANNELS = {
    "UCt-XeQTVRSETC9DceeC6nMw": "MCC Tucson",
    "UCXQm5nWl_fhxQwgHnRsPZPg": "The Mosque Foundation (Sh. Ali Mashhour)",
}

# Fields the mcc-khutba site reads from the index (from lib/data.js analysis).
# Note: only fields on ENRICHED videos (has_transcript=True) are checked.
# Un-enriched videos legitimately lack these fields.
REQUIRED_SITE_FIELDS = {
    "video_id", "title", "channel_id", "url",
    "post_date", "year", "month", "actual_at",
    "time_slot", "day_of_week", "content_type",
    "hadith_book", "has_transcript",
    "has_clean_srt", "catchy_title", "suggested_title",
    "topic_tags", "summary", "duration_seconds",
    "playlist_id", "playlist_title",
    # hadith_chapter is optional — not all enriched videos have a chapter
}

# Fields that must NOT appear in per-channel index (only in transcript JSONs)
FORBIDDEN_INDEX_FIELDS = {
    "segments", "clean_text", "raw_transcript", "words",
}

# Per-channel index must stay under this size (Next.js fetch cache limit)
MAX_INDEX_BYTES = 2_000_000  # 2 MB

# Overrides CSV expected columns (subset — these must exist)
REQUIRED_CSV_COLUMNS = {
    "video_id", "channel_id", "content_type", "hadith_book",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

class Results:
    def __init__(self, verbose: bool):
        self.verbose = verbose
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    def ok(self, name: str, detail: str = ""):
        self.passed.append(name)
        if self.verbose:
            msg = f"  ✓  {name}"
            if detail:
                msg += f" — {detail}"
            print(msg)

    def fail(self, name: str, detail: str = ""):
        self.failed.append(name)
        msg = f"  ✗  {name}"
        if detail:
            msg += f"\n     {detail}"
        print(msg)

    def warn(self, name: str, detail: str = ""):
        self.warnings.append(name)
        msg = f"  ⚠  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    def summary(self) -> int:
        """Print summary and return exit code (0=pass, 1=fail)."""
        print()
        print("─" * 60)
        total = len(self.passed) + len(self.failed)
        print(f"Results: {len(self.passed)}/{total} checks passed"
              + (f", {len(self.warnings)} warning(s)" if self.warnings else ""))
        if self.failed:
            print(f"\nFailed checks:")
            for f in self.failed:
                print(f"  • {f}")
        if self.warnings:
            print(f"\nWarnings (non-blocking):")
            for w in self.warnings:
                print(f"  • {w}")
        if not self.failed:
            print("\n✓ All checks passed.")
        return 1 if self.failed else 0


def load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return None


def fetch_url(url: str) -> tuple[int, bytes]:
    """Returns (status_code, body_bytes). Status 0 = connection error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "validate.py/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


# ── Local checks ──────────────────────────────────────────────────────────────

def check_local(r: Results) -> None:
    print("\n── Local file checks ──────────────────────────────────────")

    # 1. Per-channel index files exist
    for ch_id, ch_name in KNOWN_CHANNELS.items():
        path = METADATA_DIR / f"index-{ch_id}.json"
        if path.exists():
            r.ok(f"Per-channel index exists: {ch_name}", str(path.name))
        else:
            r.fail(f"Per-channel index missing: {ch_name}", str(path))

    # 2. Combined index.json exists
    combined = METADATA_DIR / "index.json"
    if combined.exists():
        r.ok("Combined index.json exists")
    else:
        r.fail("Combined index.json missing", str(combined))
        return  # can't continue without it

    # 3. Per-channel index sizes under 2MB
    for ch_id, ch_name in KNOWN_CHANNELS.items():
        path = METADATA_DIR / f"index-{ch_id}.json"
        if not path.exists():
            continue
        size = path.stat().st_size
        if size < MAX_INDEX_BYTES:
            r.ok(f"Per-channel index size OK: {ch_name}",
                 f"{size/1024:.0f} KB < 2 MB")
        else:
            r.fail(f"Per-channel index too large: {ch_name}",
                   f"{size/1024:.0f} KB >= 2000 KB — Next.js won't cache it")

    # 4. Combined index retains full fields (admin viewer protection)
    combined_data = load_json(combined)
    if combined_data and isinstance(combined_data, dict):
        sample_videos = combined_data.get("videos", [])
        if sample_videos:
            sample = sample_videos[0]
            if "summary" in sample:
                r.ok("Combined index retains full fields (admin viewer safe)")
            else:
                r.fail("Combined index missing 'summary' — may have been accidentally slimmed")
        else:
            r.warn("Combined index has 0 videos — empty?")
    else:
        r.fail("Combined index.json is not valid JSON")

    # 5 & 6. Per-channel index field checks
    for ch_id, ch_name in KNOWN_CHANNELS.items():
        path = METADATA_DIR / f"index-{ch_id}.json"
        if not path.exists():
            continue
        data = load_json(path)
        if not data or not isinstance(data, dict):
            r.fail(f"Per-channel index invalid JSON: {ch_name}")
            continue

        videos = data.get("videos", [])
        if not videos:
            r.warn(f"Per-channel index has 0 videos: {ch_name}")
            continue

        # Check required fields — only on fully enriched videos.
        # has_transcript=True can be set on stub files (transcript_status=unavailable)
        # that were never actually enriched. Use post_date as a proxy for
        # enrichment completion since it's only set after successful enrichment.
        enriched = [
            v for v in videos
            if v.get("has_transcript") and v.get("post_date")
        ]
        if not enriched:
            r.warn(f"No enriched videos to field-check: {ch_name}")
            continue

        # Sample up to 40 enriched videos spread across the index
        step = max(1, len(enriched) // 40)
        sample = enriched[::step][:40]
        missing_fields: dict[str, list[str]] = {}
        forbidden_found: dict[str, list[str]] = {}

        for v in sample:
            vid_id = v.get("video_id", "unknown")
            for f in REQUIRED_SITE_FIELDS:
                if f not in v:
                    missing_fields.setdefault(f, []).append(vid_id)
            for f in FORBIDDEN_INDEX_FIELDS:
                if f in v:
                    forbidden_found.setdefault(f, []).append(vid_id)

        if not missing_fields:
            r.ok(f"Required fields present: {ch_name}",
                 f"checked {len(sample)} videos")
        else:
            for field, vids in missing_fields.items():
                r.fail(
                    f"Required field '{field}' missing: {ch_name}",
                    f"Affected video_ids (up to 3): {vids[:3]}"
                )

        if not forbidden_found:
            r.ok(f"No forbidden heavy fields: {ch_name}")
        else:
            for field, vids in forbidden_found.items():
                r.fail(
                    f"Forbidden field '{field}' found in per-channel index: {ch_name}",
                    f"Affected video_ids (up to 3): {vids[:3]}"
                )

    # 7. Video counts sanity check
    for ch_id, ch_name in KNOWN_CHANNELS.items():
        index_path = METADATA_DIR / f"index-{ch_id}.json"
        tx_dir = TRANSCRIPTS_DIR / ch_id
        if not index_path.exists() or not tx_dir.exists():
            continue

        data = load_json(index_path)
        index_count = len(data.get("videos", [])) if data else 0
        tx_files = list(tx_dir.glob("*.json"))
        tx_count = len(tx_files)

        # Index should have <= transcript file count (index may have pending videos too)
        if index_count == 0:
            r.fail(f"Video count catastrophic: {ch_name}", "0 videos in index")
        elif tx_count > 0 and index_count < tx_count * 0.5:
            r.fail(
                f"Video count mismatch: {ch_name}",
                f"Index has {index_count} videos but {tx_count} transcript files exist — possible data loss"
            )
        else:
            r.ok(f"Video count sane: {ch_name}",
                 f"{index_count} in index, {tx_count} transcript files")

    # 8. All index videos have a transcript file
    for ch_id, ch_name in KNOWN_CHANNELS.items():
        index_path = METADATA_DIR / f"index-{ch_id}.json"
        tx_dir = TRANSCRIPTS_DIR / ch_id
        if not index_path.exists():
            continue
        data = load_json(index_path)
        if not data:
            continue
        missing_tx = []
        for v in data.get("videos", []):
            # Only check videos that are fully enriched (have post_date)
            # Stub files (transcript_status=unavailable) legitimately lack segments
            if v.get("has_transcript") and v.get("post_date"):
                tx_file = tx_dir / f"{v['video_id']}.json"
                if not tx_file.exists():
                    missing_tx.append(v["video_id"])
        if not missing_tx:
            r.ok(f"All has_transcript=True videos have transcript files: {ch_name}")
        else:
            r.fail(
                f"Transcript files missing for has_transcript=True videos: {ch_name}",
                f"{len(missing_tx)} missing. First 3: {missing_tx[:3]}"
            )

    # 9. Overrides CSV valid
    if OVERRIDES_CSV.exists():
        try:
            with open(OVERRIDES_CSV, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                cols = set(reader.fieldnames or [])
                rows = list(reader)
            missing_cols = REQUIRED_CSV_COLUMNS - cols
            if missing_cols:
                r.fail("Overrides CSV missing columns", str(missing_cols))
            else:
                r.ok("Overrides CSV valid", f"{len(rows)} rows, required columns present")
        except Exception as e:
            r.fail("Overrides CSV parse error", str(e))
    else:
        r.warn("Overrides CSV not found (non-blocking — may not exist yet)")


# ── Live URL checks ───────────────────────────────────────────────────────────

def check_live(r: Results) -> None:
    print("\n── Live URL checks (GitHub raw) ───────────────────────────")

    # 10 & 11 & 12. Per-channel index URLs
    for ch_id, ch_name in KNOWN_CHANNELS.items():
        url = f"{GITHUB_RAW}/metadata/index-{ch_id}.json"
        status, body = fetch_url(url)

        if status == 200:
            r.ok(f"Per-channel index URL reachable: {ch_name}", f"HTTP {status}")
        else:
            r.fail(f"Per-channel index URL unreachable: {ch_name}",
                   f"HTTP {status} — {url}")
            continue

        # Size check over the wire
        size = len(body)
        if size < MAX_INDEX_BYTES:
            r.ok(f"Live index size OK: {ch_name}", f"{size/1024:.0f} KB")
        else:
            r.fail(f"Live index too large: {ch_name}",
                   f"{size/1024:.0f} KB >= 2000 KB — Next.js won't cache it")

        # Field check on live data
        try:
            data = json.loads(body)
            videos = data.get("videos", [])
            if videos:
                sample = videos[:5]
                for v in sample:
                    missing = REQUIRED_SITE_FIELDS - set(v.keys())
                    if missing:
                        r.fail(
                            f"Required fields missing in live index: {ch_name}",
                            f"Missing: {missing} in video {v.get('video_id')}"
                        )
                        break
                else:
                    r.ok(f"Required fields present in live index: {ch_name}")
            else:
                r.warn(f"Live index has 0 videos: {ch_name}")
        except Exception as e:
            r.fail(f"Live index JSON parse error: {ch_name}", str(e))

    # 13. Combined fallback index
    url = f"{GITHUB_RAW}/metadata/index.json"
    status, _ = fetch_url(url)
    if status == 200:
        r.ok("Combined fallback index URL reachable", f"HTTP {status}")
    else:
        r.fail("Combined fallback index URL unreachable", f"HTTP {status} — {url}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate yt-transcript-pipeline data integrity")
    parser.add_argument("--local", action="store_true",
                        help="Skip live URL checks (offline mode)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every check result, not just failures")
    args = parser.parse_args()

    print("validate.py — yt-transcript-pipeline data integrity checks")
    print(f"Repo root: {REPO_ROOT}")
    print(f"Mode: {'local only' if args.local else 'local + live URLs'}")

    r = Results(verbose=args.verbose)

    check_local(r)
    if not args.local:
        check_live(r)
    else:
        print("\n── Live URL checks skipped (--local flag) ─────────────────")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
