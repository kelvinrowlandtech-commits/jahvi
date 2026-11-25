"""
config.py
Every environment-specific URL and tunable lives here (one server, one file).
All values are hardcoded; edit them directly in this file.
"""

from pathlib import Path

# --- Frontend: who may call this API ---
FRONTEND_URL = "http://localhost:5000"
EXTRA_FRONTEND_ORIGINS = [
    "http://127.0.0.1:5000",
    "https://clipforge-ff.netlify.app",
]
CODESPACE_NAME = ""  # put your Codespace name here if you run in GitHub Codespaces
CODESPACE_FRONTEND_ORIGIN = (
    f"https://{CODESPACE_NAME}-5000.app.github.dev"
    if CODESPACE_NAME else None
)
FRONTEND_ORIGINS = list(dict.fromkeys([
    FRONTEND_URL.rstrip("/"),
    *EXTRA_FRONTEND_ORIGINS,
    *([CODESPACE_FRONTEND_ORIGIN] if CODESPACE_FRONTEND_ORIGIN else []),
]))

# --- Folders (all inside the backend folder) ---------------------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"    # videos/audio waiting to be processed
OUTPUT_DIR = BASE_DIR / "outputs"    # finished videos (kept OUTPUT_TTL_HOURS)
TMP_DIR = BASE_DIR / "tmp"           # one sub-folder per running job
TITLES_DIR = BASE_DIR / "titles"     # red-text-on-black title images (png/jpg)
for _folder in (UPLOAD_DIR, OUTPUT_DIR, TMP_DIR, TITLES_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

# --- Jobs, credits, queue ----------------------------------------------------
JOB_COST = 2                 # credits taken at submit; refunded if the job fails
MAX_CONCURRENT_JOBS = 4      # jobs rendering at once (direct jobs + the drainer)
QUEUE_CAP = 30               # more queued jobs than this -> "busy, try again"
DRAIN_IDLE_SECONDS = 2       # drainer sleep when it has nothing to do
JOB_TIMEOUT_SECONDS = 20 * 60  # one FFmpeg run is killed after this long
MAX_CONCURRENT_DETECTIONS = 2  # auto headshot detection (OpenCV) runs at most this many at once

# --- Disk / upload guards ----------------------------------------------------
DISK_MAX_USED_PERCENT = 95   # at or above this the server refuses new uploads
MAX_VIDEO_MB = 200
MAX_AUDIO_MB = 200           # Beat Sync audio may be a whole video, so same size

# --- Cutting knobs (shared by all 3 pages) -----------------------------------
TAIL = 0.7           # seconds always kept AFTER a headshot stamp (use 0.5 for tighter)
START_MARGIN = 1.0   # a clip never starts closer than this to the previous stamp
CLEAN_MARGIN = 1.0   # patch footage stays this far from any stamp
MIN_LEAD = 0.5       # clip with less lead-up than this is merged into the previous clip
MIN_PATCH = 0.4      # ignore patch fragments shorter than this
MERGE_EPS = 0.05     # cuts that touch within this gap are joined
AUDIO_FADE = 0.04    # tiny audio fade at every cut so joins don't pop

# --- Beat Sync ---------------------------------------------------------------
MIN_BEAT_GAP = 1.2       # beats closer than this to the last used beat are merged away
MAX_INTRO_SECONDS = 4.0  # if the first beat is later than this, the edit starts earlier in the song

# --- Rendering ---------------------------------------------------------------
CLIPS_PER_BATCH = 10     # clips rendered per FFmpeg run (keeps RAM low); batches are joined without re-encoding
X264_PRESET = "veryfast"
X264_CRF = "20"          # quality encode only - no bitrate cap, no resizing except the export ratio
AUDIO_BITRATE = "160k"

# --- Auto title --------------------------------------------------------------
TITLE_BOX_WIDTH = 0.60   # title max width as a fraction of the video width
TITLE_BOX_HEIGHT = 0.16  # title max height as a fraction of the video height
TITLE_TOP = 0.07         # distance from the top as a fraction of the video height
TITLE_DEFAULT_SECONDS = 3.0
TITLE_MAX_SECONDS = 10.0

# --- Storage cleanup (all run every SWEEP_INTERVAL_SECONDS) ------------------
SWEEP_INTERVAL_SECONDS = 3600
OUTPUT_TTL_HOURS = 5     # finished videos (and their rows) are deleted after this
UPLOAD_TTL_DAYS = 4      # leftover source uploads
STUCK_ROW_DAYS = 4       # rows stuck queued/processing (refunded) and old failed rows
TMP_TTL_HOURS = 6        # leftover per-job temp folders
LOG_ROW_DAYS = 4         # old rows in the extractreqlogs table
