"""Connection helper and small shared row-access utilities for the engine.

Deliberately separate from src/db.py (the legacy module backing the
currently-running pipeline, which targets the `jobs` table). This module
only ever touches the v2 tables created by db/migrations/0001_opportunity_model.sql.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION_SQL = ROOT / "db" / "migrations" / "0001_opportunity_model.sql"

# Columns added to the v2 schema after 0001_opportunity_model.sql was frozen. Mirrors
# src/db.py's MIGRATION_COLUMNS idiom for the legacy `jobs` table: since
# db/migrations/0001_opportunity_model.sql's CREATE TABLE statements are idempotent
# (IF NOT EXISTS) but cannot add a column to an already-created table, any new column
# goes here instead, applied via a PRAGMA table_info guard so an existing database
# upgrades in place without error.
OPPORTUNITIES_MIGRATION_COLUMNS = {
    # Release timestamp (§5.2/§5.3): the ONLY way an opportunity ever leaves
    # MANUAL_REVIEW (src/engine/recovery.py:release_manual_review). Also the cutoff
    # countable_attempt_count/countable_validation_failure_count (src/engine/retry.py)
    # filter attempts on — a release grants a genuinely fresh budget, not a
    # permanently truncated one.
    "manual_released_at": "DATETIME",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_str(now: str | None = None) -> str:
    return (now or now_iso())[:10]


def _apply_migration_columns(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
    for col, col_type in OPPORTUNITIES_MIGRATION_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col} {col_type}")


def connect(db_path: str = ":memory:", *, ensure_schema: bool = True) -> sqlite3.Connection:
    """Open a connection to the v2 schema.

    For `:memory:` or a fresh file, applies db/migrations/0001_opportunity_model.sql
    (idempotent — safe against an already-migrated file too), then any additive
    column migrations in OPPORTUNITIES_MIGRATION_COLUMNS.
    """
    # autocommit mode: the engine manages transactions explicitly with
    # BEGIN IMMEDIATE / COMMIT / ROLLBACK (claim.py, transitions.py), which
    # conflicts with sqlite3's default implicit-transaction behavior.
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if ensure_schema:
        conn.executescript(MIGRATION_SQL.read_text())
        _apply_migration_columns(conn)
    return conn


def fetch_opportunity(conn: sqlite3.Connection, opportunity_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM opportunities WHERE opportunity_id = ?", (opportunity_id,)
    ).fetchone()


def fetch_attempt(conn: sqlite3.Connection, attempt_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM application_attempts WHERE attempt_id = ?", (attempt_id,)
    ).fetchone()


def fetch_latest_attempt(conn: sqlite3.Connection, opportunity_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM application_attempts
        WHERE opportunity_id = ?
        ORDER BY attempt_number DESC
        LIMIT 1
        """,
        (opportunity_id,),
    ).fetchone()


def fetch_channel_health(conn: sqlite3.Connection, channel_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM channel_health WHERE channel_key = ?", (channel_key,)
    ).fetchone()
