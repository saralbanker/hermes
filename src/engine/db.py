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


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_str(now: str | None = None) -> str:
    return (now or now_iso())[:10]


def connect(db_path: str = ":memory:", *, ensure_schema: bool = True) -> sqlite3.Connection:
    """Open a connection to the v2 schema.

    For `:memory:` or a fresh file, applies db/migrations/0001_opportunity_model.sql
    (idempotent — safe against an already-migrated file too).
    """
    # autocommit mode: the engine manages transactions explicitly with
    # BEGIN IMMEDIATE / COMMIT / ROLLBACK (claim.py, transitions.py), which
    # conflicts with sqlite3's default implicit-transaction behavior.
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if ensure_schema:
        conn.executescript(MIGRATION_SQL.read_text())
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
