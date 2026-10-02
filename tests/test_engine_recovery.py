"""Phase 2 engine: crash recovery / stale-lease takeover.
WORKFLOW_ENGINE.md §41-45, §103-105, §158; DATA_MODEL.md §20."""

import datetime as dt

from engine import claim, db as enginedb, recovery, retry, transitions


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
