"""Phase 6's own polling wrapper — reuses src/response_watcher.py's IMAP
connection/fetch logic (imported, not duplicated/forked) but is NOT wired
into hermes-watch.timer. A completely separate, explicitly-invoked
entrypoint; the live timer keeps calling response_watcher.py exactly as
before.

Implements EXECUTION_PROTOCOL.md §74.12 (Patch 11) recovery behavior:
bounded reconnect/backoff on IMAP auth/connection failure, then defer to the
next poll rather than crash — this watcher's own failure must not stop
src/engine/worker.py's application pipeline (WORKFLOW_ENGINE.md §61), which
is true here by construction: this module is never imported by
src/engine/worker.py, so an unhandled exception in this loop cannot reach
it at all. See the Phase 6 report's decoupling confirmation.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from response_watcher import _connect, _get_app_password, fetch_messages  # noqa: E402 — reused

from . import pipeline

logger = logging.getLogger(__name__)

# §74.12 step 1 ("confirm this is a genuine auth/connection failure... not a
# transient blip"): bounded, increasing backoff before giving up for this
# poll — exact values are ordinary tuning (no doc specifies them numerically).
RECONNECT_BACKOFF_SECONDS = [30, 60, 120, 300]
MAX_RECONNECT_ATTEMPTS = len(RECONNECT_BACKOFF_SECONDS)


def _connect_with_backoff(sleep_fn=time.sleep):
    if not _get_app_password():
        return None
    for attempt in range(MAX_RECONNECT_ATTEMPTS):
        imap_conn = _connect()
        if imap_conn is not None:
            return imap_conn
        if attempt < MAX_RECONNECT_ATTEMPTS - 1:
            sleep_fn(RECONNECT_BACKOFF_SECONDS[attempt])
    return None


def poll_once(conn: sqlite3.Connection, days: int = 3, sleep_fn=time.sleep) -> dict:
    """Message-id idempotency (DATA_MODEL.md §11.2/§18) is what makes
    §74.12 step 4 ("any backlog since the outage began is safely
    re-ingestible... without manual replay") true: re-scanning the same
    `days` window after a reconnect only ever re-processes already-seen
    message_ids as duplicates."""
    stats = {"scanned": 0, "new": 0, "duplicate": 0, "persisted": 0, "notified": 0, "status": "ok"}

    imap_conn = _connect_with_backoff(sleep_fn)
    if imap_conn is None:
        stats["status"] = "imap_unavailable"
        logger.warning(
            "gmail watcher: IMAP unavailable after %d bounded reconnect attempt(s) — "
            "deferring to next poll (EXECUTION_PROTOCOL.md §74.12)", MAX_RECONNECT_ATTEMPTS
        )
        return stats

    try:
        for message_id, from_addr, subject, body, received_at in fetch_messages(imap_conn, days):
            stats["scanned"] += 1
            result = pipeline.process_message(conn, message_id, from_addr, subject, body, received_at)
            if result.duplicate:
                stats["duplicate"] += 1
                continue
            stats["new"] += 1
            stats["persisted"] += int(result.persisted)
            stats["notified"] += int(result.notified)
    finally:
        try:
            imap_conn.logout()
        except Exception:
            pass
    return stats


def poll_loop(conn_factory, interval_minutes: int = 10, max_iterations: int | None = None,
              sleep_fn=time.sleep) -> list[dict]:
    reports = []
    i = 0
    while max_iterations is None or i < max_iterations:
        conn = conn_factory()
        try:
            reports.append(poll_once(conn, sleep_fn=sleep_fn))
        except Exception as exc:  # never let an unexpected bug escape the loop
            logger.error("gmail watcher: poll_once raised unexpectedly: %s", exc)
            reports.append({"status": "error", "error": str(exc)})
        finally:
            conn.close()
        i += 1
        if max_iterations is None or i < max_iterations:
            sleep_fn(interval_minutes * 60)
    return reports
