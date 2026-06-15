"""
process.py — clean and enrich a raw Transcript.

Cleaning steps:
  • Strip music/sound-effect annotations like [Music], [Applause]
  • Collapse excessive whitespace
  • Remove duplicate consecutive segments (common in auto-gen captions)

Enrichment:
  • Word count
  • Estimated read time (200 wpm average)
  • Paragraph chunking (useful for downstream LLM calls)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetch_transcript import Transcript

_ANNOTATION = re.compile(r"\[.*?\]|\(.*?\)")
_WHITESPACE  = re.compile(r"\s+")
_FILLER      = re.compile(r"\b(um+|uh+|er+|ah+|hmm+|like,?\s+)\b", re.IGNORECASE)


@dataclass
class ProcessedTranscript:
    video_id: str
    language: str
    is_generated: bool
    clean_text: str
    word_count: int
    read_time_minutes: float
    paragraphs: list[str] = field(default_factory=list)
    segments: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "language": self.language,
            "is_generated": self.is_generated,
            "clean_text": self.clean_text,
            "word_count": self.word_count,
            "read_time_minutes": self.read_time_minutes,
            "paragraphs": self.paragraphs,
            "segments": self.segments,
        }


def _clean_segment_text(text: str) -> str:
    text = _ANNOTATION.sub("", text)
    text = _FILLER.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def _deduplicate(segments: list) -> list:
    out, prev = [], None
    for seg in segments:
        if seg["text"] != prev:
            out.append(seg)
            prev = seg["text"]
    return out


def _make_paragraphs(text: str, words_per_chunk: int = 250) -> list[str]:
    words = text.split()
    return [
        " ".join(words[i : i + words_per_chunk])
        for i in range(0, len(words), words_per_chunk)
        if words[i : i + words_per_chunk]
    ]


def process_transcript(transcript: "Transcript") -> ProcessedTranscript:
    cleaned_segs = []
    for seg in transcript.segments:
        clean = _clean_segment_text(seg.text)
        if clean:
            cleaned_segs.append({"text": clean, "start": seg.start, "duration": seg.duration})

    cleaned_segs = _deduplicate(cleaned_segs)
    clean_text = " ".join(s["text"] for s in cleaned_segs)

    if clean_text:
        clean_text = clean_text[0].upper() + clean_text[1:]
        if clean_text[-1] not in ".!?":
            clean_text += "."

    word_count = len(clean_text.split())

    return ProcessedTranscript(
        video_id=transcript.video_id,
        language=transcript.language,
        is_generated=transcript.is_generated,
        clean_text=clean_text,
        word_count=word_count,
        read_time_minutes=round(word_count / 200, 1),
        paragraphs=_make_paragraphs(clean_text),
        segments=cleaned_segs,
    )
