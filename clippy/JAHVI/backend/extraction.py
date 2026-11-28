"""
extraction.py
Headshot Extraction Lab: cut around every headshot (optionally patching short lead-ups), apply the
export ratio. No effects, no title. The frontend polls /extraction_progress/{job_id} (in jobs.py).
"""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session
from beats import plan_exact_gap
import builder
import config
import jobs
from database import User, get_db
from helper import plan_trims
from me import get_current_user

extraction_router = APIRouter(tags=["extraction"])


@extraction_router.post("/extract")
def extract(
    video: UploadFile = File(...),
    headshot_timestamps: str = Form(...),
    max_gap: float = Form(3.0),
    ratio: str = Form("9:16"),
    patch: str = Form("false"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    params = {
        "stamps": jobs.parse_stamps(headshot_timestamps),
        "max_gap": jobs.clamp(max_gap, 0.5, 10.0),
        "ratio": jobs.parse_ratio(ratio),
        "patch": jobs.parse_bool(patch),
    }
    return jobs.submit_job(db=db, user=user, page="extraction", params=params, video=video)


def run_extraction(ctx, progress):
    p = ctx.params
    progress("preparing", 6)
    info = builder.probe(ctx.video)
    if not info["has_video"] or info["duration"] <= 0:
        raise ValueError("That file could not be read as a video.")
    progress("planning", 12)
    if p["patch"]:
        clips = plan_exact_gap(p["stamps"], p["max_gap"], info["duration"])
    else:
        clips = builder.clips_from_trims(plan_trims(p["stamps"], p["max_gap"], patch=False), [])            # no effects on this page
    out = config.OUTPUT_DIR / f"{ctx.id}.mp4"
    builder.render_clips(ctx.video, clips, out, ctx.tmp_dir, ratio=p["ratio"],
                         on_progress=lambda f: progress("rendering", 18 + 78 * f))
    return out


jobs.register("extraction", run_extraction)
