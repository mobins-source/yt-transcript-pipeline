# MCC Tucson — Full Project Summary & Architectural Decisions

*Last updated: June 2026*

---

## Overview

Two interconnected projects built for the Muslim Community Center of Tucson (@mcctucson):

1. **YT Transcript Pipeline** — automated backend that fetches, cleans, enriches, and stores YouTube lecture transcripts
2. **Jumaa Khutba Archive** (`mcc-khutba`) — public-facing Next.js website serving Friday sermons from the pipeline data

The channel publishes Arabic/English bilingual Islamic lectures streamed live at prayer times (Fajr, Zuhr, Isha) and Friday Jumaa Khutbas. As of June 2026, the channel has **715 total videos** spanning ~8 months of history.

---

## Project 1: YT Transcript Pipeline

### Repository Layout

```
yt-transcript-pipeline/
  pipeline/
    config.py             Settings (reads .env)
    fetch_channel.py      YouTube Data API v3 → all videos + duration + stream time
    fetch_transcript.py   youtube-transcript-api v1.x with cookie auth + retry
    process.py            Clean + chunk transcript text
    store.py              JSON storage + SRT/status helpers
    enrich.py             Time fields + Claude AI enrichment + index rebuild
    clean_captions.py     Arabic detection + SRT + clean TXT generation
    overrides.py          CSV override export/diff/apply CLI
    server.py             FastAPI local server (overrides + SRT status + SRT editing)
    run.py                CLI orchestrator with batch strategy

  frontend/               React + Vite (admin review tool)
    src/
      App.jsx, app.css
      components/
        VideoList.jsx          sidebar video list with status badges
        TranscriptViewer.jsx   split view + SRT edit + review buttons
        EditPanel.jsx          metadata override form
        Dashboard.jsx          pipeline status overview
        FilterPanel.jsx
        SearchBar.jsx
      hooks/
        useTranscripts.js      reads index.json, exposes allVideos + filtered videos
        useOverrides.js        reads/writes overrides via server.py
        useSrtStatus.js        loads SRT, handles status updates + caption editing

  github-workflows/
    pipeline.yml          GitHub Actions (runs twice daily)

  data/                   shared by all projects
    transcripts/{channel_id}/{video_id}.json
    transcripts/{channel_id}/{video_id}.clean_en.srt
    transcripts/{channel_id}/{video_id}.clean_en.txt
    metadata/{channel_id}/videos.json
    metadata/index.json         ← single source of truth for all frontends
    overrides.csv
    cookies.txt                 ← browser cookies for YouTube auth
    cron.log                    ← nightly cron job output
    backups/
```

---

### Data Flow

```
YouTube Data API v3 (playlistItems + videos endpoints)
  → fetch_channel.py
    → all videos paginated (50/page)
    → duration_seconds from contentDetails.duration (ISO 8601 → seconds)
    → actual_at from liveStreamingDetails.actualStartTime (live stream start)
    → one batch API call per 50 videos — no yt-dlp needed

youtube-transcript-api v1.x (with browser cookie auth)
  → fetch_transcript.py
    → session injected via http_client=requests.Session()
    → cookies loaded from data/cookies.txt (Netscape format)
    → IP block retry: 3 internal retries × 180s pause, then 3 batch-level retries × 5min pause
    → permanent failures (TranscriptsDisabled, VideoUnplayable) marked and skipped

process.py → store.py → {video_id}.json

enrich.py
  → time fields computed from actual_at in Tucson/Phoenix time (UTC-7, no DST)
  → Claude Haiku AI: summary, suggested_title, content_type, hadith_book, hadith_chapter, topic_tags
  → _rebuild_index() writes metadata/index.json

clean_captions.py
  → two-tier Arabic detection (strong markers + weak markers + English context)
  → [Arabic recitation] blocks (contiguous Arabic merged)
  → [Silence] markers (gaps ≥ 12 seconds)
  → {video_id}.clean_en.srt (timestamped)
  → {video_id}.clean_en.txt (readable paragraphs)

Frontend (React + Vite, local only)
  → reads index.json + transcript JSONs + SRT/TXT (static files)
  → server.py (FastAPI :8000) for write operations only
```

---

### Architectural Decisions

#### Storage: Static JSON Files (no database)
All data lives in `data/` as JSON files. The frontend reads them statically.
- **Why:** Zero infrastructure cost, Git history = versioning, no database to manage
- **Tradeoff:** No server-side full-text search (deferred to Supabase in future)
- **Key file:** `metadata/index.json` — merged view of all video metadata + enrichment, read by all frontends

#### Video Metadata Fetch: YouTube Data API v3
Two API calls per run:
1. `playlistItems` — paginated list of all videos (uploads playlist: channel_id with UC→UU)
2. `videos?part=contentDetails,liveStreamingDetails` — duration + actual stream start time (batched 50/call)
- **Why not yt-dlp:** Unreliable for this channel (returned 0 results), API is faster and more stable
- **Cost:** Free tier, 10,000 quota units/day, entire channel history costs ~15 units

#### Transcript Fetch: Cookie Authentication
Browser cookies injected via `YouTubeTranscriptApi(http_client=requests.Session())`.
- **Why:** YouTube's transcript API rate-limits anonymous IPs aggressively. Browser session cookies bypass this.
- **Cookie format:** Netscape cookies.txt, exported from Chrome via "Get cookies.txt LOCALLY" extension
- **Refresh:** Cookies expire every few months — re-export when IP blocks reappear
- **Fallback:** If IP blocked mid-batch, retries up to 3× with 5-min pauses, then marks video as `unavailable` and moves on (never hangs forever)

#### Batch Strategy: Rate Limiting Protection
```
BATCH_SIZE=5        videos per batch
BATCH_PAUSE=300     5 min pause between batches (with cookies, could use 10/60)
MAX_VIDEOS_PER_CHANNEL=20  per scheduled run (0 = all, used for backfill)
```
- **Why:** Prevents session exhaustion even with cookies. Cookies bypass IP blocks but not session rate limits.
- **Backfill:** 715 videos ÷ ~20 videos/night = ~35 nights to complete historical backfill
- **Ongoing:** Once backfill complete, daily runs of 20 keep up with new content

#### Scheduled Runs: Mac Cron + GitHub Actions
- **Mac cron** (`0 10 * * *`) — runs nightly for historical backfill. Uses full Python path (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`) and absolute log path.
- **GitHub Actions** (`pipeline.yml`) — twice daily for ongoing sync after backfill completes. Commits updated data back to repo, triggers auto-deploy on Vercel.

#### AI Enrichment: Claude Haiku
Model: `claude-haiku-4-5-20251001`
Fields: `summary`, `suggested_title`, `content_type`, `hadith_book`, `hadith_chapter`, `topic_tags[]`
- **Why Haiku:** Fast (< 1s/video), cheap, accurate enough for Islamic content categorization
- **Hadith books recognized:** Sahih Bukhari, Sahih Muslim, Sunan Abu Dawud, Jami al-Tirmidhi, Sunan al-Nasai, Sunan Ibn Majah, Riyadul Saliheen, Al-Wajeez

#### Time Categorization: Tucson/Phoenix (UTC-7, no DST)
Source: `actual_at` from YouTube API (live stream start time, not upload time).
```
Fajr:  04:00 – 11:59  → "Fajr"
Zuhr:  12:00 – 16:59  → "Zuhr"
Isha:  17:00 – 03:59  → "Isha"

Friday + Zuhr → time_slot = "Jumaa Khutba"
Otherwise     → time_slot = "{DayOfWeek}-{TimeOfDay}"
```

#### Arabic Caption Cleaning: Two-Tier Rule-Based Detection
**Problem:** YouTube hallucinates English words during Arabic speech ("I shall", "A shadow", "Come back" = phonetic Arabic).
**Decision:** Rule-based (no ML, no Whisper) — fast, transparent, tunable.

| Tier | Examples | Rule |
|---|---|---|
| Strong | `allahu`, `ilaha`, `illallah`, `allahumma`, `rabbana` | Always Arabic — flag regardless of context |
| Weak | `muhammad`, `rasulullah`, `wa`, `la`, `inshallah`, `ameen` | Arabic only if NO English context words present |

**Tuned with channel owner over several iterations:**
- Kept in English (removed from markers): `alhamdulillah`, `bismillah`, `sallallahu`, `subhanahu wa ta'ala`, `allah`, `mashallah`, `jazakallah`, `alayhissalam`, all prophet names, all angel names
- `[Silence]` inserted for gaps ≥ 12 seconds
- Contiguous Arabic segments merged into single `[Arabic recitation]` block

#### SRT Review Workflow: Three-Status Lifecycle
| Status | Meaning | Pipeline behaviour |
|---|---|---|
| `pending` | Generated, not yet reviewed | Skip by default, regenerate on `--force` |
| `approved` | Human-verified correct | **Never overwritten** — permanent protection |
| `needs_fix` | Detection was wrong | Auto-regenerated on next `--captions-only` run |

Review UI: split side-by-side view (original left, clean right), synced scroll by percentage, text-only inline editing, Approve/Needs Fix/Reset buttons → `PATCH /api/srt-status/{video_id}`.

#### Override System: CSV Staging Area
Manual metadata corrections staged in `data/overrides.csv`, applied separately.
- Frontend writes via `POST /api/overrides` (server.py) → "override pending" badge in UI
- CLI `python3 overrides.py apply` commits to JSONs + removes synced rows from CSV → badge clears
- `window.focus` event in `useOverrides.js` re-fetches CSV so badge clears automatically when switching back from terminal

#### --max 0 Bug Fix
`--max 0` (fetch all) previously fell back to `.env` value because `0 or 20 = 20`.
Fixed by using `None` as the CLI default and explicitly checking: `if max_videos is None → use .env, else use max_videos directly`.

---

### Frontend: Admin Review Tool (React + Vite)

Key features:
- **Video list** — SRT status dots (🟡 pending / 🟢 approved / 🔴 needs_fix), override badges
- **Transcript viewer** — 4 tabs: Summary, Full transcript, Timestamped, Clean captions
- **Split captions view** — original (left) vs clean (right), synced scroll, text-only inline edit
- **Edit panel** — metadata override form, saves to CSV via server.py
- **Dashboard** — `📊` button shows pipeline stats: SRT breakdown, content types, books, attention list
- **Server online/offline badge** — shows whether server.py is running
- **Stream time + duration** — shown in viewer header from `post_time` and `duration_seconds`
- **`refreshIndex`** — called after every status update/save so UI reflects changes immediately without page reload

---

### Data Fields in index.json

```
video_id, title, channel_id, channel_name, url
published_at        YouTube upload time (ISO UTC)
actual_at           Actual live stream start time (ISO UTC)
duration_seconds    Video length in seconds
post_time           Local Tucson datetime (YYYY-MM-DDTHH:MM:SS, no timezone)
post_date           YYYY-MM-DD in Tucson time
month, month_num, year, month_year
time_of_day         Fajr | Zuhr | Isha
day_of_week         Monday … Sunday
time_slot           Jumaa Khutba | {Day}-{TimeOfDay}
content_type        Quran | Hadith | General | Announcement | Mixed
hadith_book         Book name or null
hadith_chapter      Chapter/section or null
topic_tags          Array of lowercase strings (max 8)
suggested_title     AI-generated descriptive title
summary             AI-generated 2-3 paragraph summary
has_transcript      boolean
transcript_status   available | unavailable | never_tried
has_clean_srt       boolean
has_clean_txt       boolean
srt_status          pending | approved | needs_fix
manually_reviewed   boolean
```

---

### Pipeline Commands Reference

```bash
cd pipeline

# Full run (fetch + enrich + clean captions) — uses .env defaults
python3 run.py --channel @mcctucson

# Historical backfill — fetch ALL 715 videos
python3 run.py --channel @mcctucson --max 0 --batch-size 5 --batch-pause 300

# Fetch only
python3 run.py --channel @mcctucson --no-enrich --no-captions

# Enrich only
python3 run.py --enrich-only
python3 run.py --enrich-only --force    # re-enrich everything

# Captions only
python3 run.py --captions-only
python3 run.py --captions-only --force  # regenerate pending+needs_fix (never approved)

# Override workflow
python3 overrides.py export             # generate CSV
python3 overrides.py diff               # preview changes
python3 overrides.py apply              # commit to JSONs, clear synced rows

# Rebuild index
python3 run.py --export-index
```

---

## Project 2: Jumaa Khutba Archive (mcc-khutba)

### Location
`/Users/mobin/Documents/mcc-khutba/`

### Stack
- **Next.js 14** with App Router
- **Tailwind CSS** with warm cream color palette
- **Google Fonts:** Playfair Display (headings) + Lora (reading) + Inter (UI)
- Data read at build time via `fs.readFileSync` from `../yt-transcript-pipeline/data/`

### Layout
```
mcc-khutba/
  app/
    layout.jsx          header (م logo mark, sticky), footer, font imports
    page.jsx            home: hero + KhutbaGrid
    globals.css         warm cream palette, reading typography
    not-found.jsx
    khutba/[id]/
      page.jsx          individual khutba: header, summary, transcript
  components/
    KhutbaGrid.jsx      client: search + year/topic filters + card grid
    KhutbaCard.jsx      white card, shadow, amber hover accent, tag pills
    Transcript.jsx      client: Clean reading / Timestamped toggle
  lib/
    data.js             server-side: getAllKhutbas, getKhutba, getCleanTranscript, etc.
  next.config.mjs       outputFileTracingRoot for cross-directory data access
```

### Architectural Decisions

#### Data Access: Read from Shared Pipeline Folder
`lib/data.js` reads directly from `../yt-transcript-pipeline/data/` at build time.
- **Why:** No data duplication. Pipeline enriches data → Next.js build picks it up automatically.
- **Data filter:** `time_slot === "Jumaa Khutba" && has_transcript === true`
- **Deploy:** `npm run build` rebuilds static pages from latest data; on Vercel, push triggers rebuild

#### Design: Warm Cream for Reader-Friendly UX
Background `#FEFCF8` (warm cream) instead of dark backgrounds.
- Playfair Display headings — elegant, authoritative for Islamic content
- Lora body text — optimized for long-form reading (1.9 line height)
- Amber `#C8873A` as primary accent — warm Islamic gold feel
- Arabic recitation shown in purple `#6D3BA0` italic pill
- Silence shown in grey italic

#### Static Generation
All pages statically generated at build time via `generateStaticParams`.
- Home: server component, filters Jumaa Khutbas server-side
- KhutbaGrid: client component for live search/filter without page reload
- Individual khutba: server component reads transcript + clean text at build time

### Running

```bash
cd /Users/mobin/Documents/mcc-khutba
npm install   # first time only
npm run dev   # → http://localhost:3000
npm run build # build static site
```

---

## Current Status (June 2026)

| Item | Status |
|---|---|
| Pipeline code | ✅ Complete |
| YouTube API fetch | ✅ Working (715 videos discovered) |
| Cookie auth | ✅ Working (IP blocks bypassed) |
| Transcript fetch | ✅ 62/715 fetched, backfill ~35% complete |
| AI enrichment | ✅ All fetched videos enriched |
| Arabic caption cleaning | ✅ SRTs generated, markers tuned |
| SRT review UI | ✅ Split view + inline edit + approve workflow |
| Override system | ✅ CSV + frontend edit + auto-clear on apply |
| Pipeline dashboard | ✅ 📊 button in admin frontend |
| Historical backfill | 🔄 Running nightly via cron (~35 nights to complete) |
| Admin frontend | ✅ Running locally |
| Jumaa Khutba archive | ✅ Scaffolded, running locally |
| Vercel deployment | ⏳ Pending (after backfill completes) |
| GitHub Actions | ⏳ Pending push to GitHub |

---

## Long-Term Roadmap

| Phase | Project | Action |
|---|---|---|
| Now | Pipeline | Complete 715-video backfill (nightly cron, ~35 days) |
| Now | SRT review | Approve Jumaa Khutba SRTs first (highest public value) |
| Month 1 | Khutba archive | Deploy to Vercel + custom domain |
| Month 2 | Hadith study guide | New Next.js app, same data folder, grouped by book→chapter |
| Month 3+ | Search | Add Supabase full-text search across all transcripts |
| Ongoing | Pipeline | GitHub Actions twice-daily sync after backfill |

### Hadith Study Guide (next project, same data)
Filter: `content_type === "Hadith" || hadith_book !== null`
Structure: Hadith Book → Chapter → Lectures in chronological order
Al-Wajeez alone will have ~300+ lectures once backfill completes.
