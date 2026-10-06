"""Phase 2 engine: duplicate-submission protection.
WORKFLOW_ENGINE.md §64 (Duplicate Prevention), §149 (Duplicate Safety Test)."""

from engine import claim, db as enginedb, duplicates, transitions


def test_same_canonical_key_resolves_to_one_opportunity_different_url(engine_conn):
    """§149: same canonical opportunity, different URL -> no second application
    (because it's never a second opportunity row in the first place)."""
    now = enginedb.now_iso()
    defaults = dict(
        identity_version=1, company_normalized="acme", job_title_normalized="engineer",
        first_seen_at=now, last_observed_at=now, current_open_state="OPEN",
        age_basis="FIRST_SEEN_AT_FALLBACK", age_reference_at=now, age_band="0_3D",
        hard_eligibility_state="ELIGIBLE", fit_state="EVALUATED", fit_score=0.9,
        application_state="READY", created_at=now, updated_at=now,
    )
    opp_id_1, created_1 = duplicates.get_or_create_opportunity(engine_conn, "canon::dup", defaults)
    opp_id_2, created_2 = duplicates.get_or_create_opportunity(engine_conn, "canon::dup", defaults)

    assert created_1 is True
    assert created_2 is False
    assert opp_id_1 == opp_id_2

    count = engine_conn.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"]
    assert count == 1


def test_same_canonical_key_resolves_to_one_opportunity_different_source(engine_conn):
    """§149: same canonical opportunity, different source -> no second
    application. Simulated via two source_observations under different
    source_name both resolving to the same opportunity_id."""
    now = enginedb.now_iso()
    defaults = dict(
        identity_version=1, company_normalized="acme", job_title_normalized="engineer",
        first_seen_at=now, last_observed_at=now, current_open_state="OPEN",
        age_basis="FIRST_SEEN_AT_FALLBACK", age_reference_at=now, age_band="0_3D",
        hard_eligibility_state="ELIGIBLE", fit_state="EVALUATED", fit_score=0.9,
        application_state="READY", created_at=now, updated_at=now,
    )
    opp_id, _ = duplicates.get_or_create_opportunity(engine_conn, "canon::multi-source", defaults)

    for source_name, url in (("indeed", "https://indeed.com/job/1"), ("greenhouse", "https://boards.greenhouse.io/acme/jobs/1")):
        engine_conn.execute(
            """
            INSERT INTO source_observations (
                opportunity_id, source_name, source_url, observed_at,
                observation_status, created_at
            ) VALUES (?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (opp_id, source_name, url, now, now),
        )

    obs_count = engine_conn.execute(
        "SELECT COUNT(DISTINCT opportunity_id) AS n FROM source_observations WHERE opportunity_id = ?",
        (opp_id,),
    ).fetchone()["n"]
    assert obs_count == 1  # both observations point at the single opportunity


def test_pre_claim_duplicate_check_blocks_submitted(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::blocked-submitted")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    transitions.record_submitted(engine_conn, result.attempt_id, opp_id, "indeed")

    assert duplicates.pre_claim_duplicate_check(engine_conn, opp_id) == "skip_submitted"
    # And the opportunity is simply no longer claimable at all (COMPLETED).
    assert claim.claim_next(engine_conn, worker_id="w2", lease_seconds=900) is None


def test_pre_claim_duplicate_check_blocks_already_applied(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::blocked-already")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    transitions.record_already_applied(engine_conn, result.attempt_id, opp_id)

    assert duplicates.pre_claim_duplicate_check(engine_conn, opp_id) == "skip_already_applied"


def test_pre_claim_duplicate_check_requires_reconciliation(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::reconcile")
    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    transitions.record_submission_unconfirmed(engine_conn, result.attempt_id, opp_id)

    assert duplicates.pre_claim_duplicate_check(engine_conn, opp_id) == "reconcile_first"
    assert claim.claim_next(engine_conn, worker_id="w2", lease_seconds=900) is None
