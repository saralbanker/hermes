"""Phase 4: src/engine/ai/failure.py — AI failures reuse Phase 2's
record_tailoring_failure rather than duplicating "release without consuming
an attempt" logic."""
from __future__ import annotations

from engine import claim
from engine.ai import failure, gateway


def test_classify_ai_failure_maps_known_exception_types():
    assert failure.classify_ai_failure(gateway.AIUnavailable("x")) == "runtime_unavailable"
    assert failure.classify_ai_failure(gateway.AITimeout("x")) == "timeout"
    assert failure.classify_ai_failure(ValueError("x")) == "malformed_or_invalid_output"
    assert failure.classify_ai_failure(RuntimeError("x")) == "unexpected_exception"


def test_release_on_ai_failure_preserves_opportunity_and_does_not_consume_attempt(
    make_opportunity, seed_channel, engine_conn
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::ai-failure")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    assert result is not None

    tr = failure.release_on_ai_failure(
        engine_conn, result.attempt_id, opp_id, gateway.AIUnavailable("ollama down")
    )
    assert tr.fenced_out is False
    assert tr.new_application_state == "READY"

    from engine.retry import countable_attempt_count
    assert countable_attempt_count(engine_conn, opp_id) == 0

    attempt = engine_conn.execute(
        "SELECT execution_phase, outcome, error_class FROM application_attempts WHERE attempt_id = ?",
        (result.attempt_id,),
    ).fetchone()
    assert attempt["execution_phase"] == "NOT_STARTED"
    assert attempt["outcome"] is None
    assert attempt["error_class"] == "ai_failure:runtime_unavailable"
