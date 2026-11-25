"""
beats.py
Beat Sync logic: get the audio, find the beats, and plan the clips so every
headshot lands exactly on a beat.

Rules (all knobs in config.py):
  * Beats closer than MIN_BEAT_GAP to the last USED beat are merged away (1s,2s,3s -> 1s,3s).
  * Every remaining beat gets a headshot, cycling through the headshots in order when there are
    more beats than headshots.
  * Each beat's piece = [lead-up][HEADSHOT on the beat][TAIL]; the lead-up is the gap to the previous
    piece's tail, so pieces tile the timeline exactly.
  * Not enough lead-up footage -> borrow clean footage (patches); still short -> hold the first
    frame (freeze-pad fallback). Video is never slowed down.
"""
import logging
import subprocess
from pathlib import Path

import builder
import config
from builder import Clip
from helper import clean_zones

log = logging.getLogger("jahvi.beats")


# ----------------------------- audio -----------------------------------------

def extract_audio(src, tmp_dir):
    """Path to an audio file librosa can read: the MP3 itself, or the audio pulled out of a video."""
    info = builder.probe(src)
    if not info["has_audio"]:
        raise ValueError("No audio was found in the music file you uploaded.")
    if not info["has_video"]:
        return str(src)                      # already audio only (MP3, WAV, M4A...)
    for ext, codec in ((".mp3", ["-c:a", "libmp3lame", "-q:a", "2"]), (".m4a", ["-c:a", "aac", "-b:a", "192k"])):
        out = Path(tmp_dir) / f"music{ext}"
        result = subprocess.run(
            ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-i", str(src), "-vn", "-ac", "2", "-ar", "44100", *codec, str(out)],
            capture_output=True, timeout=300)
        if result.returncode == 0 and out.exists():
            return str(out)
    raise ValueError("Could not extract the audio from that video.")


def find_beats(audio_path):
    """Strong beat times (seconds) from rms.py. librosa is imported lazily (it is slow to load)."""
    from rms import detect_beats
    return detect_beats(audio_path)


# ----------------------------- beat rules ------------------------------------

def merge_close_beats(beats, min_gap=None):
    """Keep a beat only if it is at least min_gap after the last kept one."""
    min_gap = config.MIN_BEAT_GAP if min_gap is None else min_gap
    kept = []
    for beat in sorted(float(b) for b in beats):
        if not kept or beat - kept[-1] >= min_gap - 1e-9:
            kept.append(beat)
    return kept


class PatchPool:
    """
    Hands out clean footage (no headshot nearby) for lead-ups that are too short.
    Footage is taken nearest-earlier first, from the END of a zone backwards, and a
    zone is used up before the next call reuses it - so repeats look different.
    When everything has been used once, footage is allowed to repeat.
    """

    def __init__(self, zones):
        self.zones = list(zones)
        self.used = [0.0] * len(self.zones)

    def _order(self, ref):
        def key(i):
            zs, ze = self.zones[i]
            return (0, ref - ze) if ze <= ref else (1, zs - ref)
        return sorted(range(len(self.zones)), key=key)

    def take(self, need, avoid_start, avoid_end):
        """Returns ([(start, end)...] ascending, still_missing_seconds)."""
        out = []
        for attempt in (0, 1):
            for zi in self._order(avoid_start):
                if need < config.MIN_PATCH:
                    break
                zs, ze = self.zones[zi]
                top = ze - self.used[zi]
                if top > avoid_start and zs < avoid_end:     # never overlap the clip it belongs to
                    top = min(top, avoid_start)
                if top - zs < config.MIN_PATCH:
                    continue
                take = min(need, top - zs)
                out.append((top - take, top))
                self.used[zi] += take
                need -= take
            if need < config.MIN_PATCH or attempt == 1:
                break
            self.used = [0.0] * len(self.zones)           # everything used once: allow reuse
        return sorted(out), max(need, 0.0)


# ----------------------------- the plan --------------------------------------

def plan_beatsync(stamps, beats, source_duration):
    """
    Returns {"clips": [Clip...], "length": seconds of finished video,
             "music_offset": seconds to skip at the start of the song, "beats_used": n}
    """
    stamps = sorted({round(float(s), 3) for s in stamps})
    if not stamps:
        raise ValueError("No headshot timestamps were sent.")
    kept = merge_close_beats(beats)
    if not kept:
        raise ValueError("No usable beats were found in that audio.")

    offset = max(0.0, kept[0] - config.MAX_INTRO_SECONDS)   # long silent intro: start the edit earlier in the song
    times = [b - offset for b in kept]

    pool = PatchPool(clean_zones(stamps, source_duration))
    tail = config.TAIL
    clips, prev_end = [], 0.0
    for i, beat in enumerate(times):
        h = i % len(stamps)
        stamp = stamps[h]
        lead = max(0.0, beat - prev_end)                    # footage needed before the headshot

        floor = 0.0 if h == 0 else max(0.0, stamps[h - 1] + config.START_MARGIN)
        usable = min(lead, max(0.0, stamp - floor))         # real lead-up we can show
        main = Clip(src_start=stamp - usable, dur=usable + tail, windows=[(usable, usable + tail)])

        piece = [main]
        deficit = lead - usable
        if deficit > 0.02:
            taken, missing = pool.take(deficit, main.src_start, main.src_start + main.dur)
            piece = [Clip(a, b - a) for a, b in taken] + [main]
            if missing > 0.02:
                piece[0].freeze = missing                   # last resort: hold the first frame
        clips.extend(piece)
        prev_end = beat + tail

    return {"clips": clips, "length": prev_end, "music_offset": offset, "beats_used": len(times)}
