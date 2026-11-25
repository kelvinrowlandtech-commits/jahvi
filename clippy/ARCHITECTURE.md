# ClipForge / Jahvi - architecture (supersedes the old .txt docs)

## The 3 processing pages, one job system
| Page | Route | Does |
|---|---|---|
| Dashboard | `POST /api/generate` | cut (Normal / Maximum gap / Exact gap) + effect + optional auto title |
| Extraction Lab | `POST /extract` | cut around headshots (optional patching) + ratio |
| Beat Sync Lab | `POST /api/beatsync` | music REQUIRED; every beat gets a headshot landing exactly on it + effect + optional auto title |

All three call `jobs.submit_job()` and register a recipe (`jobs.register`). Auto headshot detection
(`POST /api/detect-headshots`, OpenCV, in `cv4.py`) is on all three pages through `timeline.js`:
the browser compresses the video, the server returns stamps, the bars are drawn automatically.

## Submit order (jobs.py)
validate form -> disk < 95% used? -> queue below cap? -> take 2 credits atomically -> save files (size capped)
-> free slot AND empty queue ? run now (ThreadPoolExecutor) : insert row status=queued.
A failure after the credits were taken refunds them.

## Queue
* Running jobs <= `MAX_CONCURRENT_JOBS` (4), enforced by one atomic SQL counter (`jobcount`).
* ONE drainer thread runs queued jobs one at a time, oldest first, reserving a slot before each.
* A new job never jumps ahead of a waiting one.
* Every job writes stage + percentage to its row (FFmpeg's own progress feeds the bar); the frontend polls.
  Dashboard/Beat Sync: `GET /api/videos/{id}`. Extraction: `GET /extraction_progress/{id}` (JSON, then the file).
* Finished video: `GET /api/videos/{id}/video` returns the real MP4 (`?download=true` = attachment).
* Failed job -> credits refunded (once). Server restart -> counter reset, mid-run jobs failed + refunded, queued jobs continue.

## Rendering (builder.py)
Clips -> batches of 10 per FFmpeg run -> joined with no re-encode. The FFmpeg command is built once
with a single `{{FILTER}}` slot; the filter_complex text is built separately and dropped in.
Effects come from the `effect_presets` table (raw FFmpeg text): `global_filter` (whole video) and
`headshot_filter` (put `enable='{ENABLE}'` on each filter; it becomes `between(t,a,b)+...`).
No compression step: one quality encode (CRF 20), no bitrate cap, no resizing except the export ratio.
Auto title: random image from `titles/` (red text on black); a screen blend removes the black.

## Beat Sync rules (beats.py)
* `rms.py` finds beats; beats closer than 1.2 s to the last used beat are merged away (1,2,3 -> 1,3).
* Every kept beat gets a headshot (cycling when there are more beats than headshots).
* Each headshot is cut to stamp + 0.7 s (`TAIL`); the lead-up fills the gap to the previous piece, so
  pieces tile the music exactly. Short lead-up -> borrow clean footage -> last resort freeze the first frame.

## Storage cleanup (sweeper.py, hourly)
stuck/failed rows > 4 d (refunded) | leftover uploads > 4 d | finished videos + rows > 5 h | tmp folders | old log rows.
Only uploads/, outputs/, tmp/ are touched.

## First-time setup
1. `pip install -r requirements.txt` and make sure `ffmpeg` + `ffprobe` are installed on the server.
2. Start the server once (creates the new tables), then `python seed_effects.py` (starter effects).
3. Put your title images in `JAHVI/backend/titles/` (the two sample_*.png are placeholders).
4. Tune `config.py` to your host: `MAX_CONCURRENT_JOBS` (about 1 per CPU core), `QUEUE_CAP`, size limits.
