"""
helper.py
Cutting plans shared by the Dashboard and the Extraction Lab (no database, no FFmpeg here).

Timeline of one clip:  [patch footage] -> [lead-up] -> HEADSHOT -> [TAIL]
All the knobs (TAIL, margins...) live in config.py.
"""
from config import (
    CLEAN_MARGIN, MERGE_EPS, MIN_LEAD, MIN_PATCH, START_MARGIN, TAIL,
)


def subtract(pool, cut_start, cut_end):
    """Remove [cut_start, cut_end] from a list of (start, end) free ranges."""
    out = []
    for s, e in pool:
        if cut_end <= s or cut_start >= e:
            out.append((s, e))
            continue
        if cut_start > s:
            out.append((s, cut_start))
        if cut_end < e:
            out.append((cut_end, e))
    return out


def clean_zones(stamps, duration=None):
    """
    Footage with no headshot nearby: the gaps between stamps (and before the first /
    after the last one), each shrunk by CLEAN_MARGIN so a headshot never leaks in.
    """
    zones = []
    bounds = [(None, stamps[0])] if stamps else []
    bounds += list(zip(stamps, stamps[1:]))
    if stamps and duration:
        bounds.append((stamps[-1], None))
    for a, b in bounds:
        s = 0.0 if a is None else a + CLEAN_MARGIN
        e = (duration if b is None else b - CLEAN_MARGIN)
        if e is not None and e - s >= MIN_PATCH:
            zones.append((s, e))
    return zones


def _main_segments(stamps, max_gap):
    """One segment per headshot: up to max_gap of lead-up, never into the previous headshot."""
    segs = []
    prev_stamp = None
    for stamp in stamps:
        end = stamp + TAIL
        if prev_stamp is None:
            start = max(0.0, stamp - max_gap)
        else:
            floor = max(prev_stamp + START_MARGIN, segs[-1]["end"])
            start = max(stamp - max_gap, floor)

        lead = stamp - start
        if segs and lead < min(MIN_LEAD, max_gap) - 1e-9:
            segs[-1]["end"] = max(segs[-1]["end"], end)
        else:
            segs.append({"stamp": stamp, "start": start, "end": end, "patches": []})
        prev_stamp = stamp
    return segs


def _fill_patches(segs, stamps, max_gap):
    """
    For clips whose lead-up is shorter than max_gap, borrow clean footage from the
    gaps between EARLIER stamps. Nearest gap first. Footage is never reused.
    """
    pool = [z for z in clean_zones(stamps)]
    for seg in segs:
        pool = subtract(pool, seg["start"], seg["end"])

    for seg in segs:
        need = max_gap - (seg["stamp"] - seg["start"])
        taken = []
        earlier = [z for z in pool if z[1] <= seg["stamp"]]
        for zs, ze in sorted(earlier, key=lambda z: z[1], reverse=True):
            if need < MIN_PATCH:
                break
            take = min(need, ze - zs)
            if take < MIN_PATCH:
                continue
            taken.append((ze - take, ze))
            need -= take
        for ts, te in taken:
            pool = subtract(pool, ts, te)
        seg["patches"] = sorted(taken)


def _merge_contiguous(trims):
    """Join cuts that touch in the source video so there is no pointless seam."""
    merged = []
    for s, e in trims:
        if merged and abs(s - merged[-1][1]) <= MERGE_EPS:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def plan_trims(stamps, max_gap, patch=False):
    """Returns the ordered list of (start, end) cuts to concatenate."""
    stamps = sorted({round(float(s), 3) for s in stamps})
    max_gap = float(max_gap)
    if not stamps:
        return []

    segs = _main_segments(stamps, max_gap)
    if patch:
        _fill_patches(segs, stamps, max_gap)

    trims = []
    for seg in segs:
        trims.extend(seg["patches"])
        trims.append((seg["start"], seg["end"]))
    return _merge_contiguous(trims)


# ============================ upload helper used by headshot detection (cv4.py) ====

def save_video(video):
    """Saves an upload to uploads/ and returns its path (None if there is no video). Size-capped."""
    import uuid

    import config as _config
    if not video:
        return None
    source = getattr(video, "file", video)
    path = _config.UPLOAD_DIR / f"detect_{uuid.uuid4()}.mp4"
    limit, written = _config.MAX_VIDEO_MB * 1024 * 1024, 0
    try:
        with open(path, "wb") as out:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    from fastapi import HTTPException
                    raise HTTPException(413, f"That file is too large (the limit is {_config.MAX_VIDEO_MB} MB).")
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return str(path)
