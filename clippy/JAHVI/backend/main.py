"""
main.py
The one Jahvi server: auth, credits, headshot detection, the three edit pages (Dashboard, Extraction
Lab, Beat Sync Lab), the shared job/queue routes - plus two background threads:
the queue drainer (jobs.py) and the storage sweeper (sweeper.py).
Run:  uvicorn main:app --port 8001
"""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
import jobs
import sweeper
from beatsync import beatsync_router
from cv4 import auto_detect_router
from dashboard import dashboard_router
from database import init_db
from extraction import extraction_router
from login import router as login_router
from me import router as account_router
from user_extract_vid import user_extract_vid
from signup import router as signup_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                    # creates the new jobs / effect_presets tables if they don't exist
    jobs.startup_reset()         # slot counter back to 0; jobs that died with the last server are refunded
    stop = threading.Event()
    jobs.start_drainer(stop)
    sweeper.start_sweeper(stop)
    yield
    stop.set()


app = FastAPI(title="Jahvi", lifespan=lifespan)

# Explicit origins are required because the refresh-token cookie uses credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

for router in (
    jobs.jobs_router,
    dashboard_router,
    extraction_router,
    beatsync_router,
    auto_detect_router,
    user_extract_vid,
    login_router,
    account_router,signup_router,
):
    app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
