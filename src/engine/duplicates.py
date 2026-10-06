"""Duplicate-submission protection — WORKFLOW_ENGINE.md §64 Duplicate
Prevention, using `canonical_key` + attempt history (never URL-only).
"""

from __future__ import annotations

import sqlite3

from . import db as enginedb
from .enums import ApplicationState, Outcome


def get_or_create_opportunity(
    conn: sqlite3.Connection, canonical_key: str, defaults: dict
) -> tuple[int, bool]:
    """DATA_MODEL.md §5.4: canonical identity is unique; a second source
    observation for the same canonical opportunity must resolve to the
    SAME opportunity row, never create a second one (this is what makes
    WORKFLOW_ENGINE.md §149's "different URL/different source -> no second
    application" true by construction).

    Returns (opportunity_id, created).
    """
    row = conn.execute(
        "SELECT opportunity_id FROM opportunities WHERE canonical_key = ?", (canonical_key,)
    ).fetchone()
    if row is not None:
        return row["opportunity_id"], False

    columns = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    cur = conn.execute(
        f"INSERT INTO opportunities (canonical_key, {columns}) VALUES (?, {placeholders})",
        (canonical_key, *defaults.values()),
    )
    return cur.lastrowid, True


def pre_claim_duplicate_check(conn: sqlite3.Connection, opportunity_id: int) -> str:
    """WORKFLOW_ENGINE.md §64:
        submitted      -> do not claim
        already applied -> do not claim
        unconfirmed    -> reconcile first
        else           -> proceed
    """
    opp = enginedb.fetch_opportunity(conn, opportunity_id)
    if opp is None:
        return "proceed"

    attempts = conn.execute(
        "SELECT outcome FROM application_attempts WHERE opportunity_id = ? AND outcome IS NOT NULL",
        (opportunity_id,),
    ).fetchall()
    outcomes = {row["outcome"] for row in attempts}

    if Outcome.SUBMITTED.value in outcomes:
        return "skip_submitted"
    if Outcome.ALREADY_APPLIED.value in outcomes:
        return "skip_already_applied"
    if opp["application_state"] == ApplicationState.AWAITING_RECONCILIATION.value:
        return "reconcile_first"
    return "proceed"
