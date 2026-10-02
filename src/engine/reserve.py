"""READY_RESERVE derivation and work_queue rebuild.

DATA_MODEL.md §26 (post Patch 1): the predicate is

    current_open_state IN (OPEN, UNKNOWN)
    AND age_band IN (0_3D, 4_7D, 8_14D, 15_21D)
    AND hard_eligibility_state = ELIGIBLE
    AND application_state = READY
    AND no permanent all-channel block
    AND retry conditions satisfied
      (work_queue.next_attempt_at IS NULL OR next_attempt_at <= now())

Patch 1 is the fix this phase depends on: the pre-patch predicate used
`application_state NOT IN (...)` which left OBSERVED/EVALUATING counted in
the reserve. This module implements the corrected, strictly-narrower form.
"""

from __future__ import annotations

import sqlite3

from . import db as enginedb
from .age import compute_age_band
from .enums import AGE_BANDS_IN_ORDER

# "No permanent all-channel block" (DATA_MODEL.md §26): opportunities don't
# carry a channel list of their own (routing is resolved near application
# time, WORKFLOW_ENGINE.md §32), so the only durable, opportunity-level
# signal of a permanent block available in this schema is the explicit
# NO_SUPPORTED_ROUTE hard-eligibility reason (DATA_MODEL.md §5.7). This is a
# deliberate simplification: full per-route block checking belongs to
# channel resolution (Phase 3), not reserve counting.
_PERMANENT_BLOCK_REASON = "NO_SUPPORTED_ROUTE"


def compute_ready_reserve(conn: sqlite3.Connection, now: str | None = None) -> int:
    rows = conn.execute(
        """
        SELECT o.age_reference_at, o.hard_eligibility_reason,
               w.next_attempt_at
        FROM opportunities o
        LEFT JOIN work_queue w ON w.opportunity_id = o.opportunity_id
        WHERE o.current_open_state IN ('OPEN', 'UNKNOWN')
          AND o.hard_eligibility_state = 'ELIGIBLE'
          AND o.application_state = 'READY'
        """
    ).fetchall()

    count = 0
    for row in rows:
        if row["hard_eligibility_reason"] == _PERMANENT_BLOCK_REASON:
            continue
        if compute_age_band(row["age_reference_at"], now) not in AGE_BANDS_IN_ORDER:
            continue
        next_attempt_at = row["next_attempt_at"]
        if next_attempt_at is not None and next_attempt_at > (now or enginedb.now_iso()):
            continue
        count += 1
    return count


def rebuild_work_queue(conn: sqlite3.Connection, now: str | None = None) -> int:
    """DATA_MODEL.md §9.4 / WORKFLOW_ENGINE.md §17: deterministic, fully
    recomputable from canonical state. Invents no new facts.
    """
    now = now or enginedb.now_iso()

    # Preserve any pending retry-backoff timer and resolved candidate channel
    # already recorded for an opportunity — a rebuild must not erase
    # DATA_MODEL.md §9.1's non-canonical-but-still-real scheduling facts
    # (next_attempt_at is written by the retryable-failure transition, not
    # invented here; wiping it on every sweep would let a backed-off
    # opportunity become immediately reclaimable).
    existing = {
        row["opportunity_id"]: (row["next_attempt_at"], row["candidate_channel"])
        for row in conn.execute(
            "SELECT opportunity_id, next_attempt_at, candidate_channel FROM work_queue"
        ).fetchall()
    }

    conn.execute("DELETE FROM work_queue")

    candidates = conn.execute(
        """
        SELECT opportunity_id, age_reference_at, fit_score, latest_application_route
        FROM opportunities
        WHERE application_state = 'READY'
          AND hard_eligibility_state = 'ELIGIBLE'
          AND current_open_state IN ('OPEN', 'UNKNOWN')
        """
    ).fetchall()

    inserted = 0
    for row in candidates:
        age_band = compute_age_band(row["age_reference_at"], now)
        if age_band not in AGE_BANDS_IN_ORDER:
            continue
        _insert_queue_row(conn, row, age_band, existing, now)
        inserted += 1
    return inserted


def _insert_queue_row(
    conn: sqlite3.Connection, opp_row: sqlite3.Row, age_band: str, existing: dict, now: str
) -> None:
    prior_next_attempt_at, prior_candidate_channel = existing.get(
        opp_row["opportunity_id"], (None, None)
    )
    candidate_channel = prior_candidate_channel or opp_row["latest_application_route"]
    conn.execute(
        """
        INSERT INTO work_queue (
            opportunity_id, ready_state, age_band, priority_score,
            next_attempt_at, lease_until, candidate_channel, queue_reason,
            updated_at
        ) VALUES (?, 'READY', ?, ?, ?, NULL, ?, 'engine_rebuild', ?)
        """,
        (opp_row["opportunity_id"], age_band, opp_row["fit_score"],
         prior_next_attempt_at, candidate_channel, now),
    )
