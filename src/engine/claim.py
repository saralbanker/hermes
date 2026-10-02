"""Claim transaction — WORKFLOW_ENGINE.md §24 / DATA_MODEL.md §19,
Scheduler Query Contract (§20), Candidate Revalidation (§72).

The claim transaction is the durable boundary before any external
(browser/network) work. No browser operation occurs inside it.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from . import db as enginedb
from .age import compute_age_band, is_within_horizon
from .daily_limits import has_daily_capacity, record_attempt_claimed
from .duplicates import pre_claim_duplicate_check
from .enums import AGE_BANDS_IN_ORDER, ApplicationState, BLOCKING_CHANNEL_STATUSES, ChannelStatus
from .retry import is_retry_eligible

_UNRESOLVED_CHANNEL = "unresolved"
_MAX_CANDIDATE_SCAN = 25  # bound the revalidation-retry loop per band


@dataclass(frozen=True)
class ClaimResult:
    attempt_id: int
    opportunity_id: int
    attempt_number: int
    channel: str


def _route_usable(conn: sqlite3.Connection, channel_key: str | None) -> bool:
    if not channel_key or channel_key == _UNRESOLVED_CHANNEL:
        return True  # channel not yet resolved; resolved later (§32/§47)
    health = enginedb.fetch_channel_health(conn, channel_key)
    if health is None:
        return True  # unknown channel (not yet seeded) is not treated as blocked
    return ChannelStatus(health["status"]) not in BLOCKING_CHANNEL_STATUSES


def revalidate_candidate(
    conn: sqlite3.Connection, opportunity_id: int, candidate_channel: str | None, now: str | None = None
) -> bool:
    """WORKFLOW_ENGINE.md §72: immediately-before-claim revalidation."""
    opp = enginedb.fetch_opportunity(conn, opportunity_id)
    if opp is None:
        return False
    if opp["application_state"] != ApplicationState.READY.value:
        return False
    if not is_within_horizon(opp["age_reference_at"], now):
        return False
    if opp["hard_eligibility_state"] != "ELIGIBLE":
        return False
    if pre_claim_duplicate_check(conn, opportunity_id) != "proceed":
        return False
    if not has_daily_capacity(conn, now):
        return False
    if not _route_usable(conn, candidate_channel):
        return False
    if not is_retry_eligible(conn, opportunity_id, now):
        return False
    return True


def _select_candidates_in_band(
    conn: sqlite3.Connection, age_band: str, now: str, channel_filter: str | None = None
) -> list[sqlite3.Row]:
    channel_clause = "AND w.candidate_channel = ?" if channel_filter else ""
    params = (age_band, now)
    if channel_filter:
        params += (channel_filter,)
    return conn.execute(
        f"""
        SELECT w.opportunity_id, w.candidate_channel
        FROM work_queue w
        JOIN opportunities o ON o.opportunity_id = w.opportunity_id
        WHERE w.age_band = ?
          AND (w.next_attempt_at IS NULL OR w.next_attempt_at <= ?)
          {channel_clause}
        ORDER BY COALESCE(o.fit_score, -1) DESC, o.opportunity_id ASC
        LIMIT ?
        """,
        params + (_MAX_CANDIDATE_SCAN,),
    ).fetchall()


def _next_attempt_number(conn: sqlite3.Connection, opportunity_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS n FROM application_attempts WHERE opportunity_id = ?",
        (opportunity_id,),
    ).fetchone()
    return row["n"]


def claim_next(
    conn: sqlite3.Connection, worker_id: str, lease_seconds: int, now: str | None = None,
    *, channel_filter: str | None = None,
) -> ClaimResult | None:
    """WORKFLOW_ENGINE.md §20 Scheduler Query Contract + §24 Claim Transaction.

    Iterates age bands oldest-priority-first (0_3D -> 15_21D per §18), picks
    the best claimable candidate in the first non-empty band, atomically
    claims it. On a lost claim race (another worker already flipped the
    opportunity out of READY) moves on to the next candidate rather than
    failing the whole call (§26 Claim Race).

    `channel_filter` (Phase 3 addition, default None = no filter, so every
    existing Phase 2 caller/test is unaffected): restricts candidates to a
    specific `work_queue.candidate_channel`, for a channel-specific driver
    like src/engine_apply.py that only knows how to drive one route.
    """
    now = now or enginedb.now_iso()
    if not has_daily_capacity(conn, now):
        return None

    for age_band in AGE_BANDS_IN_ORDER:
        for candidate in _select_candidates_in_band(conn, age_band, now, channel_filter):
            result = _try_claim(conn, candidate["opportunity_id"], candidate["candidate_channel"],
                                 worker_id, lease_seconds, now)
            if result is not None:
                return result
    return None


def _insert_claimed_attempt(
    conn: sqlite3.Connection,
    opportunity_id: int,
    channel: str,
    worker_id: str,
    lease_seconds: int,
    now: str,
) -> tuple[int, int]:
    """Inserts the CLAIMED attempt row. Returns (attempt_id, attempt_number)."""
    attempt_number = _next_attempt_number(conn, opportunity_id)
    lease_until = (
        dt.datetime.fromisoformat(now) + dt.timedelta(seconds=lease_seconds)
    ).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """
        INSERT INTO application_attempts (
            opportunity_id, channel, attempt_number, worker_id, claimed_at,
            lease_until, attempt_state, execution_phase, retry_eligible,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'CLAIMED', 'NOT_STARTED', 0, ?, ?)
        """,
        (opportunity_id, channel, attempt_number, worker_id, now, lease_until, now, now),
    )
    return cur.lastrowid, attempt_number


def _try_claim(
    conn: sqlite3.Connection,
    opportunity_id: int,
    candidate_channel: str | None,
    worker_id: str,
    lease_seconds: int,
    now: str,
) -> ClaimResult | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not revalidate_candidate(conn, opportunity_id, candidate_channel, now):
            conn.execute("ROLLBACK")
            return None

        channel = candidate_channel or _UNRESOLVED_CHANNEL
        attempt_id, attempt_number = _insert_claimed_attempt(
            conn, opportunity_id, channel, worker_id, lease_seconds, now
        )

        updated = conn.execute(
            """
            UPDATE opportunities
            SET application_state = 'APPLYING', current_attempt_id = ?, updated_at = ?
            WHERE opportunity_id = ? AND application_state = 'READY'
            """,
            (attempt_id, now, opportunity_id),
        )
        if updated.rowcount == 0:
            # Lost the claim race (§26): another worker/attempt already
            # moved this opportunity out of READY between revalidation and
            # here. Discard and let the caller try the next candidate.
            conn.execute("ROLLBACK")
            return None

        conn.execute("DELETE FROM work_queue WHERE opportunity_id = ?", (opportunity_id,))
        record_attempt_claimed(conn, now)
        conn.execute("COMMIT")
        return ClaimResult(attempt_id, opportunity_id, attempt_number, channel)
    except Exception:
        conn.execute("ROLLBACK")
        raise
