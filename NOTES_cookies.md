## Batch Strategy & Cookie Auth (Rate Limiting Solution)

### Problem
YouTube blocks IPs that make too many transcript API requests in a short window.
Anonymous requests from a Mac IP get blocked after ~15–20 requests.

### Solution: Cookies + Batch Strategy

**Cookies (primary fix):**
- Export your browser's YouTube session cookies to a Netscape `cookies.txt` file
- Inject into the transcript API via `http_client=requests.Session()` (v1.x API)
- Authenticated requests bypass IP rate limiting entirely

**Generate cookies.txt:**
```bash
# Option A — Safari (requires Terminal Full Disk Access in System Settings)
yt-dlp --cookies-from-browser safari --cookies data/cookies.txt "https://www.youtube.com"

# Option B — Chrome extension
# Install "Get cookies.txt LOCALLY" → youtube.com → Export → save as data/cookies.txt
```

**Add to .env:**
```
COOKIES_FILE=../data/cookies.txt
```

**Cookies need refreshing** when they expire (typically every few months).
You'll know they're expired if IP blocks start happening again.

**Batch strategy (secondary defense):**
```
BATCH_SIZE=10       # videos per batch
BATCH_PAUSE=180     # 3 min pause between batches
MAX_VIDEOS_PER_CHANNEL=20  # per scheduled run
```

If IP blocked mid-batch, pauses 5 minutes and retries — but gives up on a
video after 3 attempts (never hangs indefinitely).

### Confirmed Working Result (June 2026)
```
5 saved  |  41 skipped  |  4 unavailable  |  20 enriched  |  19 SRTs
54 videos total in index
```
