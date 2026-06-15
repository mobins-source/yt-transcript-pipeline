# YT Transcript Pipeline

Fetch, process, and browse transcripts from YouTube channels — no video download required.

```
yt-transcript-pipeline/
├── pipeline/
│   ├── config.py            # Settings (reads .env)
│   ├── fetch_channel.py     # Get video list via yt-dlp
│   ├── fetch_transcript.py  # Download captions
│   ├── process.py           # Clean + enrich text
│   ├── store.py             # JSON storage layer
│   ├── run.py               # CLI entry point
│   ├── requirements.txt
│   └── .env.example
├── frontend/                # React + Vite browser UI
│   ├── src/
│   │   ├── components/      # SearchBar, VideoList, TranscriptViewer
│   │   ├── hooks/           # useTranscripts
│   │   ├── App.jsx
│   │   └── app.css
│   ├── index.html
│   └── package.json
├── github-workflows/
│   └── pipeline.yml         # Scheduled GitHub Actions run
└── data/
    ├── transcripts/{channel_id}/{video_id}.json
    ├── metadata/{channel_id}/videos.json
    ├── metadata/index.json  ← frontend reads this
    └── backups/
```

## Quick start

### 1. Pipeline setup

```bash
cd pipeline
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set YOUTUBE_CHANNELS=@yourchannel
```

### 2. Run the pipeline

```bash
python run.py                          # all channels in .env
python run.py --channel @mkbhd --max 20
python run.py --no-skip                # re-fetch everything
python run.py --help
```

### 3. Browse transcripts (frontend)

```bash
cd frontend
npm install

# Make data/ available as static files:
ln -s ../data public/data

npm run dev   # → http://localhost:5173
```

## GitHub Actions

Copy `github-workflows/pipeline.yml` → `.github/workflows/pipeline.yml`.

Set repository secret:
- `YOUTUBE_CHANNELS` — comma-separated channel handles (e.g. `@mkbhd,@linustechtips`)

The pipeline runs daily at 03:00 UTC, commits updated transcripts back to the repo, and can also be triggered manually from the Actions tab.

## Storage format

**`data/metadata/index.json`**
```json
{
  "updated_at": "2024-01-15T03:00:00Z",
  "videos": [
    {
      "video_id": "abc123",
      "title": "My Video",
      "channel_id": "UCxxx",
      "channel_name": "@mkbhd",
      "upload_date": "20240115",
      "duration_seconds": 600,
      "url": "https://youtube.com/watch?v=abc123",
      "has_transcript": true
    }
  ]
}
```

**`data/transcripts/{channel_id}/{video_id}.json`**
```json
{
  "video_id": "abc123",
  "language": "en",
  "is_generated": false,
  "clean_text": "Full cleaned transcript…",
  "word_count": 1842,
  "read_time_minutes": 9.2,
  "paragraphs": ["Paragraph one…", "Paragraph two…"],
  "segments": [
    { "text": "Hello everyone", "start": 0.0, "duration": 1.5 }
  ]
}
```
