"""
dashboard.py
Dashboard (Quick Edit): cut only (Normal / Maximum gap / Exact gap) + effect from the effect table
+ optional auto title. No beat sync here.
"""
from beats import plan_exact_gap
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

import builder
import config
import jobs
from database import EffectPreset, User, get_db
from helper import plan_trims
from me import get_current_user

dashboard_router = APIRouter(tags=["dashboard"])

GAP_MODES = ("normal", "maximum", "exact")


def pick_effect(db, class_ids):
    """One random active effect from the chosen classes (no plan tiers)."""
    if not class_ids:
        return None
    row = (db.query(EffectPreset)
           .filter(EffectPreset.active.is_(True), EffectPreset.class_name.in_(class_ids))
           .order_by(func.random()).first())
    return builder.load_effect(row)


@dashboard_router.post("/api/generate")
def generate(
    video: UploadFile = File(...),
    headshot_timestamps: str = Form(...),
    effect_class_ids: str = Form("[]"),
    ratio: str = Form("9:16"),
    gap_mode: str = Form("normal"),
    gap_value: float = Form(3.0),
    autotitle: str = Form("false"),
    title_seconds: float = Form(config.TITLE_DEFAULT_SECONDS),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if gap_mode not in GAP_MODES:
        raise HTTPException(400, "Unknown gap mode.")
    params = {
        "stamps": jobs.parse_stamps(headshot_timestamps),
        "effect_class_ids": jobs.parse_class_ids(effect_class_ids),
        "ratio": jobs.parse_ratio(ratio),
        "gap_mode": gap_mode,
        "gap_value": jobs.clamp(gap_value, 0.5, 10.0),
        "autotitle": jobs.parse_bool(autotitle),
        "title_seconds": jobs.clamp(title_seconds, 0.5, config.TITLE_MAX_SECONDS),
    }
    return jobs.submit_job(db=db, user=user, page="dashboard", params=params, video=video)


def run_dashboard(ctx, progress):
    p = ctx.params
    stamps = p["stamps"]
    progress("preparing", 6)
    info = builder.probe(ctx.video)
    if not info["has_video"] or info["duration"] <= 0:
        raise ValueError("That file could not be read as a video.")

    from database import SessionLocal
    with SessionLocal() as db:
        effect = pick_effect(db, p["effect_class_ids"])

    progress("planning", 12)
    if p["gap_mode"] == "normal":
        clips = builder.clips_from_trims([(0.0, info["duration"])], stamps)
    elif p["gap_mode"] == "maximum":      # the button now labelled "Exact gap"
        clips = plan_exact_gap(stamps, p["gap_value"], info["duration"])
    else:
        clips = builder.clips_from_trims(plan_trims(stamps, p["gap_value"], patch=False), stamps)



    title_path = builder.pick_title() if p["autotitle"] else None
    out = config.OUTPUT_DIR / f"{ctx.id}.mp4"
    builder.render_clips(
        ctx.video, clips, out, ctx.tmp_dir, ratio=p["ratio"], effect=effect,
        title_path=title_path, title_seconds=p["title_seconds"],
        on_progress=lambda f: progress("rendering", 18 + 78 * f))
    return out


jobs.register("dashboard", run_dashboard)
