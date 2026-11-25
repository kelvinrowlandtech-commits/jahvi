import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from environment import load_environment

load_environment()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
if not DATABASE_URL.startswith("postgresql"):
    raise RuntimeError("DATABASE_URL must point to a PostgreSQL database")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()



DEFAULT_CREDITS = 10


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    full_name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    credits = Column(Integer, nullable=False, default=DEFAULT_CREDITS, server_default=str(DEFAULT_CREDITS))


class SignupSecurity(Base):
    __tablename__ = "signup_security"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_address = Column(String(45), nullable=False, index=True)
    device_id = Column(String(128), nullable=False, index=True)
    success = Column(Boolean, nullable=False, default=False)

class ExtractReqLogs(Base):
    __tablename__ = "extractreqlogs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    status = Column(String, nullable=True)
    percent = Column(Integer, nullable=True)
    edited_vid_url = Column(Text, nullable=True)
    video_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Job(Base):
    """One edit request from any of the 3 pages. Queued jobs are just rows with status='queued'."""
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True)                 # uuid
    user_id = Column(Integer, nullable=False, index=True)
    page = Column(String(20), nullable=False)                 # dashboard | extraction | beatsync
    status = Column(String(12), nullable=False, default="queued")   # queued | processing | completed | failed
    stage = Column(String(32), nullable=False, default="queued")
    percentage = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    params = Column(Text, nullable=False, default="{}")       # JSON: everything the recipe needs
    upload_path = Column(Text, nullable=True)
    audio_path = Column(Text, nullable=True)
    output_file = Column(String(80), nullable=True)           # file name inside outputs/
    cost = Column(Integer, nullable=False, default=2)
    refunded = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)


class JobCount(Base):
    """Single row (id=1): how many jobs are rendering right now."""
    __tablename__ = "jobcount"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_count = Column(Integer, nullable=False, default=0)


class EffectPreset(Base):
    """
    One effect = two raw FFmpeg filter strings.
      global_filter   runs on the whole video
      headshot_filter runs only around each headshot; put {ENABLE} where the
                      enable expression goes, e.g.  eq=contrast=1.3:enable='{ENABLE}'
    """
    __tablename__ = "effect_presets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_name = Column(String(60), nullable=False, index=True)   # group shown in the picker (Rage, Cinematic, Funk...)
    name = Column(String(80), nullable=False)                     # this effect's name
    style = Column(String(200), nullable=True)                    # small description
    global_filter = Column(Text, nullable=False, default="")
    headshot_filter = Column(Text, nullable=False, default="")
    active = Column(Boolean, nullable=False, default=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    print("made db connection")
