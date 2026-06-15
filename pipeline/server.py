"""
server.py — Local API server for the overrides + SRT status + SRT editing system.

Runs on http://localhost:8000. The Vite dev server proxies /api → here.

Usage:
  cd pipeline
  python3 server.py

Endpoints:
  GET    /api/status                      → health check + counts
  GET    /api/overrides                   → all override rows
  GET    /api/overrides/{video_id}        → single override row
  POST   /api/overrides                   → upsert override row
  DELETE /api/overrides/{video_id}        → remove override row
  GET    /api/srt-status/{video_id}       → get SRT status for a video
  PATCH  /api/srt-status/{video_id}       → update SRT review status
  PATCH  /api/srt/{video_id}              → save edited SRT segments (text-only)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import List

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("Missing dependencies. Run: pip3 install fastapi uvicorn pydantic")
    raise

sys.path.insert(0, str(Path(__file__).parent))
import config
import store
from enrich import _rebuild_index
from overrides import OVERRIDES_PATH, EXPORT_FIELDS, EDITABLE_FIELDS
from clean_captions import (
    generate_clean_transcript_text,
    clean_transcript_txt_path,
)

app = FastAPI(title="YT Transcript API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _read_csv() -> dict[str, dict]:
    if not OVERRIDES_PATH.exists():
        return {}
    with open(OVERRIDES_PATH, newline="", encoding="utf-8") as f:
        return {row["video_id"]: row for row in csv.DictReader(f)}


def _write_csv(rows: dict[str, dict]) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OVERRIDES_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        sorted_rows = sorted(rows.values(), key=lambda r: r.get("post_date", ""), reverse=True)
        writer.writerows(sorted_rows)


# ── SRT helpers ───────────────────────────────────────────────────────────────

def _rebuild_srt_from_segments(segments: list[dict]) -> str:
    """Reconstruct SRT file content from a list of {index, start, end, text} dicts."""
    lines = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        lines.append(f"{seg['index']}\n{seg['start']} --> {seg['end']}\n{text}\n")
    return "\n".join(lines)


def _regenerate_txt_from_srt(channel_id: str, video_id: str) -> None:
    """Re-generate the clean_en.txt from the current clean_en.srt content."""
    srt_text = store.load_srt(channel_id, video_id)
    if not srt_text:
        return

    # Parse SRT into entries matching the format generate_clean_transcript_text expects
    entries = []
    for block in srt_text.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) < 3:
            continue
        text = "\n".join(lines[2:]).strip()
        entries.append({
            "text":       text,
            "is_arabic":  text == "[Arabic recitation]",
            "is_silence": text == "[Silence]",
        })

    txt_content = generate_clean_transcript_text(entries)
    txt_path    = clean_transcript_txt_path(channel_id, video_id)
    txt_path.write_text(txt_content, encoding="utf-8")


# ── Pydantic models ───────────────────────────────────────────────────────────

class OverrideRow(BaseModel):
    video_id:        str
    channel_id:      str
    title:           str = ""
    suggested_title: str = ""
    content_type:    str = ""
    hadith_book:     str = ""
    hadith_chapter:  str = ""
    topic_tags:      str = ""
    time_of_day:     str = ""
    day_of_week:     str = ""
    time_slot:       str = ""
    post_date:       str = ""
    reviewed:        str = ""
    notes:           str = ""


class SrtStatusUpdate(BaseModel):
    channel_id: str
    status: str


class SrtSegment(BaseModel):
    index: int
    start: str   # "00:00:04,000"
    end:   str   # "00:00:08,000"
    text:  str


class SrtEditBody(BaseModel):
    channel_id: str
    segments:   List[SrtSegment]


# ── Status route ──────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    rows     = _read_csv()
    reviewed = sum(1 for r in rows.values() if r.get("reviewed", "").lower() == "yes")
    srt_counts = {store.SRT_PENDING: 0, store.SRT_APPROVED: 0, store.SRT_NEEDS_FIX: 0}
    for channel_id in store.list_all_channel_ids():
        for meta in store.load_channel_metadata(channel_id):
            s = store.get_srt_status(channel_id, meta["video_id"])
            if s in srt_counts:
                srt_counts[s] += 1
    return {
        "status":             "ok",
        "overrides_total":    len(rows),
        "overrides_reviewed": reviewed,
        "srt_pending":        srt_counts[store.SRT_PENDING],
        "srt_approved":       srt_counts[store.SRT_APPROVED],
        "srt_needs_fix":      srt_counts[store.SRT_NEEDS_FIX],
    }


# ── Override routes ───────────────────────────────────────────────────────────

@app.get("/api/overrides")
def get_all_overrides():
    return list(_read_csv().values())


@app.get("/api/overrides/{video_id}")
def get_override(video_id: str):
    rows = _read_csv()
    if video_id not in rows:
        raise HTTPException(status_code=404, detail="No override for this video")
    return rows[video_id]


@app.post("/api/overrides")
def upsert_override(row: OverrideRow):
    if not row.video_id:
        raise HTTPException(status_code=400, detail="video_id is required")
    rows     = _read_csv()
    existing = rows.get(row.video_id, {})
    updated  = dict(existing)
    updated["video_id"]   = row.video_id
    updated["channel_id"] = row.channel_id or existing.get("channel_id", "")
    updated["title"]      = row.title      or existing.get("title", "")
    updated["post_date"]  = row.post_date  or existing.get("post_date", "")
    for field in EDITABLE_FIELDS:
        new_val = getattr(row, field, "").strip()
        if new_val:
            updated[field] = new_val
    rows[row.video_id] = updated
    _write_csv(rows)
    return {"ok": True, "video_id": row.video_id}


@app.delete("/api/overrides/{video_id}")
def delete_override(video_id: str):
    rows = _read_csv()
    if video_id not in rows:
        raise HTTPException(status_code=404, detail="No override for this video")
    del rows[video_id]
    _write_csv(rows)
    return {"ok": True, "video_id": video_id}


# ── SRT status routes ─────────────────────────────────────────────────────────

@app.get("/api/srt-status/{video_id}")
def get_srt_status(video_id: str, channel_id: str):
    srt_status = store.get_srt_status(channel_id, video_id)
    if srt_status is None:
        raise HTTPException(status_code=404, detail="No SRT for this video")
    return {"video_id": video_id, "channel_id": channel_id,
            "srt_status": srt_status, "srt_exists": store.srt_exists(channel_id, video_id)}


@app.patch("/api/srt-status/{video_id}")
def update_srt_status(video_id: str, body: SrtStatusUpdate):
    if body.status not in store.SRT_STATUSES:
        raise HTTPException(status_code=400,
            detail=f"Invalid status. Must be: {', '.join(store.SRT_STATUSES)}")
    if not store.srt_exists(body.channel_id, video_id):
        raise HTTPException(status_code=404, detail="No SRT file found for this video")
    ok = store.save_srt_status(body.channel_id, video_id, body.status)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save status")
    _rebuild_index()
    return {"ok": True, "video_id": video_id, "srt_status": body.status}


# ── SRT edit route ────────────────────────────────────────────────────────────

@app.patch("/api/srt/{video_id}")
def edit_srt(video_id: str, body: SrtEditBody):
    """
    Save manually edited SRT segments (text-only — timestamps are preserved).

    Accepts the full list of segments after editing. Reconstructs the SRT file,
    regenerates the clean_en.txt, and keeps srt_status as 'pending' so the
    user still needs to explicitly approve.

    Approved SRTs cannot be edited — mark as needs_fix first.
    """
    if store.is_srt_approved(body.channel_id, video_id):
        raise HTTPException(
            status_code=403,
            detail="SRT is approved — mark as 'needs_fix' before editing"
        )

    if not store.srt_exists(body.channel_id, video_id):
        raise HTTPException(status_code=404, detail="No SRT file found for this video")

    # Reconstruct and write the SRT file
    segments_dicts = [s.model_dump() for s in body.segments]
    srt_content    = _rebuild_srt_from_segments(segments_dicts)
    srt_file       = store.srt_path(body.channel_id, video_id)
    srt_file.write_text(srt_content, encoding="utf-8")

    # Regenerate the clean_en.txt from the updated SRT
    _regenerate_txt_from_srt(body.channel_id, video_id)

    # Keep status as pending — user must still approve
    store.save_srt_status(body.channel_id, video_id, store.SRT_PENDING)

    return {
        "ok":            True,
        "video_id":      video_id,
        "segments_saved": len(body.segments),
        "srt_status":    store.SRT_PENDING,
    }


if __name__ == "__main__":
    print("Starting YT Transcript API server…")
    print(f"Overrides file: {OVERRIDES_PATH}")
    print("API:  http://localhost:8000")
    print("Docs: http://localhost:8000/docs\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
