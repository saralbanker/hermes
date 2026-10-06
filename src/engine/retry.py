"""Retry eligibility, backoff, and attempt counting.

WORKFLOW_ENGINE.md §22 (Retry Eligibility — the authoritative opportunity-
level predicate), §23 (Retry Backoff), and the Patch 2 correction: an
attempt only counts against `attempts < MAX_ATTEMPTS` if its
`execution_phase` advanced past NOT_STARTED.
"""

from __future__ import annotations

import sqlite3

from . import db as enginedb
from .age import is_within_horizon
from .enums import ApplicationState, CONFIRMED_OUTCOMES, Outcome
from .policy import MAX_ATTEMPTS, MAX_VALIDATION_ATTEMPTS, RETRY_BACKOFF_SECONDS

# A pre-submission gate finding or job-data-specific gate exception (see
# src/submission_gate.py's classify_gate_outcome), as recorded in
# application_attempts.error_class by transitions.record_validation_finding.
VALIDATION_ERROR_CLASSES = frozenset({"gate_finding", "gate_job_data_error"})


def _manual_released_at(conn: sqlite3.Connection, opportunity_id: int) -> str | None:
    row = conn.execute(
        "SELECT manual_released_at FROM opportunities WHERE opportunity_id = ?",
        (opportunity_id,),
    ).fetchone()
    return row["manual_released_at"] if row else None


def countable_attempt_count(conn: sqlite3.Connection, opportunity_id: int) -> int:
    """WORKFLOW_ENGINE.md §22 (Patch 2): attempts whose execution_phase
    advanced past NOT_STARTED — i.e. external work actually began. Attempts
    created at/before a manual_released_at timestamp (if set) are excluded —
    a release grants a genuinely fresh budget, not a permanently truncated
    one (both this counter and countable_validation_failure_count must reset
    together on release, since MANUAL_REVIEW is reachable via either one).
    """
    released_at = _manual_released_at(conn, opportunity_id)
    if released_at:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM application_attempts
            WHERE opportunity_id = ? AND execution_phase != 'NOT_STARTED' AND created_at > ?
            """,
            (opportunity_id, released_at),
        ).fetchone()
        return row["n"]
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM application_attempts
        WHERE opportunity_id = ? AND execution_phase != 'NOT_STARTED'
        """,
        (opportunity_id,),
    ).fetchone()
    return row["n"]


def countable_validation_failure_count(conn: sqlite3.Connection, opportunity_id: int) -> int:
    """Attempts tagged as a pre-submission gate finding or job-data gate exception,
    counted by error_class — independent of execution_phase. Attempts created at/before
    a manual_released_at timestamp (if set) are excluded — a release grants a genuinely
    fresh budget, not a permanently truncated one."""
    released_at = _manual_released_at(conn, opportunity_id)
    if released_at:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM application_attempts WHERE opportunity_id = ? "
            "AND error_class IN (?, ?) AND created_at > ?",
            (opportunity_id, *VALIDATION_ERROR_CLASSES, released_at)).fetchone()["n"]
    return conn.execute(
        "SELECT COUNT(*) AS n FROM application_attempts WHERE opportunity_id = ? AND error_class IN (?, ?)",
        (opportunity_id, *VALIDATION_ERROR_CLASSES)).fetchone()["n"]


def has_confirmed_submission(conn: sqlite3.Connection, opportunity_id: int) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM application_attempts
        WHERE opportunity_id = ? AND outcome IN (?, ?)
        """,
        (opportunity_id, *[o.value for o in CONFIRMED_OUTCOMES]),
    ).fetchone()
    return row["n"] > 0


def is_retry_eligible(conn: sqlite3.Connection, opportunity_id: int, now: str | None = None) -> bool:
    """WORKFLOW_ENGINE.md §22, full predicate."""
    opp = enginedb.fetch_opportunity(conn, opportunity_id)
    if opp is None:
        return False
    if opp["application_state"] != ApplicationState.READY.value:
        return False
    if has_confirmed_submission(conn, opportunity_id):
        return False

    # The retry_eligible bit (DATA_MODEL.md §7.4) gates ordinary same-route
    # bounded retry after RETRYABLE_FAILURE. CHANNEL_BLOCKED is route-scoped
    # (§106 Channel-Scoped Retry, §107 Route Fallback): record_channel_blocked
    # already decides whether to return the opportunity to READY (alternate
    # route available) or MANUAL_REVIEW (none), so an opportunity that made
    # it back to READY after a channel block has already been vetted — this
    # predicate must not re-block it via a bit that was deliberately 0 for a
    # different (route-health) reason.
    latest = enginedb.fetch_latest_attempt(conn, opportunity_id)
    if (
        latest is not None
        and latest["outcome"] == Outcome.RETRYABLE_FAILURE.value
        and latest["retry_eligible"] != 1
    ):
        return False

    if countable_attempt_count(conn, opportunity_id) >= MAX_ATTEMPTS:
        return False

    if not is_within_horizon(opp["age_reference_at"], now):
        return False

    queue_row = conn.execute(
        "SELECT next_attempt_at FROM work_queue WHERE opportunity_id = ?",
        (opportunity_id,),
    ).fetchone()
    next_attempt_at = queue_row["next_attempt_at"] if queue_row else None
    if next_attempt_at is not None and next_attempt_at > (now or enginedb.now_iso()):
        return False

    return True


def compute_backoff_seconds(attempt_number: int) -> int | None:
    """WORKFLOW_ENGINE.md §23. Returns None when no further automatic retry
    is scheduled (attempt_number has reached MAX_ATTEMPTS)."""
    return RETRY_BACKOFF_SECONDS.get(attempt_number)


def compute_next_attempt_at(attempt_number: int, now: str | None = None) -> str | None:
    import datetime as dt

    backoff = compute_backoff_seconds(attempt_number)
    if backoff is None:
        return None
    base = dt.datetime.fromisoformat((now or enginedb.now_iso()))
    return (base + dt.timedelta(seconds=backoff)).strftime("%Y-%m-%d %H:%M:%S")
