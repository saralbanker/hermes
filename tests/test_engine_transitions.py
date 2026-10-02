"""Phase 2 engine: state transitions beyond submit/retry, covering the rest
of WORKFLOW_ENGINE.md §68 Transition Table + §155 Daily Cap Test."""

from engine import claim, daily_limits, db as enginedb, transitions


def test_channel_blocked_with_alternate_route_returns_to_ready(make_opportunity, seed_channel, engine_conn):
    seed_channel("ashby", status="ANTIBOT_BLOCKED")
    opp_id = make_opportunity("canon::cb1", candidate_channel="ashby")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    assert result is None  # channel already blocked pre-claim (route not usable)

    # Simulate the block being discovered mid-attempt instead: claim with a
    # healthy channel, then the attempt itself discovers the block.
    engine_conn.execute("UPDATE channel_health SET status='HEALTHY' WHERE channel_key='ashby'")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    assert result is not None

    tr = transitions.record_channel_blocked(
        engine_conn, result.attempt_id, opp_id, "ashby", has_alternate_route=True
    )
    assert tr.new_application_state == "READY"
    attempt = enginedb.fetch_attempt(engine_conn, result.attempt_id)
    assert attempt["outcome"] == "CHANNEL_BLOCKED"
    assert attempt["retry_eligible"] == 0  # anti-bot block: no same-route auto-retry


def test_channel_blocked_without_alternate_route_goes_to_manual_review(
    make_opportunity, seed_channel, engine_conn
):
    seed_channel("ashby")
    opp_id = make_opportunity("canon::cb2", candidate_channel="ashby")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)

    tr = transitions.record_channel_blocked(
        engine_conn, result.attempt_id, opp_id, "ashby", has_alternate_route=False
    )
    assert tr.new_application_state == "MANUAL_REVIEW"


def test_unsupported_channel_marks_ineligible_observed(make_opportunity, seed_channel, engine_conn):
    seed_channel("redirect")
    opp_id = make_opportunity("canon::unsupported", candidate_channel="redirect")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)

    tr = transitions.record_unsupported_channel(engine_conn, result.attempt_id, opp_id)
    assert tr.new_application_state == "OBSERVED"

    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["hard_eligibility_state"] == "INELIGIBLE"
    assert opp["hard_eligibility_reason"] == "NO_SUPPORTED_ROUTE"


def test_terminal_failure_always_goes_to_manual_review(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::terminal")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    transitions.mark_external_work_started(engine_conn, result.attempt_id)

    from engine.enums import ExecutionPhase

    tr = transitions.record_terminal_failure(
        engine_conn, result.attempt_id, opp_id,
        execution_phase=ExecutionPhase.EXTERNAL_WORK_STARTED, error_class="fatal_error",
    )
    assert tr.new_application_state == "MANUAL_REVIEW"
    attempt = enginedb.fetch_attempt(engine_conn, result.attempt_id)
    assert attempt["outcome"] == "TERMINAL_FAILURE"
    assert attempt["retry_eligible"] == 0


def test_already_applied_completes_with_zero_confirmed_count(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::already")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    now = enginedb.now_iso()
    transitions.record_already_applied(engine_conn, result.attempt_id, opp_id, now=now)

    assert daily_limits.get_confirmed_count(engine_conn, now) == 0
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "COMPLETED"


def test_daily_cap_blocks_new_claims_at_target(make_opportunity, seed_channel, engine_conn):
    """§155 Daily Cap Test: 99 confirmed -> claim may proceed; 100 confirmed
    -> no new application claim; unconfirmed attempt -> count unchanged."""
    seed_channel("indeed")
    now = enginedb.now_iso()
    date = enginedb.today_str(now)
    engine_conn.execute(
        "INSERT INTO daily_limits_v2 (date, confirmed_count, updated_at) VALUES (?, 99, ?)",
        (date, now),
    )
    opp_id = make_opportunity("canon::cap99")
    assert daily_limits.has_daily_capacity(engine_conn, now) is True
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900, now=now)
    assert result is not None

    transitions.record_submitted(engine_conn, result.attempt_id, opp_id, "indeed", now=now)
    assert daily_limits.get_confirmed_count(engine_conn, now) == 100
    assert daily_limits.has_daily_capacity(engine_conn, now) is False

    make_opportunity("canon::cap100")
    assert claim.claim_next(engine_conn, worker_id="w2", lease_seconds=900, now=now) is None


def test_unconfirmed_attempt_does_not_change_confirmed_count(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::unconfirmed-cap")
    now = enginedb.now_iso()
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900, now=now)
    transitions.record_submission_unconfirmed(engine_conn, result.attempt_id, opp_id, now=now)
    assert daily_limits.get_confirmed_count(engine_conn, now) == 0
