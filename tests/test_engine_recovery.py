"""Phase 2 engine: crash recovery / stale-lease takeover.
WORKFLOW_ENGINE.md §41-45, §103-105, §158; DATA_MODEL.md §20."""

import datetime as dt

import pytest

from engine import claim, db as enginedb, recovery, retry, transitions
from engine.policy import MAX_VALIDATION_ATTEMPTS


def _expire_lease(conn, attempt_id):
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE application_attempts SET lease_until = ? WHERE attempt_id = ?", (past, attempt_id)
    )


def test_not_started_lease_release_and_requeue(make_opportunity, seed_channel, engine_conn):
    """§45: execution_phase=NOT_STARTED -> release/requeue. This must NOT
    count against MAX_ATTEMPTS (Patch 2)."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::crash1")
    result = claim.claim_next(engine_conn, worker_id="dead-worker", lease_seconds=1)
    _expire_lease(engine_conn, result.attempt_id)

    expired = recovery.find_expired_leases(engine_conn)
    assert len(expired) == 1
    assert expired[0]["attempt_id"] == result.attempt_id

    action = recovery.classify_recovery(expired[0])
    assert action is recovery.RecoveryAction.RELEASE_REQUEUE

    recovered = recovery.recover_expired_lease(engine_conn, expired[0])
    assert recovered.result.fenced_out is False

    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "READY"
    assert opp["current_attempt_id"] is None
    assert retry.countable_attempt_count(engine_conn, opp_id) == 0


def test_external_work_started_lease_retries_safely(make_opportunity, seed_channel, engine_conn):
    """§45: execution_phase=EXTERNAL_WORK_STARTED -> retry only when safe
    (treated as a retryable failure, which DOES count toward MAX_ATTEMPTS)."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::crash2")
    result = claim.claim_next(engine_conn, worker_id="dead-worker", lease_seconds=1)
    transitions.mark_external_work_started(engine_conn, result.attempt_id)
    _expire_lease(engine_conn, result.attempt_id)

    expired = recovery.find_expired_leases(engine_conn)
    action = recovery.classify_recovery(expired[0])
    assert action is recovery.RecoveryAction.RETRY_IF_SAFE

    recovered = recovery.recover_expired_lease(engine_conn, expired[0])
    assert recovered.result.new_application_state in ("READY", "MANUAL_REVIEW")
    assert retry.countable_attempt_count(engine_conn, opp_id) == 1


def test_submit_intent_lease_marks_unconfirmed_never_retried(make_opportunity, seed_channel, engine_conn):
    """§41/§43/§45: execution_phase=SUBMIT_INTENT with no outcome -> mark
    unconfirmed and reconcile; never treat the missing row as proof of
    non-submission, never blindly retry (§69 Forbidden Transitions)."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::crash3")
    result = claim.claim_next(engine_conn, worker_id="dead-worker", lease_seconds=1)
    transitions.mark_external_work_started(engine_conn, result.attempt_id)
    transitions.mark_submit_intent(engine_conn, result.attempt_id)
    _expire_lease(engine_conn, result.attempt_id)

    expired = recovery.find_expired_leases(engine_conn)
    action = recovery.classify_recovery(expired[0])
    assert action is recovery.RecoveryAction.MARK_UNCONFIRMED_RECONCILE

    recovered = recovery.recover_expired_lease(engine_conn, expired[0])
    assert recovered.result.new_application_state == "AWAITING_RECONCILIATION"

    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "AWAITING_RECONCILIATION"
    attempt = enginedb.fetch_attempt(engine_conn, result.attempt_id)
    assert attempt["outcome"] == "SUBMISSION_UNCONFIRMED"

    # Never blindly retried: the opportunity must not be retry-eligible.
    assert retry.is_retry_eligible(engine_conn, opp_id) is False


def test_lease_with_outcome_already_recorded_is_finalized_not_retried(
    make_opportunity, seed_channel, engine_conn
):
    """§45: outcome already recorded overrides phase-based inference —
    finalize, never retry (covers a late success report racing lease expiry)."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::crash4")
    result = claim.claim_next(engine_conn, worker_id="dead-worker", lease_seconds=1)
    transitions.record_submitted(engine_conn, result.attempt_id, opp_id, "indeed")
    _expire_lease(engine_conn, result.attempt_id)

    # Outcome is already set, so this attempt is excluded from the expired
    # unresolved-lease set entirely (find_expired_leases filters outcome IS NULL).
    expired = recovery.find_expired_leases(engine_conn)
    assert expired == []


def test_run_startup_recovery_is_idempotent(make_opportunity, seed_channel, engine_conn):
    """§158 Recovery Idempotency Test: run startup recovery twice; no
    duplicate attempt/submission is created."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::idempotent")
    result = claim.claim_next(engine_conn, worker_id="dead-worker", lease_seconds=1)
    _expire_lease(engine_conn, result.attempt_id)

    summary1 = recovery.run_startup_recovery(engine_conn)
    assert summary1["recovered_leases"] == 1

    summary2 = recovery.run_startup_recovery(engine_conn)
    assert summary2["recovered_leases"] == 0  # nothing left to recover

    attempts = engine_conn.execute(
        "SELECT COUNT(*) AS n FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempts["n"] == 1  # no duplicate attempt created


def test_stale_lease_takeover_by_different_worker_not_started(
    make_opportunity, seed_channel, engine_conn
):
    """Checklist item 4 — lease expiry + takeover by a different worker_id.
    Worker 'dead-worker' claims but never advances past NOT_STARTED before
    its lease (a real elapsed lease_until, not a manually-forced state)
    expires; startup recovery releases it; a different worker ('w2') must
    then be able to claim the SAME opportunity with a fresh attempt/lease."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::takeover1")

    first = claim.claim_next(engine_conn, worker_id="dead-worker", lease_seconds=1)
    assert first is not None
    _expire_lease(engine_conn, first.attempt_id)

    summary = recovery.run_startup_recovery(engine_conn)
    assert summary["recovered_leases"] == 1

    second = claim.claim_next(engine_conn, worker_id="w2", lease_seconds=900)
    assert second is not None
    assert second.attempt_id != first.attempt_id

    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "APPLYING"
    assert opp["current_attempt_id"] == second.attempt_id

    second_attempt = enginedb.fetch_attempt(engine_conn, second.attempt_id)
    assert second_attempt["worker_id"] == "w2"
    assert second_attempt["lease_until"] is not None

    # The original worker's lease/attempt must not have been silently
    # reused — recovery minted a genuinely new attempt for the new worker.
    first_attempt = enginedb.fetch_attempt(engine_conn, first.attempt_id)
    assert first_attempt["worker_id"] == "dead-worker"
    assert first_attempt["attempt_state"] == "FINISHED"


def test_stale_lease_takeover_by_different_worker_after_external_work_started(
    make_opportunity, seed_channel, engine_conn
):
    """Same takeover guarantee when the dead worker's lease expired AFTER
    external work had already started (RETRY_IF_SAFE path): recovery
    records a retryable failure and requeues with backoff, and once the
    backoff window has elapsed a different worker_id can claim it."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::takeover2")

    first = claim.claim_next(engine_conn, worker_id="dead-worker", lease_seconds=1)
    assert first is not None
    transitions.mark_external_work_started(engine_conn, first.attempt_id)
    _expire_lease(engine_conn, first.attempt_id)

    summary = recovery.run_startup_recovery(engine_conn)
    assert summary["recovered_leases"] == 1
    assert retry.countable_attempt_count(engine_conn, opp_id) == 1

    # Immediately: still inside the backoff window, no takeover yet.
    assert claim.claim_next(engine_conn, worker_id="w2", lease_seconds=900) is None

    far_future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    second = claim.claim_next(engine_conn, worker_id="w2", lease_seconds=900, now=far_future)
    assert second is not None
    assert second.attempt_id != first.attempt_id

    second_attempt = enginedb.fetch_attempt(engine_conn, second.attempt_id)
    assert second_attempt["worker_id"] == "w2"
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["current_attempt_id"] == second.attempt_id


def test_expire_stale_opportunities_sweep(make_opportunity, engine_conn):
    old_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S")
    opp_id = make_opportunity("canon::stale", age_reference_at=old_ts)

    expired_count = recovery.expire_stale_opportunities(engine_conn)
    assert expired_count == 1

    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "EXPIRED"
    row = engine_conn.execute(
        "SELECT COUNT(*) AS n FROM work_queue WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert row["n"] == 0


# ---------------------------------------------------------------------------
# §5.2/§5.3 — release_manual_review: the only way out of MANUAL_REVIEW, and the
# validation-failure budget reset it grants.
# ---------------------------------------------------------------------------

def _requeue_indeed(engine_conn, opp_id, now):
    engine_conn.execute(
        "INSERT INTO work_queue (opportunity_id, ready_state, age_band, priority_score, "
        "candidate_channel, updated_at) VALUES (?, 'READY', '0_3D', 0.9, 'indeed', ?)",
        (opp_id, now),
    )


def _one_gate_finding(engine_conn, now):
    claimed = claim.claim_next(engine_conn, "w1", 900, now, channel_filter="indeed")
    assert claimed is not None, "opportunity must still be claimable before exhaustion"
    return transitions.record_validation_finding(
        engine_conn, claimed.attempt_id, claimed.opportunity_id,
        error_class="gate_finding", error_code="cover letter is empty, missing, or whitespace-only",
        now=now,
    )


def _seconds_later(now: str, n: int) -> str:
    return (dt.datetime.strptime(now, "%Y-%m-%d %H:%M:%S") + dt.timedelta(seconds=n)).strftime(
        "%Y-%m-%d %H:%M:%S")


def test_release_manual_review_resets_validation_failure_budget(make_opportunity, seed_channel, engine_conn):
    """Exhaust MAX_VALIDATION_ATTEMPTS via repeated gate findings (-> MANUAL_REVIEW), release
    via release_manual_review, and confirm the budget is genuinely fresh: the 3 pre-release
    attempts must not count against the post-release budget (countable_validation_failure_count
    resets to 0 immediately), and a 4th finding after release is attempt 1 of a new 3 — not an
    instant re-exhaustion back into MANUAL_REVIEW. Mechanically proves what the Implementation
    Agent verified with an ad hoc script, now as a real pytest test.

    Timestamps are explicit and strictly increasing (never enginedb.now_iso() back-to-back):
    countable_validation_failure_count's cutoff is `created_at > manual_released_at` — an
    attempt created at the exact same (second-granularity) timestamp as the release is, by
    that filter's own documented intent, treated as at/before the release and excluded. Real
    wall-clock calls a few microseconds apart can collide on the same second, which would
    make this test flaky without forcing distinct seconds explicitly.
    """
    seed_channel("indeed")
    # latest_application_route is what release_manual_review's fresh work_queue row carries
    # forward as candidate_channel (src/engine/recovery.py) — normally set by discovery.py;
    # set explicitly here so the post-release claim_next(channel_filter="indeed") can find it.
    opp_id = make_opportunity("canon::release-boundary", latest_application_route="indeed")

    now = enginedb.now_iso()
    for _ in range(MAX_VALIDATION_ATTEMPTS - 1):
        tr = _one_gate_finding(engine_conn, now)
        assert tr.new_application_state == "READY"
        _requeue_indeed(engine_conn, opp_id, now)
        now = _seconds_later(now, 1)

    tr = _one_gate_finding(engine_conn, now)  # occurrence MAX_VALIDATION_ATTEMPTS: exhausted
    assert tr.new_application_state == "MANUAL_REVIEW"
    assert retry.countable_validation_failure_count(engine_conn, opp_id) == MAX_VALIDATION_ATTEMPTS

    release_now = _seconds_later(now, 1)
    release_tr = recovery.release_manual_review(engine_conn, opp_id, now=release_now)
    assert release_tr.new_application_state == "READY"
    assert retry.countable_validation_failure_count(engine_conn, opp_id) == 0
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "READY"
    assert opp["current_attempt_id"] is None

    # release_manual_review re-inserts its own work_queue row — claimable again immediately,
    # strictly after the release timestamp.
    post_release_now = _seconds_later(release_now, 1)
    claimed = claim.claim_next(engine_conn, "w1", 900, post_release_now, channel_filter="indeed")
    assert claimed is not None

    tr4 = transitions.record_validation_finding(
        engine_conn, claimed.attempt_id, claimed.opportunity_id,
        error_class="gate_finding", error_code="cover letter is empty, missing, or whitespace-only",
        now=post_release_now,
    )
    assert tr4.new_application_state == "READY", "a 4th finding post-release must be attempt 1, not re-exhaustion"
    assert retry.countable_validation_failure_count(engine_conn, opp_id) == 1


def test_release_manual_review_refuses_a_non_manual_review_opportunity(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::release-refused")  # created straight to READY, never MANUAL_REVIEW
    with pytest.raises(recovery.ManualReleaseError):
        recovery.release_manual_review(engine_conn, opp_id)
    assert enginedb.fetch_opportunity(engine_conn, opp_id)["application_state"] == "READY"


def test_release_manual_review_refuses_a_nonexistent_opportunity(engine_conn):
    with pytest.raises(recovery.ManualReleaseError):
        recovery.release_manual_review(engine_conn, 999999)
