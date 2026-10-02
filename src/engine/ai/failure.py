"""AI failure -> engine transition bridge.

AI_SYSTEM.md §76-83 (AI Failure Classes / Runtime Unavailable / Timeout /
AI Failure Before Application): "If AI fails before browser interaction: no
submission is confirmed, no daily count increment occurs, no browser lease
is implied merely by an AI request." Phase 2 already built exactly this
"release without consuming an attempt" mechanism for tailoring failures
(src/engine/transitions.py:record_tailoring_failure, Patch 2) and Phase 3
already reused it for pre-navigation browser/session failures
(src/engine_apply.py). This module reuses it a third time for AI failures,
per the Phase 4 brief's explicit instruction not to duplicate it.
"""

from __future__ import annotations

import sqlite3

from . import gateway
from engine import transitions

AI_FAILURE_CLASSES = {
    gateway.AIUnavailable: "runtime_unavailable",
    gateway.AITimeout: "timeout",
    ValueError: "malformed_or_invalid_output",
}


def classify_ai_failure(exc: Exception) -> str:
    for exc_type, label in AI_FAILURE_CLASSES.items():
        if isinstance(exc, exc_type):
            return label
    return "unexpected_exception"


def release_on_ai_failure(
    conn: sqlite3.Connection, attempt_id: int, opportunity_id: int, exc: Exception,
    now: str | None = None,
):
    """Call when a model call fails during tailoring/generation, before any
    browser action began (execution_phase is still NOT_STARTED at this
    point in the §47 loop order: CLAIM -> TAILOR -> RESOLVE CHANNEL ->
    APPLY). Reuses record_tailoring_failure's exact mechanics — preserve the
    opportunity, release the lease, do not consume a MAX_ATTEMPTS slot."""
    reason = f"ai_failure:{classify_ai_failure(exc)}"
    return transitions.record_tailoring_failure(conn, attempt_id, opportunity_id, now=now, reason=reason)
