"""
beatsync.py
Beat Sync Lab: the music (MP3, or the audio of a video) is REQUIRED. Every beat that rms.py finds
(after merging beats that are too close) gets a headshot clip, so each headshot lands exactly on
its beat. See beats.py for the planning rules.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

import beats
import builder
import config
import jobs
from dashboard import pick_effect
from database import SessionLocal, User, get_db
from me import get_current_user

beatsync_router = APIRouter(tags=["beatsync"])


def _volume(raw, default):
    """The page sends a fraction (1.0 = 100%); also tolerate a percent."""
    value = float(raw)
    value = value / 100 if value > 5 else value
    return jobs.clamp(value if value == value else default, 0.0, 2.0)


@beatsync_router.post("/api/beatsync")
def beatsync(
    video: UploadFile = File(...),
    audio: UploadFile = File(None),
    custom_audio: UploadFile = File(None),          # older name used by the page
    headshot_timestamps: str = Form(...),
    effect_class_ids: str = Form("[]"),
    ratio: str = Form("9:16"),
    music_volume: float = Form(1.0),
    video_volume: float = Form(0.5),
    autotitle: str = Form("false"),
    title_seconds: float = Form(config.TITLE_DEFAULT_SECONDS),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    music = audio or custom_audio
    if music is None or not (music.filename or "").strip():
        raise HTTPException(400, "Add a song (MP3) or a video to take the music from.")
    params = {
        "stamps": jobs.parse_stamps(headshot_timestamps),
        "effect_class_ids": jobs.parse_class_ids(effect_class_ids),
        "ratio": jobs.parse_ratio(ratio),
        "music_volume": _volume(music_volume, 1.0),
        "video_volume": _volume(video_volume, 0.5),
        "autotitle": jobs.parse_bool(autotitle),
        "title_seconds": jobs.clamp(title_seconds, 0.5, config.TITLE_MAX_SECONDS),
    }
    return jobs.submit_job(db=db, user=user, page="beatsync", params=params, video=video, audio=music)


def run_beatsync(ctx, progress):
    p = ctx.params
    progress("preparing", 4)
    info = builder.probe(ctx.video)
    if not info["has_video"] or info["duration"] <= 0:
        raise ValueError("That file could not be read as a video.")

    progress("extracting_audio", 8)
    music = beats.extract_audio(ctx.audio, ctx.tmp_dir)

    progress("detecting_beats", 14)
    found = beats.find_beats(music)

    progress("planning", 24)
    plan = beats.plan_beatsync(p["stamps"], found, info["duration"])
    with SessionLocal() as db:
        effect = pick_effect(db, p["effect_class_ids"])
    title_path = builder.pick_title() if p["autotitle"] else None

    silent_cut = ctx.tmp_dir / "picture.mp4"
    builder.render_clips(
        ctx.video, plan["clips"], silent_cut, ctx.tmp_dir, ratio=p["ratio"], effect=effect,
        title_path=title_path, title_seconds=p["title_seconds"],
        on_progress=lambda f: progress("rendering", 28 + 58 * f))

    progress("mixing", 88)
    out = config.OUTPUT_DIR / f"{ctx.id}.mp4"
    builder.mix_music(silent_cut, music, out, music_offset=plan["music_offset"], length=plan["length"],
                      music_volume=p["music_volume"], video_volume=p["video_volume"],
                      on_progress=lambda f: progress("mixing", 88 + 9 * f))
    return out


jobs.register("beatsync", run_beatsync)
