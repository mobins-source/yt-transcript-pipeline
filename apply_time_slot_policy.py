#!/usr/bin/env python3
"""
apply_time_slot_policy.py — one-shot generator for time-slot metadata policy.

Policy (confirmed 2026-07):
  MCC channel, 2025+ only, based on actual stream time (MST = UTC-7):
    - Fajr window  04:15-07:00  -> content_type=Hadith, hadith_book=Al-Wajeez
    - Isha window  19:00-22:00  -> content_type=Hadith, hadith_book=Riyadul Saliheen
  Excluded (never touched):
    - Ramadan windows: 2025-03-01..2025-03-30, 2026-02-18..2026-03-20 (incl. Eid)
    - Friday 11:00-15:00 MST (Jumaa khutba)
    - Any title containing "Eid"
    - Videos without enrichment (no post_date = no usable transcript)

Writes rows into data/overrides.csv (merging with existing rows).
Then run:  python3 overrides.py diff   (preview)
           python3 overrides.py apply  (write to JSONs + rebuild index)
"""
import csv
import json
from datetime import datetime, timedelta, date
from pathlib import Path

REPO = Path(__file__).resolve().parent
INDEX = REPO / "data" / "metadata" / "index.json"
OVERRIDES = REPO / "data" / "overrides.csv"

MCC = "UCt-XeQTVRSETC9DceeC6nMw"
RAMADAN = [(date(2025, 3, 1), date(2025, 3, 30)),
           (date(2026, 2, 18), date(2026, 3, 20))]

EXPORT_FIELDS = ["video_id", "channel_id", "title", "suggested_title", "catchy_title",
                 "content_type", "hadith_book", "hadith_chapter", "topic_tags",
                 "time_of_day", "day_of_week", "time_slot", "post_date", "reviewed", "notes"]


def mst(v):
    at = v.get("actual_at") or v.get("published_at") or ""
    if not at:
        return None
    try:
        return datetime.fromisoformat(at.replace("Z", "+00:00")) - timedelta(hours=7)
    except ValueError:
        return None


def main():
    videos = json.loads(INDEX.read_text())["videos"]

    fajr, isha = {}, {}
    for v in videos:
        if v.get("channel_id") != MCC:
            continue
        m = mst(v)
        if not m or m.year < 2025:
            continue
        if any(a <= m.date() <= b for a, b in RAMADAN):
            continue
        t = m.strftime("%H:%M")
        if m.weekday() == 4 and "11:00" <= t <= "15:00":
            continue  # Jumaa khutba
        if not (("04:15" <= t < "07:00") or ("19:00" <= t <= "22:00")):
            continue
        if "eid" in (v.get("title", "") or "").lower():
            continue  # Eid prayer/khutbah
        if not v.get("post_date"):
            continue  # no enrichment = no usable transcript
        (fajr if "04:15" <= t < "07:00" else isha)[v["video_id"]] = v

    def policy(vid):
        return "Al-Wajeez" if vid in fajr else ("Riyadul Saliheen" if vid in isha else None)

    existing = list(csv.DictReader(open(OVERRIDES))) if OVERRIDES.exists() else []
    seen, rows, updated = set(), [], 0
    for row in existing:
        vid = row.get("video_id", "").strip()
        seen.add(vid)
        book = policy(vid)
        if book:
            if row.get("content_type") != "Hadith" or row.get("hadith_book") != book:
                updated += 1
            row["content_type"], row["hadith_book"] = "Hadith", book
            row["notes"] = (row.get("notes", "") or "").strip() or "time-slot policy"
        rows.append({f: row.get(f, "") for f in EXPORT_FIELDS})

    added = synced = 0
    for vid, v in list(fajr.items()) + list(isha.items()):
        if vid in seen:
            continue
        book = policy(vid)
        if v.get("content_type") == "Hadith" and (v.get("hadith_book") or "") == book:
            synced += 1
            continue
        rows.append({
            "video_id": vid, "channel_id": MCC, "title": v.get("title", ""),
            "suggested_title": "", "catchy_title": "",
            "content_type": "Hadith", "hadith_book": book,
            "hadith_chapter": "", "topic_tags": "", "time_of_day": "",
            "day_of_week": "", "time_slot": "", "post_date": v.get("post_date", ""),
            "reviewed": "",
            "notes": "time-slot policy (Fajr=Al-Wajeez / Isha=Riyadul Saliheen)",
        })
        added += 1

    rows.sort(key=lambda r: r.get("post_date", "") or "", reverse=True)
    with open(OVERRIDES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"Fajr {len(fajr)} + Isha {len(isha)} in scope")
    print(f"Existing rows preserved: {len(existing)} (policy applied to {updated})")
    print(f"New rows: {added} | already correct (skipped): {synced}")
    print(f"Total rows written: {len(rows)} -> {OVERRIDES}")
    print("\nNext:  cd pipeline && python3 overrides.py diff   # preview")
    print("       cd pipeline && python3 overrides.py apply  # apply + rebuild index")


if __name__ == "__main__":
    main()
