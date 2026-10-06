"""Phase 3: src/engine/channel_health.py — DATA_MODEL.md §8 writes and the
BROWSER_SYSTEM.md §103.1 (Patch 3) reactivation rules, in isolation."""
from __future__ import annotations

import datetime as dt

from engine import channel_health as ch, db as enginedb


def _past(seconds_ago: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _future(seconds_ahead: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds_ahead)).strftime("%Y-%m-%d %H:%M:%S")


def test_degrade_sets_status_and_cooldown(seed_channel, engine_conn):
    seed_channel("indeed")
    from engine.enums import ChannelStatus

    ch.degrade(engine_conn, "indeed", ChannelStatus.RATE_LIMITED, cooldown_seconds=60,
               error_class="rate_limit")
    health = enginedb.fetch_channel_health(engine_conn, "indeed")
    assert health["status"] == "RATE_LIMITED"
    assert health["cooldown_until"] is not None
    assert health["failure_streak"] == 1
    assert health["rate_limit_count"] == 1


def test_rate_limited_recovers_by_timer_alone(seed_channel, engine_conn):
    from engine.enums import ChannelStatus

    seed_channel("indeed")
    now = _past(120)
    ch.degrade(engine_conn, "indeed", ChannelStatus.RATE_LIMITED, cooldown_seconds=60, now=now)
    # cooldown_until = now + 60s, which is in the past relative to actual now.
    assert ch.try_timer_recovery(engine_conn, "indeed") is True
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "HEALTHY"


def test_rate_limited_does_not_recover_before_cooldown_elapses(seed_channel, engine_conn):
    from engine.enums import ChannelStatus

    seed_channel("indeed")
    ch.degrade(engine_conn, "indeed", ChannelStatus.RATE_LIMITED, cooldown_seconds=3600)
    assert ch.try_timer_recovery(engine_conn, "indeed") is False
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "RATE_LIMITED"


def test_auth_expired_never_clears_by_timer_only_by_confirm(seed_channel, engine_conn):
    from engine.enums import ChannelStatus

    seed_channel("indeed")
    ch.degrade(engine_conn, "indeed", ChannelStatus.AUTH_EXPIRED, error_class="login_required")
    assert ch.try_timer_recovery(engine_conn, "indeed") is False  # not in the timer-only set
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "AUTH_EXPIRED"
    assert ch.confirm_reauthenticated(engine_conn, "indeed") is True
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "HEALTHY"


def test_form_schema_changed_never_clears_by_timer_only_by_driver_fix(seed_channel, engine_conn):
    from engine.enums import ChannelStatus

    seed_channel("indeed")
    ch.degrade(engine_conn, "indeed", ChannelStatus.FORM_SCHEMA_CHANGED, error_class="form_changed")
    assert ch.try_timer_recovery(engine_conn, "indeed") is False
    assert ch.confirm_driver_fixed(engine_conn, "indeed") is True
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "HEALTHY"


def test_antibot_blocked_requires_both_cooldown_and_probe(seed_channel, engine_conn):
    """§103.1: "requires minimum cooldown AND a successful read-only,
    non-mutating probe" — both conditions, neither alone."""
    from engine.enums import ChannelStatus

    seed_channel("indeed")
    ch.degrade(engine_conn, "indeed", ChannelStatus.ANTIBOT_BLOCKED, cooldown_seconds=3600,
               error_class="anti_bot_block")

    # Timer alone: never clears ANTIBOT_BLOCKED, even if it were elapsed.
    assert ch.try_timer_recovery(engine_conn, "indeed") is False
    # Probe called before cooldown elapses: refused.
    assert ch.confirm_probe_succeeded(engine_conn, "indeed") is False
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "ANTIBOT_BLOCKED"

    # Cooldown elapsed AND probe confirmed: clears.
    engine_conn.execute(
        "UPDATE channel_health SET cooldown_until = ? WHERE channel_key = 'indeed'", (_past(1),)
    )
    assert ch.confirm_probe_succeeded(engine_conn, "indeed") is True
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "HEALTHY"


def test_record_success_resets_streak_and_promotes_degraded_to_healthy(seed_channel, engine_conn):
    from engine.enums import ChannelStatus

    seed_channel("indeed", status="DEGRADED")
    ch.record_success(engine_conn, "indeed")
    health = enginedb.fetch_channel_health(engine_conn, "indeed")
    assert health["status"] == "HEALTHY"
    assert health["failure_streak"] == 0
    assert health["success_count"] == 1


def test_record_success_does_not_silently_clear_a_real_block(seed_channel, engine_conn):
    """record_success must never be used to accidentally clear ANTIBOT_BLOCKED/
    AUTH_EXPIRED/FORM_SCHEMA_CHANGED — those need an explicit confirm_* call."""
    from engine.enums import ChannelStatus

    seed_channel("indeed", status="ANTIBOT_BLOCKED")
    ch.record_success(engine_conn, "indeed")
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "ANTIBOT_BLOCKED"
