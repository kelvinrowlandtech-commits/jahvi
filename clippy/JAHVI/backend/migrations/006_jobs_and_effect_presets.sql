-- 006: one job table for all 3 pages + the effect table.
-- The server creates these automatically on startup (SQLAlchemy create_all); this file is the same
-- thing in SQL if you prefer to run it by hand. The old jobprogress / queued_jobs tables are no
-- longer used and can be dropped whenever you like.

CREATE TABLE IF NOT EXISTS jobs (
    id            VARCHAR(36) PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    page          VARCHAR(20) NOT NULL,
    status        VARCHAR(12) NOT NULL DEFAULT 'queued',
    stage         VARCHAR(32) NOT NULL DEFAULT 'queued',
    percentage    INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    params        TEXT NOT NULL DEFAULT '{}',
    upload_path   TEXT,
    audio_path    TEXT,
    output_file   VARCHAR(80),
    cost          INTEGER NOT NULL DEFAULT 2,
    refunded      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_jobs_user_id ON jobs (user_id);
CREATE INDEX IF NOT EXISTS ix_jobs_status_created ON jobs (status, created_at);

CREATE TABLE IF NOT EXISTS jobcount (
    id        SERIAL PRIMARY KEY,
    job_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS effect_presets (
    id              SERIAL PRIMARY KEY,
    class_name      VARCHAR(60) NOT NULL,
    name            VARCHAR(80) NOT NULL,
    style           VARCHAR(200),
    global_filter   TEXT NOT NULL DEFAULT '',
    headshot_filter TEXT NOT NULL DEFAULT '',
    active          BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_effect_presets_class_name ON effect_presets (class_name);
