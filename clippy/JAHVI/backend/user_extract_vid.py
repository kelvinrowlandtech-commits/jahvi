from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import ExtractReqLogs, get_db
from jwt_handler import decode_token


user_extract_vid = APIRouter()


@user_extract_vid.get("/fetch_extracts")
def fetch_extracts(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="couldnt validate user",
        )

    payload = decode_token(token, expected_type="access")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    jobs = (
        db.query(ExtractReqLogs)
        .filter(
            ExtractReqLogs.user_id == user_id,
            or_(
                ExtractReqLogs.status == "done",
                ExtractReqLogs.status == "uploaded",
                ExtractReqLogs.percent == 100,
                ExtractReqLogs.edited_vid_url.isnot(None),
            ),
            ExtractReqLogs.edited_vid_url != "pending",
        )
        .order_by(ExtractReqLogs.created_at.desc())
        .all()
    )

    videos = []
    for job in jobs:
        url = job.edited_vid_url or job.video_url
        if url and url != "pending":
            videos.append(url)

    if not videos:
        return {"message": "u have no jobs", "videos": []}

    return {"videos": videos}

