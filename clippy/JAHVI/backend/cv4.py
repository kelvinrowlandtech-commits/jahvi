import os
import threading
from collections import deque

import cv2
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import config
from helper import save_video
from jobs import disk_has_room
from me import get_current_user
from database import User

auto_detect_router = APIRouter(prefix="/api", tags=["headshot detection"])

# Detection runs OpenCV inside the request, so only a couple may run at once; the rest are told to retry.
# This keeps it from starving the video-editing jobs.
_DETECT_SLOTS = threading.BoundedSemaphore(config.MAX_CONCURRENT_DETECTIONS)

REF_W, REF_H = 1024, 576
REF_ROI = (485, 540, 72, 102)
REF_STRIP = (380, 640, 0, 200)
INTERVAL = 0.3
CONTRAST_MIN = 50
AVG1_MIN = 40
AVG2_STATIC = 80
MERGE_GAP = 1.0


def _scale_roi(width: int, height: int, roi: tuple[int, int, int, int]):
    x1, x2, y1, y2 = roi
    return (
        int(x1 * width / REF_W),
        int(x2 * width / REF_W),
        int(y1 * height / REF_H),
        int(y2 * height / REF_H),
    )


def detect_headshots(video_path: str) -> list[float]:
    video = cv2.VideoCapture(video_path)
    if not video.isOpened():
        video.release()
        raise ValueError("The uploaded file could not be opened as a video.")
    try:
        frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = video.get(cv2.CAP_PROP_FPS) or 30.0
        duration = frames / fps if fps > 0 else 0
        width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if duration <= 0 or width <= 0 or height <= 0:
            raise ValueError("The uploaded video has no readable frames.")

        x1, x2, y1, y2 = _scale_roi(width, height, REF_ROI)
        sx1, sx2, sy1, sy2 = _scale_roi(width, height, REF_STRIP)
        hits = []
        sample_count = int(2 / INTERVAL) + 1
        sample_every = max(1, int(round(fps * INTERVAL)))
        first_frame = int(0.5 * fps)
        video.set(cv2.CAP_PROP_POS_FRAMES, first_frame)
        frame_index = first_frame
        next_sample_frame = first_frame
        sample_index = 0
        gray_window = deque(maxlen=sample_count)

        def check_window(gray_frames, start_index):
            if len(gray_frames) < 3:
                return
            current_time = 0.5 + start_index * INTERVAL
            template = gray_frames[0][y1:y2, x1:x2]
            search_strip = gray_frames[0][sy1:sy2, sx1:sx2]
            if template.size == 0 or search_strip.shape[0] < template.shape[0] or search_strip.shape[1] < template.shape[1]:
                raise ValueError("The video resolution is too small for headshot detection.")

            contrast = float(template.std())
            scores = []
            for gray in gray_frames:
                strip = gray[sy1:sy2, sx1:sx2]
                result = cv2.matchTemplate(strip, template, cv2.TM_CCOEFF_NORMED)
                scores.append(cv2.minMaxLoc(result)[1] * 100)

            avg1_scores = scores[:max(1, int(1 / INTERVAL) + 1)]
            avg1 = sum(avg1_scores) / len(avg1_scores)
            avg2 = sum(scores) / len(scores)
            if contrast >= CONTRAST_MIN and avg1 >= AVG1_MIN and avg2 <= AVG2_STATIC:
                hits.append(round(current_time, 1))

        while True:
            ok, frame = video.read()
            if not ok:
                break
            if frame_index >= next_sample_frame:
                gray_window.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                if len(gray_window) == sample_count:
                    check_window(list(gray_window), sample_index - sample_count + 1)
                sample_index += 1
                next_sample_frame += sample_every
            frame_index += 1

        tail_start_index = sample_index - len(gray_window)
        last_full_start = sample_index - sample_count
        for start_index in range(max(0, last_full_start + 1), sample_index - 2):
            offset = start_index - tail_start_index
            check_window(list(gray_window)[offset:], start_index)

        merged = []
        for timestamp in hits:
            if not merged or timestamp - merged[-1] > MERGE_GAP:
                merged.append(timestamp)
        return merged
    finally:
        video.release()


@auto_detect_router.post("/detect-headshots")
def detect_headshots_route(
    video: UploadFile = File(...),
    _user: User = Depends(get_current_user),
):
    if not disk_has_room():
        raise HTTPException(status_code=503, detail="Our servers are almost full right now. Please try again in a little while.")
    if not _DETECT_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="Headshot detection is busy right now. Please try again in a moment, or add the bars by hand.")
    saved_video = None
    try:
        saved_video = save_video(video)
        if not saved_video:
            raise HTTPException(status_code=400, detail="A video upload is required.")
        raw = detect_headshots(saved_video)
        timestamps = sorted({max(0.0, round(t - config.DETECT_SHIFT_BACK, 1)) for t in raw})
        return {"timestamps": timestamps, "count": len(timestamps)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        _DETECT_SLOTS.release()
        if saved_video and os.path.exists(saved_video):
            os.remove(saved_video)
