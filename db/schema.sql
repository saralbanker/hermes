CREATE TABLE IF NOT EXISTS jobs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    url                     TEXT UNIQUE NOT NULL,
    company                 TEXT NOT NULL,
    title                   TEXT NOT NULL,
    location                TEXT,
    job_board               TEXT,
    description             TEXT,
    salary_min              INTEGER,
    salary_max              INTEGER,
    date_posted             TEXT,

    score                   REAL,
    score_reason            TEXT,

    resume_variant          TEXT,
    cover_letter_path       TEXT,

    status                  TEXT NOT NULL DEFAULT 'discovered',
    status_reason           TEXT,
    applied_at              TEXT,
    screenshot_path         TEXT,

    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_limits (
    date            TEXT PRIMARY KEY,
    linkedin_count  INTEGER NOT NULL DEFAULT 0,
    other_count     INTEGER NOT NULL DEFAULT 0,
    total_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TRIGGER IF NOT EXISTS update_jobs_timestamp
AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = datetime('now') WHERE id = NEW.id;
END;
