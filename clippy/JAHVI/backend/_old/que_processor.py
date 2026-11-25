import os, subprocess, uuid
from fastapi import Depends
from sqlalchemy.orm import Session
from extraction import extract_que_manager, set_job_id
from database import ExtractReqLogs, progress_Logs, get_db
from job import max_job, max_queue
from extraction import ExtractRequest
from extraction import E1, E2, E3   

def process_que(db: Session = Depends(get_db)):
    job_id = str(uuid.uuid4())
    que = extract_que_manager()
    video_url = que["video_url"]
    user = que["user"]
    current_job = que.created_at
    options = ExtractRequest(
        headshot_timestamps=que["timestamps"],
        max_gap=que["exact_gap"],
        ratio=que["ratio"],
        patch=que["patch"],
    )

    if max_queue() >= 2:         
        return {"msg": "max queue reached"}
    if patch:
        set_job_id(user, job_id, db, "extract")
        E2(options, video_url, user, db)
    else if not patch:
        set_job_id(user, job_id, db, "extract")
        E1(options, video_url, user, db)
