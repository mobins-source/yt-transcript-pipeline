"""
clean_captions.py — Generate a clean English SRT and transcript from stored transcripts.

Problem:
  YouTube auto-captions hallucinate English text during Arabic speech.
  This module detects Arabic speech segments using text pattern analysis
  and replaces them with [Arabic recitation] markers.
  Gaps of 12+ seconds between segments are marked as [Silence].

Outputs:
  data/transcripts/{channel_id}/{video_id}.clean_en.srt   ← timestamped SRT
  data/transcripts/{channel_id}/{video_id}.clean_en.txt   ← clean readable transcript

SRT status lifecycle:
  pending   → just generated, needs review
  approved  → reviewed and correct — NEVER overwritten by pipeline
  needs_fix → reviewed, Arabic detection was wrong — regenerated on next run
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console

import config
import store

console = Console()

SILENCE_THRESHOLD_SECONDS = 12.0

STRONG_MARKERS = {
    "allahu", "ilaha", "illallah",
    "allahumma", "rabbanaa", "rabbana",
}

# NOTE: "inshallah" / "insha" intentionally NOT included here.
# Kept in English per channel owner request (June 2026) — same treatment
# as alhamdulillah, bismillah, mashallah, etc. See ENGLISH_CONTEXT note below.
WEAK_MARKERS = {
    "muhammad", "rasulullah",
    "wa", "la",
    "ameen", "aameen",
}

ENGLISH_CONTEXT = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for",
    "and", "or", "but", "with", "from", "by", "about", "into",
    "is", "are", "was", "were", "be", "been", "have", "has", "had",
    "do", "does", "did", "will", "would", "can", "could", "should",
    "said", "says", "tell", "told", "ask", "asked", "know", "knew",
    "come", "came", "go", "went", "make", "made",
    "he", "she", "we", "they", "you", "it", "his", "her", "our",
    "their", "its", "my", "your", "who", "which", "that", "this",
    "prophet", "messenger", "peace", "upon", "him", "blessing",
    "blessings", "companions", "believers", "muslims", "islam",
    "prayer", "worship", "faith", "angel", "allah", "subhanahu",
    "one", "two", "three", "first", "second", "when", "then",
    "after", "before", "so", "if", "because",
}

# Phrases that are common Islamic expressions kept in the English transcript
# (not flagged as Arabic) regardless of surrounding context.
# inshallah/insha added June 2026 per channel owner request.
ENGLISH_KEPT_PHRASES = {
    "inshallah", "insha", "alhamdulillah", "bismillah",
    "mashallah", "subhanallah", "alhamdulilah",
}

_NOISE_WORDS = {
    ">>", "i", "oh", "real", "shall", "shadow",
    "back", "around", "yeah", "double", "done", "see",
}

_PUNCT = re.compile(r"[^\w\s']")


@dataclass
class Segment:
    index: int
    start: float
    duration: float
    text: str
    is_arabic: bool = False

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def clean_words(self) -> list[str]:
        return _PUNCT.sub("", self.text).lower().split()


def _is_anchor(seg: Segment) -> bool:
    words = seg.clean_words
    if ">>" in seg.text:
        return True
    if any(w in STRONG_MARKERS for w in words):
        return True
    if any(w in WEAK_MARKERS for w in words):
        if not any(w in ENGLISH_CONTEXT for w in words):
            return True
    return False


def _is_noise(seg: Segment, prev: Optional[Segment], next_: Optional[Segment]) -> bool:
    if seg.word_count > 5:
        return False
    words = set(seg.clean_words)
    if words and words.issubset(_NOISE_WORDS):
        return True
    gap_before = (seg.start - prev.end)  if prev  else 999
    gap_after  = (next_.start - seg.end) if next_ else 999
    if seg.word_count <= 3 and (gap_before > 3.0 or gap_after > 3.0):
        return True
    return False


def detect_arabic_segments(segments: list[Segment]) -> list[Segment]:
    n = len(segments)
    for seg in segments:
        if _is_anchor(seg):
            seg.is_arabic = True
    changed = True
    while changed:
        changed = False
        for i, seg in enumerate(segments):
            if seg.is_arabic:
                continue
            prev  = segments[i - 1] if i > 0     else None
            next_ = segments[i + 1] if i < n - 1 else None
            if (prev and prev.is_arabic or next_ and next_.is_arabic) \
                    and _is_noise(seg, prev, next_):
                seg.is_arabic = True
                changed = True
    return segments


def _format_srt_time(seconds: float) -> str:
    ms = int((seconds % 1) * 1000)
    s  = int(seconds) % 60
    m  = int(seconds) // 60 % 60
    h  = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _merge_arabic_blocks(segments: list[Segment]) -> list[dict]:
    if not segments:
        return []
    output = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if not seg.is_arabic:
            output.append({"start": seg.start, "end": seg.end,
                           "text": seg.text, "is_arabic": False, "is_silence": False})
            i += 1
        else:
            block_start, block_end = seg.start, seg.end
            j = i + 1
            while j < len(segments) and segments[j].is_arabic:
                block_end = segments[j].end
                j += 1
            output.append({"start": block_start, "end": block_end,
                           "text": "[Arabic recitation]", "is_arabic": True, "is_silence": False})
            i = j
    return output


def _insert_silence_markers(entries: list[dict]) -> list[dict]:
    if len(entries) < 2:
        return entries
    result = []
    for i, entry in enumerate(entries):
        result.append(entry)
        if i < len(entries) - 1:
            gap = entries[i + 1]["start"] - entry["end"]
            if gap >= SILENCE_THRESHOLD_SECONDS:
                result.append({"start": entry["end"], "end": entries[i + 1]["start"],
                               "text": "[Silence]", "is_arabic": False, "is_silence": True})
    return result


def generate_srt(entries: list[dict]) -> str:
    lines = []
    idx   = 1
    for entry in entries:
        text = entry["text"].strip()
        if not text:
            continue
        lines.append(f"{idx}\n{_format_srt_time(entry['start'])} --> {_format_srt_time(entry['end'])}\n{text}\n")
        idx += 1
    return "\n".join(lines)


# ── Clean transcript (txt) ────────────────────────────────────────────────────

def generate_clean_transcript_text(entries: list[dict]) -> str:
    """
    Convert SRT entries into a clean readable transcript.

    - Consecutive English segments are joined into paragraphs (separated by sentence breaks)
    - [Arabic recitation] and [Silence] get their own paragraph with blank lines around them
    """
    paragraphs = []
    english_buffer: list[str] = []

    def flush_english():
        if english_buffer:
            text = " ".join(english_buffer).strip()
            # Capitalise first letter, ensure ends with punctuation
            if text:
                text = text[0].upper() + text[1:]
                if text[-1] not in ".!?":
                    text += "."
            paragraphs.append(text)
            english_buffer.clear()

    for entry in entries:
        text = entry["text"].strip()
        if not text:
            continue

        if entry.get("is_arabic") or entry.get("is_silence"):
            flush_english()
            paragraphs.append(text)
        else:
            english_buffer.append(text)

    flush_english()

    return "\n\n".join(paragraphs)


# ── File paths ────────────────────────────────────────────────────────────────

def clean_caption_srt_path(channel_id: str, video_id: str) -> Path:
    return config.TRANSCRIPTS_DIR / channel_id / f"{video_id}.clean_en.srt"


def clean_transcript_txt_path(channel_id: str, video_id: str) -> Path:
    return config.TRANSCRIPTS_DIR / channel_id / f"{video_id}.clean_en.txt"


def already_cleaned(channel_id: str, video_id: str) -> bool:
    return clean_caption_srt_path(channel_id, video_id).exists()


def should_generate(channel_id: str, video_id: str, force: bool = False) -> tuple[bool, str]:
    if store.is_srt_approved(channel_id, video_id):
        return False, "approved — protected"
    if not already_cleaned(channel_id, video_id):
        return True, "no SRT yet"
    if store.get_srt_status(channel_id, video_id) == store.SRT_NEEDS_FIX:
        return True, "needs_fix — regenerating"
    if force:
        return True, "forced"
    return False, "already pending — skipping"


# ── Main generation ───────────────────────────────────────────────────────────

def generate_clean_captions(
    channel_id: str,
    video_id: str,
    force: bool = False,
) -> Optional[Path]:
    """
    Load stored transcript, detect Arabic segments, write:
      - {video_id}.clean_en.srt  — timestamped SRT
      - {video_id}.clean_en.txt  — clean readable transcript

    Approved SRTs are never overwritten.
    Returns SRT path on success, None if skipped or failed.
    """
    ok, reason = should_generate(channel_id, video_id, force=force)
    if not ok:
        console.print(f"  [dim]{video_id}: {reason}[/dim]")
        return None

    tx = store.load_transcript(channel_id, video_id)
    if not tx:
        return None

    raw_segments = tx.get("segments", [])
    if not raw_segments:
        console.print(f"[yellow]⚠ No segments for {video_id}[/yellow]")
        return None

    segs = [
        Segment(index=i, start=s["start"], duration=s.get("duration", 0.0),
                text=s["text"].strip())
        for i, s in enumerate(raw_segments)
        if s.get("text", "").strip()
    ]
    if not segs:
        return None

    segs          = detect_arabic_segments(segs)
    arabic_count  = sum(1 for s in segs if s.is_arabic)
    entries       = _merge_arabic_blocks(segs)
    entries       = _insert_silence_markers(entries)
    silence_count = sum(1 for e in entries if e.get("is_silence"))

    console.print(
        f"  [dim]{video_id}: {len(segs)} segments — "
        f"{arabic_count} Arabic, {silence_count} silence gaps, "
        f"{len(segs) - arabic_count} English ({reason})[/dim]"
    )

    # Write SRT
    srt_path = clean_caption_srt_path(channel_id, video_id)
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text(generate_srt(entries), encoding="utf-8")

    # Write clean transcript txt
    txt_path = clean_transcript_txt_path(channel_id, video_id)
    txt_path.write_text(generate_clean_transcript_text(entries), encoding="utf-8")

    store.save_srt_status(channel_id, video_id, store.SRT_PENDING)
    return srt_path


def clean_captions_for_channel(channel_id: str, force: bool = False) -> tuple[int, int]:
    metas = store.load_channel_metadata(channel_id)
    generated = skipped = 0
    for meta in metas:
        vid_id = meta["video_id"]
        if not store.transcript_exists(channel_id, vid_id):
            skipped += 1
            continue
        path = generate_clean_captions(channel_id, vid_id, force=force)
        if path:
            generated += 1
        else:
            skipped += 1
    return generated, skipped


def clean_captions_all_channels(force: bool = False) -> None:
    if not config.METADATA_DIR.exists():
        return
    for ch_dir in config.METADATA_DIR.iterdir():
        if not ch_dir.is_dir():
            continue
        channel_id = ch_dir.name
        console.rule(f"[bold blue]Clean captions: {channel_id}[/bold blue]")
        generated, skipped = clean_captions_for_channel(channel_id, force=force)
        console.print(
            f"[green]✓[/green] {channel_id} — "
            f"[green]{generated} generated[/green], "
            f"[yellow]{skipped} skipped[/yellow]"
        )
