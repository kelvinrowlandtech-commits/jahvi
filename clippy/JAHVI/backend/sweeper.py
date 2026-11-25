"""
sweeper.py
Storage cleanup. One background thread runs every function below at startup and then every
SWEEP_INTERVAL_SECONDS (1 hour). Every function is independent and wrapped in its own try/except,
so one failure never stops the others.

  delete_stale_queue_rows  rows stuck queued/processing (or failed) > STUCK_ROW_DAYS (4d): credits refunded, row + files removed
  delete_stale_uploads     leftover source uploads in uploads/ older than UPLOAD_TTL_DAYS (4d)
  delete_expired_outputs   finished videos older than OUTPUT_TTL_HOURS (5h): file AND row deleted
  delete_stale_tmp         leftover per-job temp folders older than TMP_TTL_HOURS
  trim_log_rows            old rows of the extractreqlogs table
Only uploads/, outputs/ and tmp/ are ever touched - never titles/ or any code.
"""
import logging
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

log = logging.getLogger("jahvi.sweeper")


def _now():
    return datetime.now(timezone.utc)


def _delete_old_files(folder, max_age_seconds):
    """Delete files in `folder` whose last-modified time is older than max_age_seconds. Returns their names."""
    removed = []
    cutoff = time.time() - max_age_seconds
    for path in Path(folder).iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path.name)
        except FileNotFoundError:
            continue
        except OSError:
            log.warning("could not delete %s", path)
    return removed


def delete_stale_queue_rows():
    from database import Job, SessionLocal
    from jobs import refund_job
    cutoff = _now() - timedelta(days=config.STUCK_ROW_DAYS)
    with SessionLocal() as db:
        rows = (db.query(Job.id, Job.upload_path, Job.audio_path)
                .filter(Job.created_at < cutoff, Job.status.in_(["queued", "processing", "failed"])).all())
    for job_id, upload_path, audio_path in rows:
        refund_job(job_id)                                  # never delivered -> credits back (no-op if already refunded)
        for p in (upload_path, audio_path):
            if p:
                Path(p).unlink(missing_ok=True)
        shutil.rmtree(config.TMP_DIR / job_id, ignore_errors=True)
    if rows:
        with SessionLocal() as db:
            db.query(Job).filter(Job.id.in_([r[0] for r in rows])).delete(synchronize_session=False)
            db.commit()
    return len(rows)


def delete_stale_uploads():
    return len(_delete_old_files(config.UPLOAD_DIR, config.UPLOAD_TTL_DAYS * 86400))


def delete_expired_outputs():
    from database import Job, SessionLocal
    cutoff = _now() - timedelta(hours=config.OUTPUT_TTL_HOURS)
    count = 0
    with SessionLocal() as db:
        rows = db.query(Job.id, Job.output_file).filter(Job.status == "completed", Job.completed_at < cutoff).all()
        for job_id, output_file in rows:
            if output_file:
                (config.OUTPUT_DIR / output_file).unlink(missing_ok=True)
        if rows:
            db.query(Job).filter(Job.id.in_([r[0] for r in rows])).delete(synchronize_session=False)
            db.commit()
        count += len(rows)
        # orphan files (no row, e.g. after a crash): by file age, and drop any row that still points at them
        names = _delete_old_files(config.OUTPUT_DIR, config.OUTPUT_TTL_HOURS * 3600)
        if names:
            db.query(Job).filter(Job.output_file.in_(names)).delete(synchronize_session=False)
            db.commit()
        count += len(names)
    return count


def delete_stale_tmp():
    cutoff = time.time() - config.TMP_TTL_HOURS * 3600
    count = 0
    for path in Path(config.TMP_DIR).iterdir():
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                count += 1
        except FileNotFoundError:
            continue
    return count


def trim_log_rows():
    from sqlalchemy import text
    from database import SessionLocal
    cutoff = _now() - timedelta(days=config.LOG_ROW_DAYS)
    with SessionLocal() as db:
        done = db.execute(text("DELETE FROM extractreqlogs WHERE created_at < :c"), {"c": cutoff}).rowcount
        db.commit()
    return done or 0


SWEEPS = (delete_stale_queue_rows, delete_stale_uploads, delete_expired_outputs, delete_stale_tmp, trim_log_rows)


def sweep_once():
    for sweep in SWEEPS:
        try:
            removed = sweep()
            if removed:
                log.info("%s removed %s item(s)", sweep.__name__, removed)
        except Exception:
            log.exception("%s failed", sweep.__name__)


def _loop(stop: threading.Event):
    while not stop.is_set():
        sweep_once()
        stop.wait(config.SWEEP_INTERVAL_SECONDS)


def start_sweeper(stop: threading.Event):
    thread = threading.Thread(target=_loop, args=(stop,), name="sweeper", daemon=True)
    thread.start()
    return thread
