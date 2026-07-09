"""
store.py — JSON file-based storage for transcripts and metadata.

Layout under DATA_DIR:
  transcripts/{channel_id}/{video_id}.json          ← ProcessedTranscript + enrichment
  transcripts/{channel_id}/{video_id}.clean_en.srt  ← cleaned English SRT
  transcripts/{channel_id}/{video_id}.clean_en.txt  ← clean readable transcript
  metadata/{channel_id}/videos.json                 ← list[VideoMeta]
  metadata/index.json                               ← flat index for frontend
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

# ── transcript_status values ──────────────────────────────────────────────────
STATUS_AVAILABLE   = "available"
STATUS_UNAVAILABLE = "unavailable"
STATUS_NEVER_TRIED = "never_tried"
STATUS_PERMANENT   = "permanently_unavailable"

# Exception class names that mean a transcript will NEVER exist for this video
# (uploader disabled captions, video is private/deleted/etc). Retrying these
# wastes the request budget — they're marked permanent on first occurrence.
PERMANENT_FAILURE_REASONS = {
    "TranscriptsDisabled",
    "VideoUnplayable",
    "VideoUnavailable",
    "AgeRestricted",
}

# Transient failures (e.g. captions not generated yet on a fresh video) are
# retried, but not forever — after this many attempts they're marked permanent.
MAX_TRANSIENT_RETRIES = 5

# ── srt_status values ─────────────────────────────────────────────────────────
SRT_PENDING   = "pending"
SRT_APPROVED  = "approved"
SRT_NEEDS_FIX = "needs_fix"
SRT_STATUSES  = {SRT_PENDING, SRT_APPROVED, SRT_NEEDS_FIX}


def _write_json(path: Path, data: Any, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ── Transcript storage ────────────────────────────────────────────────────────

def save_transcript(channel_id: str, processed: Any) -> Path:
    path = config.TRANSCRIPTS_DIR / channel_id / f"{processed['video_id']}.json"
    _write_json(path, processed)
    return path


def load_transcript(channel_id: str, video_id: str) -> dict | None:
    path = config.TRANSCRIPTS_DIR / channel_id / f"{video_id}.json"
    return _read_json(path) if path.exists() else None


def transcript_exists(channel_id: str, video_id: str) -> bool:
    return (config.TRANSCRIPTS_DIR / channel_id / f"{video_id}.json").exists()


def get_transcript_status(channel_id: str, video_id: str) -> str:
    tx = load_transcript(channel_id, video_id)
    if tx is None:
        return STATUS_NEVER_TRIED
    return tx.get("transcript_status", STATUS_AVAILABLE if tx.get("clean_text") else STATUS_NEVER_TRIED)


def mark_transcript_unavailable(channel_id: str, video_id: str, reason: str = "") -> None:
    path = config.TRANSCRIPTS_DIR / channel_id / f"{video_id}.json"
    existing = _read_json(path) if path.exists() else {"video_id": video_id}
    existing["transcript_status"]      = STATUS_UNAVAILABLE
    existing["transcript_retry_count"] = existing.get("transcript_retry_count", 0) + 1
    if reason:
        existing["unavailable_reason"] = reason
    # Permanent: known-permanent failure reason, or transient retry cap reached
    if reason in PERMANENT_FAILURE_REASONS or \
       existing["transcript_retry_count"] >= MAX_TRANSIENT_RETRIES:
        existing["transcript_status"] = STATUS_PERMANENT
    _write_json(path, existing)


def should_retry_transcript(channel_id: str, video_id: str) -> bool:
    # STATUS_PERMANENT is deliberately excluded — never retried
    status = get_transcript_status(channel_id, video_id)
    return status in (STATUS_NEVER_TRIED, STATUS_UNAVAILABLE)


def should_enrich(channel_id: str, video_id: str, force: bool = False) -> bool:
    if force:
        return True
    tx = load_transcript(channel_id, video_id)
    if not tx or tx.get("transcript_status") != STATUS_AVAILABLE:
        return False
    return "summary" not in tx or "time_of_day" not in tx or "actual_at" not in tx


# ── SRT storage ───────────────────────────────────────────────────────────────

def srt_path(channel_id: str, video_id: str) -> Path:
    return config.TRANSCRIPTS_DIR / channel_id / f"{video_id}.clean_en.srt"


def srt_exists(channel_id: str, video_id: str) -> bool:
    return srt_path(channel_id, video_id).exists()


def load_srt(channel_id: str, video_id: str) -> str | None:
    p = srt_path(channel_id, video_id)
    return p.read_text(encoding="utf-8") if p.exists() else None


def get_srt_status(channel_id: str, video_id: str) -> str | None:
    if not srt_exists(channel_id, video_id):
        return None
    tx = load_transcript(channel_id, video_id)
    return tx.get("srt_status", SRT_PENDING) if tx else SRT_PENDING


def save_srt_status(channel_id: str, video_id: str, status: str) -> bool:
    if status not in SRT_STATUSES:
        return False
    tx = load_transcript(channel_id, video_id)
    if tx is None:
        return False
    tx["srt_status"] = status
    save_transcript(channel_id, tx)
    return True


def is_srt_approved(channel_id: str, video_id: str) -> bool:
    return get_srt_status(channel_id, video_id) == SRT_APPROVED


# ── Clean transcript txt storage ──────────────────────────────────────────────

def clean_txt_path(channel_id: str, video_id: str) -> Path:
    return config.TRANSCRIPTS_DIR / channel_id / f"{video_id}.clean_en.txt"


def clean_txt_exists(channel_id: str, video_id: str) -> bool:
    return clean_txt_path(channel_id, video_id).exists()


def load_clean_txt(channel_id: str, video_id: str) -> str | None:
    p = clean_txt_path(channel_id, video_id)
    return p.read_text(encoding="utf-8") if p.exists() else None


# ── Video metadata ────────────────────────────────────────────────────────────

def save_channel_metadata(channel_id: str, videos: list[dict]) -> Path:
    path = config.METADATA_DIR / channel_id / "videos.json"
    existing_map: dict[str, dict] = {}
    if path.exists():
        for v in _read_json(path):
            existing_map[v["video_id"]] = v
    for v in videos:
        vid_id = v["video_id"]
        if vid_id in existing_map:
            existing_map[vid_id].update(v)
        else:
            existing_map[vid_id] = v
    _write_json(path, list(existing_map.values()))
    return path


def load_channel_metadata(channel_id: str) -> list[dict]:
    path = config.METADATA_DIR / channel_id / "videos.json"
    return _read_json(path) if path.exists() else []


def list_all_channel_ids() -> list[str]:
    if not config.METADATA_DIR.exists():
        return []
    return [d.name for d in config.METADATA_DIR.iterdir() if d.is_dir()]


# ── Global index ──────────────────────────────────────────────────────────────

def _index_path() -> Path:
    return config.METADATA_DIR / "index.json"


def load_index() -> dict:
    p = _index_path()
    return _read_json(p) if p.exists() else {"videos": [], "updated_at": ""}


def update_index(new_videos: list[dict], transcripts_status: dict[str, str]) -> None:
    index    = load_index()
    existing = {v["video_id"]: v for v in index["videos"]}
    for v in new_videos:
        vid   = v["video_id"]
        entry = existing.get(vid, dict(v))
        entry.update(v)
        entry["transcript_status"] = transcripts_status.get(vid, STATUS_NEVER_TRIED)
        entry["has_transcript"]    = transcripts_status.get(vid) == STATUS_AVAILABLE
        existing[vid] = entry
    index["videos"]     = list(existing.values())
    index["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(_index_path(), index)


# ── Backups ───────────────────────────────────────────────────────────────────

def backup_index() -> Path:
    src = _index_path()
    if not src.exists():
        return src
    ts  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = config.BACKUPS_DIR / f"index_{ts}.json"
    shutil.copy2(src, dst)
    return dst
