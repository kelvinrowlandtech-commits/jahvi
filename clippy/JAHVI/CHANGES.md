# Jahvi — single-server cleanup pass

Removed: worker1/, worker2/, worker.py (dispatcher), HMAC, entry_*.py, impact_moments.py, correctuploadThing.py
(it held a LIVE UploadThing key — rotate it), stray jahvi.zip. Back to one server on one port.

Architecture: one process. EVERY edit is now a job row that the page polls (no SSE). Calm CPU + free render slot (max 2) = starts at
once in a background thread; otherwise queued and drained by queue_worker.py. Closing the tab never loses a render.
Headshot detection is unchanged: a plain request, never queued.
New: edit_common.py (shared helpers), job_poller.js (shared polling), GET /api/videos/{job_id}; the /api/video/{filename} route,
SSE parsing and the in-process route-runner are gone.

Credits: reserved atomically when a job is created; failed, canceled, and unrecoverable jobs are refunded. Legacy
pre-reservation jobs retain their success-time charge behavior.

Storage cleanup (sweeper.py, every 10 min): videos expire after 12h; failed/expired rows, old file logs and spent reset
tokens purged after 24h; orphaned UploadThing files (paginated) after 1h grace; leftover local temp/outputs; stuck jobs
failed after 2h; interrupted jobs re-queued on restart; custom-audio keys of queued jobs are protected; dry-run mode.

Other fixes: patchless export sizes (1920x1080 / 1080x1920 / 1080x1080); fast input seek; Beat Sync tail no longer replays
the last headshot second; CORS wildcard removed; optional JAHVI_TRUST_PROXY; NaN gap/volume rejected; session auto-refresh;
Password recovery now sends a short-lived one-time code through Gmail SMTP instead of a reset link.
forgot.html + reset.html; My videos shows expiry countdown / expired state; duplicate routes removed.
