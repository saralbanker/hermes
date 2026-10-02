"""Phase 2 engine: scheduler age-cascade ordering.
WORKFLOW_ENGINE.md §18/§20, §147 (Scheduler Correctness Test), §148 (Retry
Correctness Test), §156 (Expiration Test)."""

import datetime as dt

from engine import claim, db as enginedb
from engine.age import compute_age_band, is_within_horizon


def _age_ts(days_ago: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def test_scheduler_claims_youngest_age_band_first(make_opportunity, seed_channel, engine_conn):
    """§147: 0_3D before 4_7D before 8_14D before 15_21D."""
    seed_channel("indeed")
    make_opportunity("canon::old-band", age_reference_at=_age_ts(10), age_band="8_14D")
    young_id = make_opportunity("canon::young-band", age_reference_at=_age_ts(1), age_band="0_3D")
    make_opportunity("canon::mid-band", age_reference_at=_age_ts(5), age_band="4_7D")

    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    assert result.opportunity_id == young_id


def test_fresh_arrival_preemptable_at_next_claim(make_opportunity, seed_channel, engine_conn):
    """§19 Fresh Preemption / §147: a new 0_3D arrival is selectable at the
    next claim, ahead of older in-band-but-lower-priority work."""
    seed_channel("indeed")
    make_opportunity("canon::stale5d", age_reference_at=_age_ts(5), age_band="4_7D", fit_score=0.99)
    fresh_id = make_opportunity("canon::fresh1d", age_reference_at=_age_ts(1), age_band="0_3D", fit_score=0.1)

    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    # 0_3D band is scanned before 4_7D regardless of fit_score.
    assert result.opportunity_id == fresh_id


def test_retry_keeps_same_age_band_no_separate_retry_queue(make_opportunity, seed_channel, engine_conn):
    """§148 Retry Correctness Test: retryable 0_3D remains 0_3D. No separate
    retry age queue exists — WORKFLOW_ENGINE.md §21 Retry Overlay."""
    from engine import transitions

    seed_channel("indeed")
    opp_id = make_opportunity("canon::retry-age", age_reference_at=_age_ts(1), age_band="0_3D")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    transitions.mark_external_work_started(engine_conn, result.attempt_id)
    transitions.record_retryable_failure(
        engine_conn, result.attempt_id, opp_id, result.attempt_number,
        error_class="network_timeout_before_external_action",
    )

    row = engine_conn.execute(
        "SELECT age_band FROM work_queue WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert row["age_band"] == "0_3D"  # unchanged, not moved to a retry-specific band


def test_age_band_boundaries_match_frozen_hour_cutoffs():
    """ARCHITECTURE_REDESIGN_FINAL...FROZEN.md §3.2: 0-72h / >72-168h /
    >168-336h / >336-504h / >504h = EXPIRED."""
    now = "2026-10-01 12:00:00"

    def ts_hours_ago(hours):
        return (dt.datetime(2026, 10, 1, 12, 0, 0) - dt.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    assert compute_age_band(ts_hours_ago(0), now) == "0_3D"
    assert compute_age_band(ts_hours_ago(72), now) == "0_3D"
    assert compute_age_band(ts_hours_ago(72.01), now) == "4_7D"
    assert compute_age_band(ts_hours_ago(168), now) == "4_7D"
    assert compute_age_band(ts_hours_ago(168.01), now) == "8_14D"
    assert compute_age_band(ts_hours_ago(336), now) == "8_14D"
    assert compute_age_band(ts_hours_ago(336.01), now) == "15_21D"
    assert compute_age_band(ts_hours_ago(504), now) == "15_21D"
    assert compute_age_band(ts_hours_ago(504.01), now) == "EXPIRED"


def test_expiration_test_claim_forbidden_past_21_days(make_opportunity, seed_channel, engine_conn):
    """§156 Expiration Test: within 21 days -> may remain eligible; >21 days
    -> claim forbidden."""
    seed_channel("indeed")
    within_id = make_opportunity("canon::within21", age_reference_at=_age_ts(20))
    make_opportunity("canon::past21", age_reference_at=_age_ts(22), age_band="EXPIRED")

    assert is_within_horizon(_age_ts(20)) is True
    assert is_within_horizon(_age_ts(22)) is False

    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    assert result.opportunity_id == within_id

    result2 = claim.claim_next(engine_conn, worker_id="w2", lease_seconds=900)
    assert result2 is None  # the >21d opportunity was never queued (band=EXPIRED)
