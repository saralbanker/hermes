"""State transitions — WORKFLOW_ENGINE.md §68 Transition Table, applied with
the lease-fencing contract (DATA_MODEL.md §19.1 / WORKFLOW_ENGINE.md §105).

Every function here writes the attempt's own result first (always allowed —
an attempt can always record evidence about itself), then attempts the
fenced opportunity-level write conditioned on `current_attempt_id` still
matching. A zero-row fenced update means a newer attempt already owns the
opportunity; per §19.1/§105 the write is discarded and the result is
reported as `fenced_out=True` for the caller to route to reconciliation
(§40) rather than silently applied.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import db as enginedb
from .age import compute_age_band
from .daily_limits import record_confirmed_submission
from .enums import ApplicationState, ExecutionPhase, Outcome
from .policy import MAX_ATTEMPTS, MAX_VALIDATION_ATTEMPTS, retry_eligible_bit
from .retry import countable_attempt_count, countable_validation_failure_count, compute_next_attempt_at


@dataclass(frozen=True)
class TransitionResult:
    fenced_out: bool
    new_application_state: str | None


def _fenced_opportunity_update(
    conn: sqlite3.Connection, opportunity_id: int, attempt_id: int, new_state: str, now: str
) -> bool:
    """Returns True if this write was applied (lease still owned)."""
    updated = conn.execute(
        """
        UPDATE opportunities
        SET application_state = ?, updated_at = ?
        WHERE opportunity_id = ? AND current_attempt_id = ?
        """,
        (new_state, now, opportunity_id, attempt_id),
    )
    return updated.rowcount > 0


def _finish_attempt(
    conn: sqlite3.Connection,
    attempt_id: int,
    *,
    outcome: Outcome,
    execution_phase: ExecutionPhase,
    error_code: str | None,
    error_class: str | None,
    now: str,
    **evidence_fields,
) -> None:
    retry_bit = retry_eligible_bit(outcome, error_class)
    fields = {
        "attempt_state": "FINISHED",
        "execution_phase": execution_phase.value,
        "outcome": outcome.value,
        "error_code": error_code,
        "error_class": error_class,
        "retry_eligible": retry_bit,
        "finished_at": now,
        "updated_at": now,
        **evidence_fields,
    }
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE application_attempts SET {set_clause} WHERE attempt_id = ?",
        (*fields.values(), attempt_id),
    )


def record_submitted(
    conn: sqlite3.Connection,
    attempt_id: int,
    opportunity_id: int,
    channel: str,
    *,
    confirmation_text: str | None = None,
    confirmation_url: str | None = None,
    now: str | None = None,
) -> TransitionResult:
    """§37 Submitted. Evidence sufficiency is the caller's responsibility
    (DATA_MODEL.md §7.7 "SUBMITTED requires sufficient evidence") — this
    function records the already-decided outcome."""
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _finish_attempt(
            conn, attempt_id, outcome=Outcome.SUBMITTED, execution_phase=ExecutionPhase.OBSERVED,
            error_code=None, error_class=None, now=now,
            confirmation_text=confirmation_text, confirmation_url=confirmation_url,
        )
        applied = _fenced_opportunity_update(
            conn, opportunity_id, attempt_id, ApplicationState.COMPLETED.value, now
        )
        if applied:
            conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
            record_confirmed_submission(conn, channel, now)
        conn.execute("COMMIT")
        return TransitionResult(not applied, ApplicationState.COMPLETED.value if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_already_applied(
    conn: sqlite3.Connection, attempt_id: int, opportunity_id: int, now: str | None = None
) -> TransitionResult:
    """§38 Already Applied: confirmed count += 0, but still COMPLETED/protected."""
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _finish_attempt(
            conn, attempt_id, outcome=Outcome.ALREADY_APPLIED, execution_phase=ExecutionPhase.OBSERVED,
            error_code=None, error_class=None, now=now,
        )
        applied = _fenced_opportunity_update(
            conn, opportunity_id, attempt_id, ApplicationState.COMPLETED.value, now
        )
        if applied:
            conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
        conn.execute("COMMIT")
        return TransitionResult(not applied, ApplicationState.COMPLETED.value if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_submission_unconfirmed(
    conn: sqlite3.Connection, attempt_id: int, opportunity_id: int, now: str | None = None
) -> TransitionResult:
    """§39 Submission Unconfirmed. Never immediately replay (§69 Forbidden
    Transitions)."""
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _finish_attempt(
            conn, attempt_id, outcome=Outcome.SUBMISSION_UNCONFIRMED,
            execution_phase=ExecutionPhase.SUBMIT_INTENT, error_code=None, error_class=None, now=now,
        )
        applied = _fenced_opportunity_update(
            conn, opportunity_id, attempt_id, ApplicationState.AWAITING_RECONCILIATION.value, now
        )
        if applied:
            conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
        conn.execute("COMMIT")
        return TransitionResult(not applied,
                                 ApplicationState.AWAITING_RECONCILIATION.value if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_retryable_failure(
    conn: sqlite3.Connection,
    attempt_id: int,
    opportunity_id: int,
    attempt_number: int,
    *,
    error_code: str | None = None,
    error_class: str | None = None,
    now: str | None = None,
) -> TransitionResult:
    """§68 Transition Table: retryable failure branches on attempt count.
    attempts < MAX_ATTEMPTS -> READY (requeued with backoff);
    attempts == MAX_ATTEMPTS -> MANUAL_REVIEW (§66)."""
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _finish_attempt(
            conn, attempt_id, outcome=Outcome.RETRYABLE_FAILURE,
            execution_phase=ExecutionPhase.EXTERNAL_WORK_STARTED,
            error_code=error_code, error_class=error_class, now=now,
        )
        countable = countable_attempt_count(conn, opportunity_id)
        exhausted = countable >= MAX_ATTEMPTS
        new_state = ApplicationState.MANUAL_REVIEW.value if exhausted else ApplicationState.READY.value

        applied = _fenced_opportunity_update(conn, opportunity_id, attempt_id, new_state, now)
        if applied:
            conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
            if not exhausted:
                _requeue_with_backoff(conn, opportunity_id, attempt_number, now)
        conn.execute("COMMIT")
        return TransitionResult(not applied, new_state if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _requeue_with_backoff(
    conn: sqlite3.Connection, opportunity_id: int, attempt_number: int, now: str
) -> None:
    """§68 Transition Table: "retryable failure (attempts < MAX) | READY |
    ... | delayed" — the queue row is re-created (not updated: claim_next
    already deleted it) with its backoff timer set, per §21 Retry Overlay:
    the opportunity retains its existing age band rather than joining a
    separate retry queue."""
    opp = enginedb.fetch_opportunity(conn, opportunity_id)
    age_band = compute_age_band(opp["age_reference_at"], now)
    next_attempt_at = compute_next_attempt_at(attempt_number, now)
    conn.execute(
        """
        INSERT INTO work_queue (
            opportunity_id, ready_state, age_band, priority_score,
            next_attempt_at, candidate_channel, queue_reason, updated_at
        ) VALUES (?, 'READY', ?, ?, ?, ?, 'retry_backoff', ?)
        """,
        (opportunity_id, age_band, opp["fit_score"], next_attempt_at,
         opp["latest_application_route"], now),
    )


def record_channel_blocked(
    conn: sqlite3.Connection,
    attempt_id: int,
    opportunity_id: int,
    channel_key: str,
    *,
    has_alternate_route: bool,
    now: str | None = None,
) -> TransitionResult:
    """§53/§67: attempt outcome CHANNEL_BLOCKED is distinct from
    channel_health.status = ANTIBOT_BLOCKED (set by the caller via
    channel_health.py, not here — this function only owns the attempt/
    opportunity dimensions)."""
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _finish_attempt(
            conn, attempt_id, outcome=Outcome.CHANNEL_BLOCKED,
            execution_phase=ExecutionPhase.EXTERNAL_WORK_STARTED,
            error_code=None, error_class="anti_bot_block", now=now,
        )
        # §50: a channel block does not force MANUAL_REVIEW by itself if
        # another legitimate route exists; the opportunity stays READY.
        new_state = ApplicationState.READY.value if has_alternate_route else ApplicationState.MANUAL_REVIEW.value
        applied = _fenced_opportunity_update(conn, opportunity_id, attempt_id, new_state, now)
        if applied and not has_alternate_route:
            conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
        conn.execute("COMMIT")
        return TransitionResult(not applied, new_state if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_unsupported_channel(
    conn: sqlite3.Connection, attempt_id: int, opportunity_id: int, now: str | None = None
) -> TransitionResult:
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _finish_attempt(
            conn, attempt_id, outcome=Outcome.UNSUPPORTED_CHANNEL,
            execution_phase=ExecutionPhase.EXTERNAL_WORK_STARTED,
            error_code=None, error_class=None, now=now,
        )
        applied = _fenced_opportunity_update(
            conn, opportunity_id, attempt_id, ApplicationState.OBSERVED.value, now
        )
        if applied:
            conn.execute(
                "UPDATE opportunities SET hard_eligibility_state = 'INELIGIBLE', "
                "hard_eligibility_reason = 'NO_SUPPORTED_ROUTE' WHERE opportunity_id = ?",
                (opportunity_id,),
            )
            conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
        conn.execute("COMMIT")
        return TransitionResult(not applied, ApplicationState.OBSERVED.value if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_terminal_failure(
    conn: sqlite3.Connection,
    attempt_id: int,
    opportunity_id: int,
    *,
    execution_phase: ExecutionPhase,
    error_code: str | None = None,
    error_class: str | None = None,
    now: str | None = None,
) -> TransitionResult:
    """TERMINAL_FAILURE (DATA_MODEL.md §7.4) has no dedicated §68 table row
    because it is, by definition, the non-retryable hard-failure outcome:
    Retry Matrix (§114) has no bounded-retry row for it, so it always lands
    on MANUAL_REVIEW directly (mirrors the "retryable failure, attempts
    exhausted" row's destination, without waiting for 3 attempts, since a
    terminal condition is inherently non-retryable from the first
    occurrence)."""
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _finish_attempt(
            conn, attempt_id, outcome=Outcome.TERMINAL_FAILURE, execution_phase=execution_phase,
            error_code=error_code, error_class=error_class, now=now,
        )
        applied = _fenced_opportunity_update(
            conn, opportunity_id, attempt_id, ApplicationState.MANUAL_REVIEW.value, now
        )
        if applied:
            conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
        conn.execute("COMMIT")
        return TransitionResult(not applied, ApplicationState.MANUAL_REVIEW.value if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_posting_expired(
    conn: sqlite3.Connection,
    attempt_id: int,
    opportunity_id: int,
    *,
    execution_phase: ExecutionPhase,
    now: str | None = None,
) -> TransitionResult:
    """BROWSER_SYSTEM.md §75 Expired Job: the driver discovered, mid-attempt,
    that the posting itself is closed/gone. This is not one of the 7 attempt-
    outcome values (DATA_MODEL.md §7.4) — EXPIRED is an opportunity-level
    `application_state` (§5.9), not an attempt outcome — so there is no
    §68 table row for it either; the smallest-correction mapping used here
    is: the attempt finishes TERMINAL_FAILURE (no retry is applicable — the
    opportunity itself is gone, not a transient attempt problem), and the
    opportunity moves directly to EXPIRED rather than the usual
    TERMINAL_FAILURE destination (MANUAL_REVIEW) — there is nothing for a
    human to review, the posting is confirmed closed."""
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _finish_attempt(
            conn, attempt_id, outcome=Outcome.TERMINAL_FAILURE, execution_phase=execution_phase,
            error_code=None, error_class="posting_expired", now=now,
        )
        applied = _fenced_opportunity_update(
            conn, opportunity_id, attempt_id, ApplicationState.EXPIRED.value, now
        )
        if applied:
            conn.execute(
                "UPDATE opportunities SET age_band = 'EXPIRED' WHERE opportunity_id = ?",
                (opportunity_id,),
            )
            conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
        conn.execute("COMMIT")
        return TransitionResult(not applied, ApplicationState.EXPIRED.value if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_tailoring_failure(
    conn: sqlite3.Connection, attempt_id: int, opportunity_id: int, now: str | None = None,
    *, reason: str = "tailoring_failure", error_code: str | None = None,
) -> TransitionResult:
    """§30 Tailoring Failure (Patch 2): execution_phase stays NOT_STARTED,
    no outcome is recorded, and — critically — this attempt must NOT count
    against §22's `attempts < MAX_ATTEMPTS`. Release the opportunity back to
    READY ("preserve opportunity").

    `reason` labels *why* execution_phase never left NOT_STARTED — the
    mechanics (release without consuming an attempt slot) are identical
    regardless of cause, so Phase 3's src/engine_apply.py also calls this
    for a pre-navigation login-session failure, a browser-launch failure, or
    a dry run that never reached Submit, passing a more specific reason
    string; the default stays "tailoring_failure" for the Phase 2 caller.

    `error_code` is additive (default None preserves every existing caller's
    behavior unchanged) — used by record_validation_finding below (and
    engine_apply.py's infra_error branch) to carry the gate's own finding
    text alongside the `reason` error_class."""
    now = now or enginedb.now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            UPDATE application_attempts
            SET attempt_state = 'FINISHED', error_class = ?, error_code = ?,
                finished_at = ?, updated_at = ?
            WHERE attempt_id = ?
            """,
            (reason, error_code, now, now, attempt_id),
        )
        applied = _fenced_opportunity_update(
            conn, opportunity_id, attempt_id, ApplicationState.READY.value, now
        )
        if applied:
            conn.execute(
                "UPDATE opportunities SET current_attempt_id = NULL WHERE opportunity_id = ? AND current_attempt_id = ?",
                (opportunity_id, attempt_id),
            )
        conn.execute("COMMIT")
        return TransitionResult(not applied, ApplicationState.READY.value if applied else None)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_validation_finding(
    conn: sqlite3.Connection, attempt_id: int, opportunity_id: int, *, error_class: str,
    error_code: str | None, now: str | None = None,
) -> TransitionResult:
    """A pre-submission gate finding or job-data-specific gate exception. execution_phase
    stays NOT_STARTED on every attempt this touches — no external work ever began.
    Counted only by countable_validation_failure_count, never MAX_ATTEMPTS. Below
    MAX_VALIDATION_ATTEMPTS: release to READY for a fresh tailor regeneration. At budget:
    terminal MANUAL_REVIEW via record_terminal_failure with execution_phase=NOT_STARTED
    passed explicitly."""
    now = now or enginedb.now_iso()
    prior = countable_validation_failure_count(conn, opportunity_id)
    if prior + 1 >= MAX_VALIDATION_ATTEMPTS:
        conn.execute("UPDATE application_attempts SET error_class=?, error_code=? WHERE attempt_id=?",
                    (error_class, error_code, attempt_id))
        return record_terminal_failure(conn, attempt_id, opportunity_id,
            execution_phase=ExecutionPhase.NOT_STARTED, error_class=error_class, error_code=error_code, now=now)
    return record_tailoring_failure(conn, attempt_id, opportunity_id, now=now,
                                    reason=error_class, error_code=error_code)


def resolve_channel(conn: sqlite3.Connection, attempt_id: int, resolved_channel: str, now: str | None = None) -> None:
    """WORKFLOW_ENGINE.md §32/§47: channel resolution happens after
    tailoring, near application time; updates the attempt's channel if it
    differs from the claim-time candidate."""
    now = now or enginedb.now_iso()
    conn.execute(
        "UPDATE application_attempts SET channel = ?, updated_at = ? WHERE attempt_id = ?",
        (resolved_channel, now, attempt_id),
    )


def mark_external_work_started(conn: sqlite3.Connection, attempt_id: int, now: str | None = None) -> None:
    now = now or enginedb.now_iso()
    conn.execute(
        """
        UPDATE application_attempts
        SET execution_phase = ?, attempt_state = 'STARTED', started_at = COALESCE(started_at, ?), updated_at = ?
        WHERE attempt_id = ? AND execution_phase = ?
        """,
        (ExecutionPhase.EXTERNAL_WORK_STARTED.value, now, now, attempt_id, ExecutionPhase.NOT_STARTED.value),
    )


def mark_submit_intent(conn: sqlite3.Connection, attempt_id: int, now: str | None = None) -> None:
    now = now or enginedb.now_iso()
    conn.execute(
        """
        UPDATE application_attempts
        SET execution_phase = ?, updated_at = ?
        WHERE attempt_id = ? AND execution_phase = ?
        """,
        (ExecutionPhase.SUBMIT_INTENT.value, now, attempt_id, ExecutionPhase.EXTERNAL_WORK_STARTED.value),
    )
