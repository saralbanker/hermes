import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "applications.db"
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Columns added after the original schema. init_db() adds any that are missing,
# so existing databases upgrade in place.
MIGRATION_COLUMNS = {
    "apply_channel":    "TEXT",   # indeed | greenhouse | lever | ashby | email
    "ats_meta":         "TEXT",   # JSON: board token, posting id, apply email
    "location_reason":  "TEXT",   # why the location filter accepted the job
    "response_status":  "TEXT",   # positive | rejection | ack (from employer email)
    "response_subject": "TEXT",
    "response_at":      "TEXT",
}


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text())
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    for col, col_type in MIGRATION_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
    conn.commit()
    conn.close()
    DB_PATH.chmod(0o600)  # owner-only: contains cover letters + application history


def upsert_job(job: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO jobs
            (url, company, title, location, job_board,
             description, salary_min, salary_max, date_posted,
             apply_channel, ats_meta, location_reason, status, status_reason)
        VALUES
            (:url, :company, :title, :location, :job_board,
             :description, :salary_min, :salary_max, :date_posted,
             :apply_channel, :ats_meta, :location_reason, :status, :status_reason)
        """,
        {"apply_channel": None, "ats_meta": None, "location_reason": None,
         "status": "discovered", "status_reason": None, **job},
    )
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    return rowid


def update_job(url: str, fields: dict):
    cols = ", ".join(f"{k} = :{k}" for k in fields)
    conn = get_conn()
    conn.execute(
        f"UPDATE jobs SET {cols} WHERE url = :_url",
        {**fields, "_url": url},
    )
    conn.commit()
    conn.close()


def get_jobs_by_status(status: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = ? ORDER BY score DESC NULLS LAST",
        (status,),
    ).fetchall()
    conn.close()
    return rows


def get_jobs_above_score(min_score: float) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE score >= ? AND status = 'scored' ORDER BY score DESC",
        (min_score,),
    ).fetchall()
    conn.close()
    return rows


def get_all_urls() -> set:
    conn = get_conn()
    rows = conn.execute("SELECT url FROM jobs").fetchall()
    conn.close()
    return {r["url"] for r in rows}


def count_today(board: str | None = None) -> int:
    from datetime import date

    today = date.today().isoformat()
    conn = get_conn()
    if board == "linkedin":
        row = conn.execute(
            "SELECT linkedin_count FROM daily_limits WHERE date = ?", (today,)
        ).fetchone()
        conn.close()
        return row["linkedin_count"] if row else 0
    else:
        row = conn.execute(
            "SELECT total_count FROM daily_limits WHERE date = ?", (today,)
        ).fetchone()
        conn.close()
        return row["total_count"] if row else 0


def increment_daily(board: str):
    from datetime import date

    today = date.today().isoformat()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO daily_limits (date, linkedin_count, other_count, total_count)
        VALUES (?, 0, 0, 0)
        ON CONFLICT(date) DO NOTHING
        """,
        (today,),
    )
    if board == "linkedin":
        conn.execute(
            "UPDATE daily_limits SET linkedin_count = linkedin_count + 1, "
            "total_count = total_count + 1 WHERE date = ?",
            (today,),
        )
    else:
        conn.execute(
            "UPDATE daily_limits SET other_count = other_count + 1, "
            "total_count = total_count + 1 WHERE date = ?",
            (today,),
        )
    conn.commit()
    conn.close()


def status_counts() -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
    ).fetchall()
    conn.close()
    return {r["status"]: r["cnt"] for r in rows}


def avg_score() -> float | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT AVG(score) as avg FROM jobs WHERE score IS NOT NULL"
    ).fetchone()
    conn.close()
    return round(row["avg"], 2) if row and row["avg"] else None


def get_daily_counts(date_str: str | None = None) -> dict:
    from datetime import date

    d = date_str or date.today().isoformat()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM daily_limits WHERE date = ?", (d,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"date": d, "linkedin_count": 0, "other_count": 0, "total_count": 0}
