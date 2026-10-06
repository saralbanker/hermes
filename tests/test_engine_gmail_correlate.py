"""Phase 6: src/engine/gmail/correlate.py — correlation to real attempts
only, anti-false-positive guard (DATA_MODEL.md §11.4)."""
from __future__ import annotations

from engine import claim, db as enginedb
from engine.gmail import correlate


def _claimed_opportunity(make_opportunity, seed_channel, engine_conn, canonical_key, company):
    seed_channel("indeed")
    make_opportunity(canonical_key, company_display=company)
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    return result


def test_correlates_by_company_name_in_sender_domain(make_opportunity, seed_channel, engine_conn):
    claimed = _claimed_opportunity(make_opportunity, seed_channel, engine_conn, "canon::acme", "Acme Robotics")
    result = correlate.correlate(engine_conn, "careers@acmerobotics.com", "Update", "body text")
    assert result is not None
    assert result.opportunity_id == claimed.opportunity_id
    assert result.attempt_id == claimed.attempt_id


def test_correlates_by_company_name_in_subject(make_opportunity, seed_channel, engine_conn):
    _claimed_opportunity(make_opportunity, seed_channel, engine_conn, "canon::globex", "Globex Corp")
    result = correlate.correlate(
        engine_conn, "noreply@unrelated.com", "Your application to Globex Corp", "body"
    )
    assert result is not None
    assert result.company == "Globex Corp"


def test_no_correlation_for_unrelated_company(make_opportunity, seed_channel, engine_conn):
    _claimed_opportunity(make_opportunity, seed_channel, engine_conn, "canon::initech", "Initech")
    result = correlate.correlate(engine_conn, "noreply@totallydifferent.com", "Hello", "nothing relevant")
    assert result is None


def test_anti_false_positive_generic_phrase_alone_does_not_correlate(
    make_opportunity, seed_channel, engine_conn
):
    """DATA_MODEL.md §11.4: must not link solely on a generic phrase like
    'no-reply' or 'recommended jobs'."""
    _claimed_opportunity(make_opportunity, seed_channel, engine_conn, "canon::hooli", "Hooli")
    result = correlate.correlate(
        engine_conn, "jobalerts-noreply@indeed.com", "Recommended jobs for you",
        "Check out these jobs we think you'd like.",
    )
    assert result is None


def test_no_candidates_returns_none(engine_conn):
    result = correlate.correlate(engine_conn, "someone@example.com", "subject", "body")
    assert result is None


def test_only_opportunities_with_a_real_attempt_are_candidates(
    make_opportunity, seed_channel, engine_conn
):
    """DATA_MODEL.md §11.5: never fabricate an attempt that does not exist
    — an opportunity with no application_attempts row must never correlate."""
    seed_channel("indeed")
    make_opportunity("canon::never-applied", company_display="NeverApplied Inc")
    result = correlate.correlate(
        engine_conn, "careers@neverapplied.com", "subject", "NeverApplied Inc update"
    )
    assert result is None
