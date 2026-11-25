"""
builder.py
Everything that turns "a list of clips" into a finished video with FFmpeg.

How it works (same for all 3 pages):
  * A page's recipe makes a list of Clip(s)  -> (where to cut in the source, effect windows).
  * render_clips() renders them in small batches (CLIPS_PER_BATCH inputs per FFmpeg run, so RAM
    stays low), then joins the batches WITHOUT re-encoding.
  * Each FFmpeg run is a PRE-BUILT command list with one FILTER_SLOT; the filter_complex text is
    built separately and dropped into that slot just before running.
  * Effects come from the database as raw FFmpeg filter text:
        global filter   -> whole video
        headshot filter -> only around each headshot; its {ENABLE} marker is replaced by the
                           between(t,a,b)+... expression built from the headshot stamps.
  * There is no compression step: one quality encode (CRF), no bitrate cap, no resizing except
    the export-ratio crop.
"""
import json
import logging
import random
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import config

log = logging.getLogger("jahvi.builder")

RATIO_SIZES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
FILTER_SLOT = "{{FILTER}}"
ENABLE_MARK = "{ENABLE}"

ENCODE_ARGS = [
    "-c:v", "libx264", "-preset", config.X264_PRESET, "-crf", config.X264_CRF,
    "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", config.AUDIO_BITRATE, "-ar", "48000",
    "-movflags", "+faststart",
]


# ============================ clips ==========================================

@dataclass
class Clip:
    src_start: float                 # where in the source video this clip starts
    dur: float                       # seconds of source footage
    windows: list = field(default_factory=list)   # [(a, b)] effect windows, relative to the clip start
    freeze: float = 0.0              # last-resort: hold the first frame this long before the clip

    @property
    def out_dur(self):
        return self.dur + self.freeze


def clips_from_trims(trims, stamps):
    """Dashboard / Extraction: each (start, end) cut becomes a clip; headshots inside it get an effect window."""
    clips = []
    for start, end in trims:
        windows = []
        for stamp in stamps:
            if start <= stamp < end:
                a = stamp - start
                windows.append((a, min(a + config.TAIL, end - start)))
        clips.append(Clip(src_start=start, dur=end - start, windows=windows))
    return clips


# ============================ probing ========================================

def probe(path):
    """duration, fps, width, height, has_audio, has_video of a media file."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,r_frame_rate,width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise ValueError("This file could not be read as a video.")
    data = json.loads(result.stdout or "{}")
    info = {"duration": 0.0, "fps": 30, "width": 0, "height": 0, "has_audio": False, "has_video": False}
    try:
        info["duration"] = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        pass
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            info["has_audio"] = True
        elif stream.get("codec_type") == "video" and not info["has_video"]:
            info["has_video"] = True
            info["width"] = int(stream.get("width") or 0)
            info["height"] = int(stream.get("height") or 0)
            try:
                num, den = str(stream.get("r_frame_rate", "30/1")).split("/")
                fps = round(float(num) / float(den))
                info["fps"] = fps if 15 <= fps <= 60 else 30
            except (ValueError, ZeroDivisionError):
                info["fps"] = 30
    return info


# ============================ effects ========================================

def _clean_filter(text):
    text = (text or "").strip().strip(",")
    if any(bad in text for bad in (";", "[", "]", "\n", "\r")):
        return None
    return text


def load_effect(row):
    """DB row -> {"global": str, "headshot": str} or None if the row is unusable."""
    if row is None:
        return None
    global_filter = _clean_filter(row.global_filter)
    headshot_filter = _clean_filter(row.headshot_filter)
    if global_filter is None or headshot_filter is None:
        log.warning("effect %s skipped: filter text may not contain ; [ ] or new lines", row.id)
        return None
    if headshot_filter and ENABLE_MARK not in headshot_filter:
        log.warning("effect %s skipped: headshot_filter has no %s marker", row.id, ENABLE_MARK)
        return None
    if not global_filter and not headshot_filter:
        return None
    return {"global": global_filter, "headshot": headshot_filter}


def enable_expr(windows):
    return "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in windows)


# ============================ title ==========================================

def pick_title():
    """A random title image (red text on a black background) from titles/, or None."""
    files = [p for p in Path(config.TITLES_DIR).iterdir()
             if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    return str(random.choice(files)) if files else None


# ============================ command + filter ===============================

def make_command(src, clips, out_path, fps, title_path=None, title_len=0.0):
    """The FFmpeg command, ready to run, with ONE slot (FILTER_SLOT) for the filter_complex."""
    args = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats"]
    for clip in clips:
        args += ["-ss", f"{clip.src_start:.3f}", "-t", f"{clip.dur:.3f}", "-i", str(src)]
    if title_path:
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{title_len:.3f}", "-i", str(title_path)]
    args += ["-filter_complex", FILTER_SLOT, "-map", "[outv]", "-map", "[outa]", *ENCODE_ARGS, str(out_path)]
    return args


def with_filter(command, filter_text):
    return [filter_text if part == FILTER_SLOT else part for part in command]


def build_filter(clips, *, fps, has_audio, size, effect=None, title=None):
    """
    The filter_complex for one batch.
    size   = (width, height) of the output frame.
    title  = None or {"visible": seconds the title shows within THIS batch,
                      "first": True if this batch starts the video (fade-in),
                      "input": input index of the title image}
    """
    width, height = size
    parts, labels = [], []
    for i, clip in enumerate(clips):
        total = clip.out_dur
        video = f"[{i}:v]setpts=PTS-STARTPTS,fps={fps}"
        if width and height:
            video += (f",scale={width}:{height}:force_original_aspect_ratio=increase"
                      f",crop={width}:{height}")
        video += ",setsar=1"
        if clip.freeze > 0:
            video += f",tpad=start_duration={clip.freeze:.3f}:start_mode=clone"
        if effect and effect["global"]:
            video += f",{effect['global']}"
        if effect and effect["headshot"] and clip.windows:
            shifted = [(a + clip.freeze, b + clip.freeze) for a, b in clip.windows]
            video += "," + effect["headshot"].replace(ENABLE_MARK, enable_expr(shifted))
        # force the exact length (holds the last frame if the source ends early) so a/v never drift across joins
        video += f",tpad=stop_duration={total:.3f}:stop_mode=clone,trim=duration={total:.3f},setpts=PTS-STARTPTS,format=yuv420p"
        parts.append(f"{video}[v{i}]")

        fade = min(config.AUDIO_FADE, clip.dur / 2)
        if has_audio:
            audio = (f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                     f"asetpts=PTS-STARTPTS")
        else:
            audio = f"anullsrc=r=48000:cl=stereo,atrim=duration={clip.dur:.3f},asetpts=PTS-STARTPTS"
        audio += (f",afade=t=in:st=0:d={fade:.3f},afade=t=out:st={clip.dur - fade:.3f}:d={fade:.3f}")
        if clip.freeze > 0:
            ms = int(round(clip.freeze * 1000))
            audio += f",adelay={ms}|{ms}"
        audio += f",apad=whole_dur={total:.3f},atrim=duration={total:.3f},asetpts=PTS-STARTPTS"
        parts.append(f"{audio}[a{i}]")
        labels.append(f"[v{i}][a{i}]")

    n = len(clips)
    if title:
        parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=1[cv][outa]")
        visible = max(0.1, title["visible"])
        box_w, box_h = int(width * config.TITLE_BOX_WIDTH), int(height * config.TITLE_BOX_HEIGHT)
        top = int(height * config.TITLE_TOP)
        t = f"[{title['input']}:v]scale={box_w}:{box_h}:force_original_aspect_ratio=decrease"
        t += f",pad={width}:{height}:(ow-iw)/2:{top}:black"
        if title["first"]:
            t += ",fade=t=in:st=0:d=0.25"
        t += f",fade=t=out:st={max(0.0, visible - 0.4):.3f}:d=0.4,format=gbrp[tt]"
        parts.append(t)
        parts.append("[cv]format=gbrp[cvg]")
        parts.append("[cvg][tt]blend=all_mode=screen:shortest=1,format=yuv420p[outv]")
    else:
        parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=1[outv][outa]")
    return ";".join(parts)


# ============================ running FFmpeg =================================

def run_ffmpeg(args, total_seconds, on_progress=None, timeout=None):
    """
    Runs a ready command. Reads FFmpeg's own progress so the caller can update the
    database smoothly (on_progress gets 0..1, at most every ~1.5 s). A run that takes
    longer than `timeout` is killed so it can never hold a slot forever.
    """
    timeout = timeout or config.JOB_TIMEOUT_SECONDS
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, text=True)
        killer = threading.Timer(timeout, proc.kill)
        killer.start()
        last = 0.0
        try:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and on_progress and total_seconds > 0:
                    try:
                        seconds = int(value) / 1_000_000
                    except ValueError:
                        continue
                    now = time.monotonic()
                    if now - last >= 1.5:
                        last = now
                        on_progress(min(1.0, max(0.0, seconds / total_seconds)))
            proc.wait()
        finally:
            killer.cancel()
        if proc.returncode != 0:
            errors.seek(0)
            tail = errors.read()[-400:].decode("utf-8", "replace")
            raise RuntimeError(f"ffmpeg failed: {tail}")


def concat_copy(parts, out_path, tmp_dir):
    """Join already-encoded batches with no re-encoding."""
    listing = Path(tmp_dir) / "concat.txt"
    listing.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in parts), encoding="utf-8")
    run_ffmpeg(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(listing),
                "-c", "copy", "-movflags", "+faststart", str(out_path)], 0)


def render_clips(src, clips, out_path, tmp_dir, *, ratio=None, effect=None,
                 title_path=None, title_seconds=0.0, on_progress=None):
    """Renders clips (in batches) into out_path. on_progress gets 0..1 for the whole render."""
    info = probe(src)
    fps = info["fps"]
    size = RATIO_SIZES.get(ratio) or (info["width"], info["height"])
    batches = [clips[i:i + config.CLIPS_PER_BATCH] for i in range(0, len(clips), config.CLIPS_PER_BATCH)]
    total = sum(c.out_dur for c in clips) or 1.0
    done = 0.0
    parts = []
    for index, batch in enumerate(batches):
        batch_dur = sum(c.out_dur for c in batch)
        title = None
        use_title = title_path and title_seconds > done + 0.05
        if use_title:
            title = {"visible": min(batch_dur, title_seconds - done), "first": done == 0.0,
                     "input": len(batch)}
        out = out_path if len(batches) == 1 else Path(tmp_dir) / f"batch_{index:03d}.mp4"
        command = make_command(src, batch, out, fps,
                               title_path if use_title else None, batch_dur + 1.0)
        filter_text = build_filter(batch, fps=fps, has_audio=info["has_audio"], size=size,
                                   effect=effect, title=title)
        base = done
        run_ffmpeg(with_filter(command, filter_text), batch_dur,
                   (lambda f, base=base, bd=batch_dur: on_progress((base + f * bd) / total))
                   if on_progress else None)
        parts.append(out)
        done += batch_dur
        if on_progress:
            on_progress(min(1.0, done / total))
    if len(parts) > 1:
        concat_copy(parts, out_path, tmp_dir)
    return round(total, 3)


def mix_music(video_in, music_path, out_path, *, music_offset, length, music_volume, video_volume,
              on_progress=None):
    """Beat Sync final step: video is copied as-is, audio = gameplay sound + music (one AAC encode)."""
    fade = min(0.6, length / 2)
    graph = (f"[0:a]volume={video_volume:.3f}[g];"
             f"[1:a]atrim=start={music_offset:.3f}:duration={length:.3f},asetpts=PTS-STARTPTS,"
             f"volume={music_volume:.3f},apad=whole_dur={length:.3f},atrim=duration={length:.3f},"
             f"afade=t=out:st={max(0.0, length - fade):.3f}:d={fade:.3f}[m];"
             f"[g][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[outa]")
    run_ffmpeg(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-progress", "pipe:1", "-nostats",
                "-i", str(video_in), "-i", str(music_path), "-filter_complex", graph,
                "-map", "0:v", "-map", "[outa]", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_path)],
               length, on_progress)
