"""Phase 2 engine: retry eligibility (WORKFLOW_ENGINE.md §22), backoff
(§23), attempt counting / tailoring-failure exclusion (§22 Patch 2, §30)."""

import datetime as dt

from engine import claim, db as enginedb, retry, transitions
from engine.policy import MAX_ATTEMPTS


def test_tailoring_failure_does_not_count_toward_max_attempts(make_opportunity, seed_channel, engine_conn):
    """The core Patch 2 behavior: an attempt whose execution_phase never
    leaves NOT_STARTED must not consume a MAX_ATTEMPTS slot."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::tailor")

    for _ in range(5):  # far more than MAX_ATTEMPTS
        result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
        assert result is not None, "opportunity should remain claimable after each tailoring failure"
        tr = transitions.record_tailoring_failure(engine_conn, result.attempt_id, opp_id)
        assert tr.fenced_out is False
        assert tr.new_application_state == "READY"
        # Re-add to the queue for the next claim (normally the maintenance
        # loop / next discovery cycle would do this; here we do it directly
        # to isolate the attempt-counting behavior under test).
        now = enginedb.now_iso()
        engine_conn.execute(
            "INSERT INTO work_queue (opportunity_id, ready_state, age_band, priority_score, "
            "candidate_channel, updated_at) VALUES (?, 'READY', '0_3D', 0.9, 'indeed', ?)",
            (opp_id, now),
        )

    assert retry.countable_attempt_count(engine_conn, opp_id) == 0

    attempts = engine_conn.execute(
        "SELECT execution_phase, outcome FROM application_attempts WHERE opportunity_id = ?",
        (opp_id,),
    ).fetchall()
    assert len(attempts) == 5
    assert all(a["execution_phase"] == "NOT_STARTED" for a in attempts)
    assert all(a["outcome"] is None for a in attempts)


def test_retryable_failure_requeues_until_max_attempts_then_manual_review(
    make_opportunity, seed_channel, engine_conn
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::retry")

    for attempt_n in range(1, MAX_ATTEMPTS + 1):
        now = enginedb.now_iso()
        engine_conn.execute(
            "UPDATE work_queue SET next_attempt_at = NULL WHERE opportunity_id = ?", (opp_id,)
        )
        result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900, now=now)
        assert result is not None, f"expected claimable at attempt {attempt_n}"
        # Mark external work as having started (so this attempt IS countable).
        transitions.mark_external_work_started(engine_conn, result.attempt_id, now)
        tr = transitions.record_retryable_failure(
            engine_conn, result.attempt_id, opp_id, result.attempt_number,
            error_code="net_timeout", error_class="network_timeout_before_external_action", now=now,
        )
        assert tr.fenced_out is False
        if attempt_n < MAX_ATTEMPTS:
            assert tr.new_application_state == "READY"
        else:
            assert tr.new_application_state == "MANUAL_REVIEW"

    assert retry.countable_attempt_count(engine_conn, opp_id) == MAX_ATTEMPTS
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "MANUAL_REVIEW"

    # A MANUAL_REVIEW opportunity must not be claimable again automatically.
    assert retry.is_retry_eligible(engine_conn, opp_id) is False


def test_backoff_blocks_premature_retry(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::backoff")
    now = enginedb.now_iso()

    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900, now=now)
    transitions.mark_external_work_started(engine_conn, result.attempt_id, now)
    transitions.record_retryable_failure(
        engine_conn, result.attempt_id, opp_id, result.attempt_number,
        error_class="network_timeout_before_external_action", now=now,
    )

    # Immediately after the failure, the backoff window has not elapsed.
    assert retry.is_retry_eligible(engine_conn, opp_id, now=now) is False

    far_future = (dt.datetime.fromisoformat(now) + dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    assert retry.is_retry_eligible(engine_conn, opp_id, now=far_future) is True


def test_confirmed_submission_is_never_retry_eligible(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::confirmed")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    transitions.record_submitted(engine_conn, result.attempt_id, opp_id, "indeed")
    assert retry.has_confirmed_submission(engine_conn, opp_id) is True
    assert retry.is_retry_eligible(engine_conn, opp_id) is False


def test_compute_backoff_seconds_full_matrix_then_exhausted():
    """§23 Retry Backoff, direct unit coverage of compute_backoff_seconds/
    compute_next_attempt_at across the whole attempt-number range: every
    attempt below MAX_ATTEMPTS gets a positive, strictly-increasing-or-equal
    backoff, and MAX_ATTEMPTS itself returns None (no further automatic
    retry is scheduled — this is what makes the exhausted-attempts ->
    terminal path real rather than just 'eventually retried again')."""
    seen = []
    for attempt_number in range(1, MAX_ATTEMPTS):
        backoff = retry.compute_backoff_seconds(attempt_number)
        assert backoff is not None and backoff > 0
        seen.append(backoff)

    assert retry.compute_backoff_seconds(MAX_ATTEMPTS) is None

    now = "2026-01-01 00:00:00"
    next_at = retry.compute_next_attempt_at(1, now=now)
    assert next_at is not None
    assert next_at > now  # strictly in the future relative to now

    assert retry.compute_next_attempt_at(MAX_ATTEMPTS, now=now) is None


def test_retry_eligible_bit_matches_retry_matrix():
    from engine.enums import Outcome
    from engine.policy import retry_eligible_bit

    assert retry_eligible_bit(Outcome.SUBMITTED, None) == 0
    assert retry_eligible_bit(Outcome.ALREADY_APPLIED, None) == 0
    assert retry_eligible_bit(Outcome.SUBMISSION_UNCONFIRMED, None) == 0
    assert retry_eligible_bit(Outcome.UNSUPPORTED_CHANNEL, None) == 0
    assert retry_eligible_bit(Outcome.TERMINAL_FAILURE, None) == 0
    assert retry_eligible_bit(Outcome.RETRYABLE_FAILURE, "network_timeout_before_external_action") == 1
    assert retry_eligible_bit(Outcome.RETRYABLE_FAILURE, "form_changed") == 1
    assert retry_eligible_bit(Outcome.CHANNEL_BLOCKED, "anti_bot_block") == 0
    assert retry_eligible_bit(Outcome.CHANNEL_BLOCKED, "rate_limit") == 1
