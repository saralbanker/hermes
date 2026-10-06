"""channel_health writes and reactivation rules.

DATA_MODEL.md §8 (schema/status enum), BROWSER_SYSTEM.md §103 (trigger ->
status mapping) and §103.1 (Patch 3, added in Phase 1: the reactivation
rule per status — "none is implicit").

This module did not exist in Phase 2 (an isolated-engine gap: Phase 2 only
seeded channel_health rows and read `.status` for route-usability checks;
nothing yet *wrote* a degrade or applied a recovery rule). Phase 3 needs
real write/recovery behavior to wire the Indeed driver's outcomes through,
so it is added here, additively, with its own tests.
"""

from __future__ import annotations

import sqlite3

from . import db as enginedb
from .enums import ChannelStatus

# §103.1: RATE_LIMITED / NETWORK_UNAVAILABLE clear on cooldown_until elapsing
# alone. AUTH_EXPIRED / FORM_SCHEMA_CHANGED / ANTIBOT_BLOCKED each require an
# explicit confirm_* call (re-auth, driver fix, or a successful read-only
# probe) — a timer by itself must never clear them.
_TIMER_ONLY_RECOVERABLE = frozenset({ChannelStatus.RATE_LIMITED, ChannelStatus.NETWORK_UNAVAILABLE})

# "Repeated form schema failures" (§103) — the doc does not specify a
# numeric threshold (consistent with the project's stated pattern of
# deferring non-correctness-critical numbers to measured behavior, per
# IMPLEMENTATION_READINESS_VERIFICATION_2026-10-01.md §12); this
# implementation's chosen default.
FORM_SCHEMA_FAILURE_STREAK_THRESHOLD = 3


def degrade(
    conn: sqlite3.Connection,
    channel_key: str,
    status: ChannelStatus,
    *,
    cooldown_seconds: int | None = None,
    error_class: str | None = None,
    error_code: str | None = None,
    now: str | None = None,
) -> None:
    """Write a channel-health degrade. `cooldown_seconds=None` means no
    timer applies to this status (AUTH_EXPIRED, FORM_SCHEMA_CHANGED,
    ANTIBOT_BLOCKED — §103.1 requires an explicit confirm_* call for these,
    not a timer)."""
    now = now or enginedb.now_iso()
    cooldown_until = None
    if cooldown_seconds is not None:
        import datetime as dt

        cooldown_until = (
            dt.datetime.fromisoformat(now) + dt.timedelta(seconds=cooldown_seconds)
        ).strftime("%Y-%m-%d %H:%M:%S")

    blocked_increment = 1 if status in (ChannelStatus.ANTIBOT_BLOCKED, ChannelStatus.ACCOUNT_WALL) else 0
    rate_limit_increment = 1 if status is ChannelStatus.RATE_LIMITED else 0
    conn.execute(
        """
        UPDATE channel_health
        SET status = ?, cooldown_until = ?, last_error_class = ?, last_error_code = ?,
            last_failure_at = ?, failure_streak = failure_streak + 1,
            blocked_count = blocked_count + ?, rate_limit_count = rate_limit_count + ?,
            updated_at = ?
        WHERE channel_key = ?
        """,
        (status.value, cooldown_until, error_class, error_code, now,
         blocked_increment, rate_limit_increment, now, channel_key),
    )


def record_success(conn: sqlite3.Connection, channel_key: str, now: str | None = None) -> None:
    now = now or enginedb.now_iso()
    conn.execute(
        """
        UPDATE channel_health
        SET status = CASE WHEN status IN ('HEALTHY', 'DEGRADED') THEN 'HEALTHY' ELSE status END,
            failure_streak = 0, success_count = success_count + 1,
            last_success_at = ?, updated_at = ?
        WHERE channel_key = ?
        """,
        (now, now, channel_key),
    )


def try_timer_recovery(conn: sqlite3.Connection, channel_key: str, now: str | None = None) -> bool:
    """§103.1: RATE_LIMITED / NETWORK_UNAVAILABLE clear when cooldown_until
    elapses. Returns True if a recovery was applied."""
    now = now or enginedb.now_iso()
    health = enginedb.fetch_channel_health(conn, channel_key)
    if health is None or health["status"] not in {s.value for s in _TIMER_ONLY_RECOVERABLE}:
        return False
    if health["cooldown_until"] is None or health["cooldown_until"] > now:
        return False
    conn.execute(
        "UPDATE channel_health SET status = 'HEALTHY', cooldown_until = NULL, updated_at = ? "
        "WHERE channel_key = ?",
        (now, channel_key),
    )
    return True


def confirm_reauthenticated(conn: sqlite3.Connection, channel_key: str, now: str | None = None) -> bool:
    """§103.1 AUTH_EXPIRED / EXECUTION_PROTOCOL.md §74.5: clears only via
    successful re-authentication — an explicit operator-confirmed call, never
    a timer."""
    return _confirm_clear(conn, channel_key, ChannelStatus.AUTH_EXPIRED, now)


def confirm_driver_fixed(conn: sqlite3.Connection, channel_key: str, now: str | None = None) -> bool:
    """§103.1 FORM_SCHEMA_CHANGED: does not self-heal on a timer; requires an
    explicit driver fix before clearing."""
    return _confirm_clear(conn, channel_key, ChannelStatus.FORM_SCHEMA_CHANGED, now)


def confirm_probe_succeeded(conn: sqlite3.Connection, channel_key: str, now: str | None = None) -> bool:
    """§103.1 ANTIBOT_BLOCKED: requires minimum cooldown AND a successful
    read-only, non-mutating probe before resuming submission attempts — both
    conditions, not either alone. Returns False (no-op) if cooldown has not
    yet elapsed, so a probe call cannot bypass the minimum cooldown."""
    now = now or enginedb.now_iso()
    health = enginedb.fetch_channel_health(conn, channel_key)
    if health is None or health["status"] != ChannelStatus.ANTIBOT_BLOCKED.value:
        return False
    if health["cooldown_until"] is not None and health["cooldown_until"] > now:
        return False  # minimum cooldown not yet elapsed
    conn.execute(
        "UPDATE channel_health SET status = 'HEALTHY', cooldown_until = NULL, updated_at = ? "
        "WHERE channel_key = ?",
        (now, channel_key),
    )
    return True


def _confirm_clear(
    conn: sqlite3.Connection, channel_key: str, expected_status: ChannelStatus, now: str | None
) -> bool:
    now = now or enginedb.now_iso()
    health = enginedb.fetch_channel_health(conn, channel_key)
    if health is None or health["status"] != expected_status.value:
        return False
    conn.execute(
        "UPDATE channel_health SET status = 'HEALTHY', cooldown_until = NULL, updated_at = ? "
        "WHERE channel_key = ?",
        (now, channel_key),
    )
    return True
