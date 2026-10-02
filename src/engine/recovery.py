"""Crash recovery + reconciliation.

WORKFLOW_ENGINE.md §44 (Process Crash Recovery), §45 (Lease Recovery),
§103-105 (Late Browser Result / Late Success vs Retry / Worker Fencing),
DATA_MODEL.md §20 (Recovery Semantics).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

from . import db as enginedb
from .enums import ApplicationState, ExecutionPhase
from .reserve import rebuild_work_queue
from .transitions import (
    TransitionResult,
    record_retryable_failure,
    record_submission_unconfirmed,
)


class RecoveryAction(str, Enum):
    RELEASE_REQUEUE = "RELEASE_REQUEUE"
    RETRY_IF_SAFE = "RETRY_IF_SAFE"
    MARK_UNCONFIRMED_RECONCILE = "MARK_UNCONFIRMED_RECONCILE"
    FINALIZE_NO_RETRY = "FINALIZE_NO_RETRY"


@dataclass(frozen=True)
class RecoveredAttempt:
    attempt_id: int
    action: RecoveryAction
    result: TransitionResult | None


def find_expired_leases(conn: sqlite3.Connection, now: str | None = None) -> list[sqlite3.Row]:
    now = now or enginedb.now_iso()
    return conn.execute(
        """
        SELECT * FROM application_attempts
        WHERE attempt_state IN ('CLAIMED', 'STARTED')
          AND lease_until IS NOT NULL AND lease_until < ?
          AND outcome IS NULL
        """,
        (now,),
    ).fetchall()


def classify_recovery(attempt: sqlite3.Row) -> RecoveryAction:
    """WORKFLOW_ENGINE.md §45: this is a direct read of the expired lease's
    attempt. `outcome`, if already written, overrides phase-based inference."""
    if attempt["outcome"] is not None:
        return RecoveryAction.FINALIZE_NO_RETRY

    phase = attempt["execution_phase"]
    if phase == ExecutionPhase.NOT_STARTED.value:
        return RecoveryAction.RELEASE_REQUEUE
    if phase == ExecutionPhase.EXTERNAL_WORK_STARTED.value:
        return RecoveryAction.RETRY_IF_SAFE
    # SUBMIT_INTENT (or the terminal OBSERVED phase reached with no outcome,
    # which should not happen but is treated the same conservative way)
    return RecoveryAction.MARK_UNCONFIRMED_RECONCILE


def recover_expired_lease(conn: sqlite3.Connection, attempt: sqlite3.Row, now: str | None = None) -> RecoveredAttempt:
    now = now or enginedb.now_iso()
    action = classify_recovery(attempt)
    attempt_id = attempt["attempt_id"]
    opportunity_id = attempt["opportunity_id"]

    if action is RecoveryAction.FINALIZE_NO_RETRY:
        return RecoveredAttempt(attempt_id, action, None)

    if action is RecoveryAction.RELEASE_REQUEUE:
        result = _release_not_started(conn, attempt_id, opportunity_id, now)
        return RecoveredAttempt(attempt_id, action, result)

    if action is RecoveryAction.RETRY_IF_SAFE:
        result = record_retryable_failure(
            conn, attempt_id, opportunity_id, attempt["attempt_number"],
            error_code="lease_expired", error_class=None, now=now,
        )
        return RecoveredAttempt(attempt_id, action, result)

    # MARK_UNCONFIRMED_RECONCILE: §41/§43 — never treat a missing submitted
    # row as proof no submission occurred; preserve as SUBMISSION_UNCONFIRMED
    # and route to reconciliation (§40), never blindly retry.
    result = record_submission_unconfirmed(conn, attempt_id, opportunity_id, now)
    return RecoveredAttempt(attempt_id, action, result)


def _release_not_started(
    conn: sqlite3.Connection, attempt_id: int, opportunity_id: int, now: str
) -> TransitionResult:
    """A lease that expired before any external work began is simply
    released — §45 "Release/requeue when durable state proves it." This
    attempt's execution_phase stays NOT_STARTED, so (Patch 2) it never
    counted against MAX_ATTEMPTS and still doesn't here."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            UPDATE application_attempts
            SET attempt_state = 'FINISHED', error_class = 'lease_expired_not_started',
                finished_at = ?, updated_at = ?
            WHERE attempt_id = ?
            """,
            (now, now, attempt_id),
        )
        updated = conn.execute(
            """
            UPDATE opportunities
            SET application_state = 'READY', current_attempt_id = NULL, updated_at = ?
            WHERE opportunity_id = ? AND current_attempt_id = ?
            """,
            (now, opportunity_id, attempt_id),
        )
        conn.execute("COMMIT")
        return TransitionResult(updated.rowcount == 0,
                                 ApplicationState.READY.value if updated.rowcount else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def run_startup_recovery(conn: sqlite3.Connection, now: str | None = None) -> dict:
    """WORKFLOW_ENGINE.md §44 Process Crash Recovery sequence (the subset
    owned by this module: lease inspection -> reconciliation -> queue
    rebuild; source/model/browser health and normal claims resume outside
    this function, in the Phase-3 live loop). Idempotent and safe to run
    twice (§158 Recovery Idempotency Test): a second run finds no expired,
    unresolved leases left to act on."""
    now = now or enginedb.now_iso()
    expired = find_expired_leases(conn, now)
    recovered = [recover_expired_lease(conn, attempt, now) for attempt in expired]
    requeued = rebuild_work_queue(conn, now)
    return {"recovered_leases": len(recovered), "recovered": recovered, "work_queue_rows": requeued}


def expire_stale_opportunities(conn: sqlite3.Connection, now: str | None = None) -> int:
    """WORKFLOW_ENGINE.md §77 Expiration Sweep: opportunities past the
    21-day horizon move to EXPIRED and drop out of the queue. Does not
    touch an opportunity with a live attempt (APPLYING/AWAITING_RECONCILIATION) —
    WORKFLOW_ENGINE.md §12: "A live attempt that began before the boundary
    is governed by its attempt lifecycle and actual external result," not
    by the age sweep."""
    from .age import is_within_horizon

    now = now or enginedb.now_iso()
    candidates = conn.execute(
        """
        SELECT opportunity_id, age_reference_at FROM opportunities
        WHERE application_state IN ('OBSERVED', 'EVALUATING', 'READY')
        """
    ).fetchall()
    expired_ids = [
        row["opportunity_id"] for row in candidates
        if not is_within_horizon(row["age_reference_at"], now)
    ]
    for opportunity_id in expired_ids:
        conn.execute(
            "UPDATE opportunities SET application_state = 'EXPIRED', age_band = 'EXPIRED', updated_at = ? "
            "WHERE opportunity_id = ?",
            (now, opportunity_id),
        )
        conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
    return len(expired_ids)
