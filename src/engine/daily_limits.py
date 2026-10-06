"""Daily confirmed-submission accounting — DATA_MODEL.md §12 / WORKFLOW_ENGINE.md §27/§28.

Against the Phase 1 `daily_limits_v2` table (date PK; indeed_count,
other_count, total_count, confirmed_count, attempt_count).
"""

from __future__ import annotations

import sqlite3

from . import db as enginedb
from .policy import DAILY_CONFIRMED_TARGET


def _ensure_row(conn: sqlite3.Connection, date: str, now: str) -> None:
    conn.execute(
        """
        INSERT INTO daily_limits_v2 (date, updated_at)
        VALUES (?, ?)
        ON CONFLICT(date) DO NOTHING
        """,
        (date, now),
    )


def get_confirmed_count(conn: sqlite3.Connection, now: str | None = None) -> int:
    now = now or enginedb.now_iso()
    date = enginedb.today_str(now)
    row = conn.execute(
        "SELECT confirmed_count FROM daily_limits_v2 WHERE date = ?", (date,)
    ).fetchone()
    return row["confirmed_count"] if row else 0


def has_daily_capacity(conn: sqlite3.Connection, now: str | None = None) -> bool:
    """WORKFLOW_ENGINE.md §27: read current confirmed count; verify
    remaining capacity; claim only if capacity remains."""
    return get_confirmed_count(conn, now) < DAILY_CONFIRMED_TARGET


def record_attempt_claimed(conn: sqlite3.Connection, now: str | None = None) -> None:
    now = now or enginedb.now_iso()
    date = enginedb.today_str(now)
    _ensure_row(conn, date, now)
    conn.execute(
        "UPDATE daily_limits_v2 SET attempt_count = attempt_count + 1, updated_at = ? WHERE date = ?",
        (now, date),
    )


def record_confirmed_submission(conn: sqlite3.Connection, channel: str, now: str | None = None) -> None:
    """WORKFLOW_ENGINE.md §28: SUBMITTED with valid evidence = +1. All other
    outcomes = +0 (handled simply by callers only invoking this on SUBMITTED).
    """
    now = now or enginedb.now_iso()
    date = enginedb.today_str(now)
    _ensure_row(conn, date, now)
    platform_column = "indeed_count" if channel == "indeed" else "other_count"
    conn.execute(
        f"""
        UPDATE daily_limits_v2
        SET confirmed_count = confirmed_count + 1,
            total_count = total_count + 1,
            {platform_column} = {platform_column} + 1,
            updated_at = ?
        WHERE date = ?
        """,
        (now, date),
    )
