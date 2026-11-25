"""
jobs.py
The one job system behind all 3 pages (Dashboard, Extraction Lab, Beat Sync Lab).

  submit  : disk check -> queue-cap check -> take credits -> save files -> run now or queue
  run now : a free slot AND an empty queue -> ThreadPoolExecutor (at most MAX_CONCURRENT_JOBS)
  queue   : just a row with status='queued'; ONE drainer thread runs queued jobs one at a time,
            always reserving a slot first, so total running jobs never exceed MAX_CONCURRENT_JOBS
  progress: every job writes stage + percentage to its row; the frontend polls, nothing is pushed
  credits : taken at submit (so nobody can queue 100 jobs for free), refunded if the job fails
  files   : the job always deletes its own upload / temp folder when it ends

Each page registers a "recipe" (register("dashboard", fn)); a recipe is fn(ctx, progress) -> output path.
"""
import json
import logging
import shutil
import threading
import uuid
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

import config
from database import EffectPreset, Job, SessionLocal, User, get_db
from me import get_current_user

log = logging.getLogger("jahvi.jobs")
jobs_router = APIRouter(tags=["jobs"])

RECIPES = {}
JobContext = namedtuple("JobContext", "id user_id page params video audio tmp_dir")
_executor = ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_JOBS, thread_name_prefix="job")

STAGE_TEXT = {
    "queued": "Waiting in the queue",
    "preparing": "Getting your video ready",
    "extracting_audio": "Extracting the audio",
    "detecting_beats": "Finding the beats",
    "planning": "Planning the cuts",
    "rendering": "Rendering your video",
    "mixing": "Mixing the music",
    "finalizing": "Finishing up",
    "done": "Done",
    "failed": "Failed",
}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def register(page, recipe):
    RECIPES[page] = recipe


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.isoformat() if value else None


# ============================ form parsing (shared) ==========================

def parse_stamps(raw):
    try:
        values = json.loads(raw)
        stamps = sorted({round(float(v), 3) for v in values})
    except (TypeError, ValueError):
        raise HTTPException(400, "The headshot timestamps could not be read.")
    if not stamps or len(stamps) > 300 or stamps[0] < 0 or any(s != s or s > 36000 for s in stamps):
        raise HTTPException(400, "Please mark at least one headshot (and no more than 300).")
    return stamps


def parse_class_ids(raw):
    try:
        values = json.loads(raw or "[]")
        return [str(v)[:60] for v in values][:30]
    except (TypeError, ValueError):
        return []


def parse_bool(raw):
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def parse_ratio(raw):
    ratio = (raw or "").strip()
    return ratio if ratio in ("9:16", "1:1", "16:9") else None


def clamp(value, low, high):
    return max(low, min(high, value))


# ============================ small DB helpers ===============================

def disk_has_room():
    usage = shutil.disk_usage(config.UPLOAD_DIR)
    return usage.used / usage.total * 100 < config.DISK_MAX_USED_PERCENT


def take_credits(db, user_id, amount):
    """Atomic check-and-deduct: only succeeds if the user has at least `amount`."""
    done = db.execute(text("UPDATE users SET credits = credits - :a WHERE id = :u AND credits >= :a"),
                      {"a": amount, "u": user_id}).rowcount == 1
    db.commit()
    return done


def give_back_credits(db, user_id, amount):
    db.execute(text("UPDATE users SET credits = credits + :a WHERE id = :u"), {"a": amount, "u": user_id})
    db.commit()


def refund_job(job_id):
    """Gives the job's credits back exactly once, however many times it is called."""
    with SessionLocal() as db:
        row = db.execute(text("UPDATE jobs SET refunded = true WHERE id = :id AND refunded = false "
                              "RETURNING user_id, cost"), {"id": job_id}).first()
        if row:
            db.execute(text("UPDATE users SET credits = credits + :c WHERE id = :u"), {"c": row[1], "u": row[0]})
        db.commit()


def reserve_slot(db):
    done = db.execute(text("UPDATE jobcount SET job_count = job_count + 1 WHERE id = 1 AND job_count < :m"),
                      {"m": config.MAX_CONCURRENT_JOBS}).rowcount == 1
    db.commit()
    return done


def release_slot():
    with SessionLocal() as db:
        db.execute(text("UPDATE jobcount SET job_count = GREATEST(job_count - 1, 0) WHERE id = 1"))
        db.commit()


def set_progress(job_id, stage, percentage):
    try:
        with SessionLocal() as db:
            db.execute(text("UPDATE jobs SET stage = :s, percentage = :p WHERE id = :id AND status = 'processing'"),
                       {"s": stage, "p": int(clamp(percentage, 0, 99)), "id": job_id})
            db.commit()
    except Exception:
        log.exception("could not write progress for %s", job_id)


def _unlink(*paths):
    for p in paths:
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                log.warning("could not delete %s", p)


def save_upload(upload: UploadFile, dest: Path, max_mb):
    limit, written = max_mb * 1024 * 1024, 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, f"That file is too large (the limit is {max_mb} MB).")
                out.write(chunk)
        if written == 0:
            raise HTTPException(400, "The uploaded file is empty.")
    except BaseException:
        _unlink(dest)
        raise
    return str(dest)


# ============================ submit =========================================

def submit_job(*, db: Session, user: User, page, params, video: UploadFile, audio: UploadFile = None):
    """Shared first half of every page's route. Returns {job_id, status, queue_position}."""
    if not disk_has_room():
        raise HTTPException(503, "Our servers are almost full right now. Please try again in a little while.")
    queued_now = db.query(func.count(Job.id)).filter(Job.status == "queued").scalar() or 0
    if queued_now >= config.QUEUE_CAP:
        raise HTTPException(503, "We're very busy right now. Please try again in a few minutes.")
    if not take_credits(db, user.id, config.JOB_COST):
        raise HTTPException(402, f"You need at least {config.JOB_COST} credits to start a video.")

    job_id = str(uuid.uuid4())
    video_path = audio_path = None
    reserved = False
    try:
        video_path = save_upload(video, config.UPLOAD_DIR / f"{job_id}_video.mp4", config.MAX_VIDEO_MB)
        if audio is not None:
            ext = Path(audio.filename or "").suffix.lower()
            ext = ext if ext in AUDIO_EXTENSIONS else ".bin"
            audio_path = save_upload(audio, config.UPLOAD_DIR / f"{job_id}_audio{ext}", config.MAX_AUDIO_MB)

        direct = queued_now == 0 and reserve_slot(db)      # queue-jumping is not allowed
        reserved = direct
        now = _now()
        job = Job(id=job_id, user_id=user.id, page=page,
                  status="processing" if direct else "queued",
                  stage="preparing" if direct else "queued", percentage=0,
                  params=json.dumps(params), upload_path=video_path, audio_path=audio_path,
                  cost=config.JOB_COST, created_at=now, started_at=now if direct else None)
        db.add(job)
        db.commit()
    except Exception as exc:
        db.rollback()
        _unlink(video_path, audio_path)
        if reserved:
            release_slot()
        give_back_credits(db, user.id, config.JOB_COST)
        if isinstance(exc, HTTPException):
            raise
        log.exception("could not start job")
        raise HTTPException(500, "We couldn't start your video. Your credits were not used. Please try again.")

    position = 0
    if not direct:
        position = db.query(func.count(Job.id)).filter(Job.status == "queued", Job.created_at < job.created_at).scalar() or 0
    else:
        _executor.submit(run_job, job_id)
    return {"job_id": job_id, "status": job.status, "queue_position": position}


# ============================ running ========================================

def run_job(job_id):
    """Runs one job. Used by direct jobs (pool thread) and by the drainer. Always releases its slot."""
    tmp_dir = config.TMP_DIR / job_id
    upload_path = audio_path = None
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            upload_path, audio_path = job.upload_path, job.audio_path
            ctx = JobContext(job.id, job.user_id, job.page, json.loads(job.params or "{}"),
                             upload_path, audio_path, tmp_dir)
            if job.started_at is None:
                job.started_at = _now()
            job.status, job.stage, job.percentage = "processing", "preparing", 3
            db.commit()
        tmp_dir.mkdir(parents=True, exist_ok=True)
        recipe = RECIPES[ctx.page]
        output = Path(recipe(ctx, lambda stage, pct: set_progress(job_id, stage, pct)))
        with SessionLocal() as db:
            db.execute(text("UPDATE jobs SET status='completed', stage='done', percentage=100, output_file=:f, "
                            "completed_at=now(), error=NULL WHERE id=:id"), {"f": output.name, "id": job_id})
            db.commit()
        log.info("job %s (%s) done", job_id, ctx.page)
    except Exception as exc:
        log.exception("job %s failed", job_id)
        message = str(exc) if isinstance(exc, ValueError) else (
            "Something went wrong while making your video. Your credits were returned. Please try again.")
        try:
            with SessionLocal() as db:
                db.execute(text("UPDATE jobs SET status='failed', stage='failed', error=:e, completed_at=now() "
                                "WHERE id=:id"), {"e": message, "id": job_id})
                db.commit()
            refund_job(job_id)
        except Exception:
            log.exception("could not mark job %s failed", job_id)
    finally:
        _unlink(upload_path, audio_path)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        release_slot()


# ============================ the queue drainer ==============================

def _claim_next_queued(db):
    row = db.execute(text(
        "UPDATE jobs SET status='processing', stage='preparing', started_at=now() "
        "WHERE id = (SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) "
        "RETURNING id")).first()
    db.commit()
    return row[0] if row else None


def _drain_loop(stop: threading.Event):
    """One queued job at a time, oldest first. Always takes a slot first so the total stays <= the limit."""
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                has_queued = db.query(Job.id).filter(Job.status == "queued").first() is not None
                if not has_queued or not reserve_slot(db):
                    job_id = None
                else:
                    try:
                        job_id = _claim_next_queued(db)
                    except Exception:
                        release_slot()
                        raise
                    if job_id is None:
                        release_slot()
            if job_id is None:
                stop.wait(config.DRAIN_IDLE_SECONDS)
                continue
            run_job(job_id)            # releases the slot itself
        except Exception:
            log.exception("drainer error")
            stop.wait(5)


def start_drainer(stop: threading.Event):
    thread = threading.Thread(target=_drain_loop, args=(stop,), name="queue-drainer", daemon=True)
    thread.start()
    return thread


def startup_reset():
    """Server (re)start: no job is running any more. Reset the counter; jobs that were mid-run are failed and refunded."""
    with SessionLocal() as db:
        db.execute(text("INSERT INTO jobcount (id, job_count) VALUES (1, 0) "
                        "ON CONFLICT (id) DO UPDATE SET job_count = 0"))
        dead = db.execute(text(
            "UPDATE jobs SET status='failed', stage='failed', completed_at=now(), error=:e "
            "WHERE status='processing' RETURNING id, upload_path, audio_path"),
            {"e": "The server restarted while your video was being made. Your credits were returned."}).all()
        db.commit()
    for job_id, upload_path, audio_path in dead:
        refund_job(job_id)
        _unlink(upload_path, audio_path)
        shutil.rmtree(config.TMP_DIR / job_id, ignore_errors=True)


# ============================ routes =========================================

def _output_exists(job):
    return bool(job.output_file) and (config.OUTPUT_DIR / job.output_file).is_file()


def _position(db, job):
    if job.status != "queued":
        return None
    return db.query(func.count(Job.id)).filter(Job.status == "queued", Job.created_at < job.created_at).scalar() or 0


def public_job(db, job):
    status = job.status
    if status == "completed" and not _output_exists(job):
        status = "expired"
    expires = job.completed_at + timedelta(hours=config.OUTPUT_TTL_HOURS) if job.completed_at else None
    return {
        "id": job.id,
        "edit_type": job.page,
        "status": status,
        "queue_position": _position(db, job),
        "progress_percent": job.percentage,
        "progress_message": STAGE_TEXT.get(job.stage, job.stage or ""),
        "error": job.error,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "completed_at": _iso(job.completed_at),
        "expires_at": _iso(expires) if status == "completed" else None,
        "video_url": f"/api/videos/{job.id}/video" if status == "completed" else None,
    }


def _own_job(db, job_id, user):
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "Video not found.")
    return job


@jobs_router.get("/api/videos")
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Job).filter(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(50).all()
    return {"videos": [public_job(db, job) for job in rows]}


@jobs_router.get("/api/videos/{job_id}")
def job_status(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return public_job(db, _own_job(db, job_id, user))


@jobs_router.get("/api/videos/{job_id}/video")
def job_video(job_id: str, download: bool = False, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Returns the actual MP4 (frontend and backend are different servers, so never just a path)."""
    job = _own_job(db, job_id, user)
    if job.status != "completed" or not _output_exists(job):
        raise HTTPException(410, "This video is no longer available.")
    headers = {"Content-Disposition": f'attachment; filename="jahvi-{job.page}-{job.id[:8]}.mp4"'} if download else None
    return FileResponse(config.OUTPUT_DIR / job.output_file, media_type="video/mp4", headers=headers)


@jobs_router.delete("/api/videos/{job_id}")
def delete_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = _own_job(db, job_id, user)
    if job.status in ("queued", "processing"):
        raise HTTPException(409, "This video is still being made.")
    _unlink(config.OUTPUT_DIR / job.output_file if job.output_file else None)
    db.delete(job)
    db.commit()
    return {"deleted": True}


@jobs_router.get("/api/effects")
def list_effect_classes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(EffectPreset.class_name, func.count(EffectPreset.id), func.min(EffectPreset.style))
            .filter(EffectPreset.active.is_(True)).group_by(EffectPreset.class_name)
            .order_by(EffectPreset.class_name).all())
    return {"classes": [{"id": name, "name": name, "description": style or "", "count": count}
                        for name, count, style in rows]}


@jobs_router.get("/extraction_progress/{job_id}")
def extraction_progress(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Extraction Lab contract: progress JSON while running, then the actual video file."""
    job = _own_job(db, job_id, user)
    if job.status == "completed" and _output_exists(job):
        return FileResponse(config.OUTPUT_DIR / job.output_file, media_type="video/mp4")
    if job.status == "completed":
        return {"status": "failed", "stage": "expired", "percentage": 0, "error": "This video expired and was removed."}
    position = _position(db, job)
    stage = (f"Waiting in the queue (position {position + 1})" if job.status == "queued"
             else STAGE_TEXT.get(job.stage, job.stage or "Processing"))
    return {"status": job.status, "stage": stage, "percentage": job.percentage, "error": job.error,
            "queue_position": position}
