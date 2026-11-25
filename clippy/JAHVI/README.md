# Jahvi

One FastAPI server (`backend/`) plus a static frontend (`frontend/`).

## Run it

```bash
sudo apt-get install -y ffmpeg          # needs ffmpeg + ffprobe
python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env     # then fill it in and export the variables
python -m uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000
python -m http.server 5000 --directory frontend
```

Open `http://localhost:5000`.

## Where the URLs live (change these when you change environment)

- `JAHVI_FRONTEND_URL` -> the frontend URL allowed by backend CORS and used for reset-password links (defaults to `http://localhost:5000`; set it to your Codespaces or deployed frontend URL).
- `frontend/url.js` exports `API_BASE_URL` for every frontend API call. It selects localhost:8000 for local development, the forwarded port 8000 for Codespaces, and `https://javi.orinda.com` for production. Set `BACKEND_URL` there only when you need to override automatic detection.
- `backend/config.py` -> tunables such as queue load threshold, video retention hours, and sweeper settings; each can also be set by env var.
- UploadThing reads `TOKEN` first, while retaining support for `UPLOADTHING_TOKEN` and the older aliases.

## How an edit works

Dashboard, Headshot Lab and Beat Sync all work the same way, with **polling only** (no SSE):

1. The request is validated and the edit cost is atomically deducted when its job is accepted; failed jobs are refunded.
2. A job row is created in `queued_jobs` and the API immediately returns its `job_id`.
   - CPU under `LOAD_THRESHOLD_PERCENT` and a render slot free (`MAX_CONCURRENT_RENDERS`): the edit starts right away
     in a background thread from the local upload.
   - Otherwise the inputs go to UploadThing and the job waits (`queued`). `queue_worker.py` wakes every
     `QUEUE_DRAIN_INTERVAL_SECONDS` and starts the oldest `QUEUE_JOBS_PER_DRAIN` jobs when there is room.
3. The page polls `GET /api/videos/{job_id}` every few seconds (status, progress %, queue position).
   Closing the tab loses nothing: the finished video appears in "My videos".
4. When a job finishes: output uploaded to UploadThing -> job marked completed -> original input deleted.
   The video streams back through `/api/videos/{job_id}/output`.

Headshot **detection** (`/api/detect-headshots`, OpenCV) is never queued: it is a plain request/response.

## Storage cleanup (nothing is left to grow)

`sweeper.py` runs every `SWEEP_INTERVAL_MINUTES`:

- finished queue videos are deleted `RETENTION_HOURS` (12) after completion and the job shows "expired"
- failed/expired job rows, old file logs and spent reset tokens are purged after `ROW_RETENTION_HOURS` (24)
- UploadThing files no live job references are deleted after a 1h grace window (paginated listing)
- leftover local temp files/folders (older than 3h) and unserved exports (older than 1h) are removed
- jobs stuck in "processing" for 2h are failed; a restart re-queues interrupted jobs

First run: set `JAHVI_SWEEPER_DRY_RUN=1` to only log what it would delete.
Kept forever on purpose: `users`, `credit_purchases`, `signup_security`.

## Patcher vs patchless

The Headshot Lab uses `patchless.py` (exact gap, no patching) by default.
Turning patching on (maximum gap) uses `patcher.py`.
