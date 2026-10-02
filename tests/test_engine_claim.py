"""Phase 2 engine: claim transaction, lease, concurrent-claim race, and
worker fencing. WORKFLOW_ENGINE.md §24-26, §72, §105; DATA_MODEL.md §19,
§19.1.
"""

from engine import claim, db as enginedb, transitions


def test_claim_next_creates_attempt_and_marks_applying(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::1")

    result = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)

    assert result is not None
    assert result.opportunity_id == opp_id
    assert result.attempt_number == 1

    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "APPLYING"
    assert opp["current_attempt_id"] == result.attempt_id

    attempt = enginedb.fetch_attempt(engine_conn, result.attempt_id)
    assert attempt["attempt_state"] == "CLAIMED"
    assert attempt["execution_phase"] == "NOT_STARTED"
    assert attempt["worker_id"] == "w1"
    assert attempt["lease_until"] is not None

    # No browser operation occurs in the claim transaction (§24): the queue
    # row is removed, nothing else about the opportunity's external state changes.
    row = engine_conn.execute(
        "SELECT COUNT(*) AS n FROM work_queue WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert row["n"] == 0


def test_claim_next_returns_none_when_no_candidates(engine_conn):
    assert claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900) is None


def test_claim_race_loser_gets_no_rows_affected(make_opportunity, seed_channel, engine_conn):
    """WORKFLOW_ENGINE.md §26 Claim Race: simulate two workers racing for the
    same opportunity using two separate connections to the same on-disk DB.
    Worker B must not perform browser work on an unowned candidate — i.e.
    claim_next must return None for B once A has already claimed it."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::race")
    engine_conn.close()  # release the in-memory conn; switch to a file-backed DB

    import tempfile, os

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn_setup = enginedb.connect(path)
        now = enginedb.now_iso()
        conn_setup.execute(
            """
            INSERT INTO opportunities (
                canonical_key, identity_version, company_normalized, job_title_normalized,
                first_seen_at, last_observed_at, current_open_state, age_basis,
                age_reference_at, age_band, hard_eligibility_state, fit_state, fit_score,
                application_state, created_at, updated_at
            ) VALUES (?,1,'acme','engineer',?,?,'OPEN','FIRST_SEEN_AT_FALLBACK',?,'0_3D',
                      'ELIGIBLE','EVALUATED',0.9,'READY',?,?)
            """,
            ("canon::race2", now, now, now, now, now),
        )
        new_opp_id = conn_setup.execute(
            "SELECT opportunity_id FROM opportunities WHERE canonical_key = 'canon::race2'"
        ).fetchone()["opportunity_id"]
        conn_setup.execute(
            "INSERT INTO channel_health (channel_key, scope, provider, status, updated_at) "
            "VALUES ('indeed','global','indeed','HEALTHY',?)",
            (now,),
        )
        conn_setup.execute(
            "INSERT INTO work_queue (opportunity_id, ready_state, age_band, priority_score, "
            "candidate_channel, updated_at) VALUES (?, 'READY', '0_3D', 0.9, 'indeed', ?)",
            (new_opp_id, now),
        )
        conn_setup.close()

        conn_a = enginedb.connect(path, ensure_schema=False)
        conn_b = enginedb.connect(path, ensure_schema=False)

        result_a = claim.claim_next(conn_a, worker_id="worker-a", lease_seconds=900)
        result_b = claim.claim_next(conn_b, worker_id="worker-b", lease_seconds=900)

        assert result_a is not None
        assert result_a.opportunity_id == new_opp_id
        assert result_b is None  # no candidates left for worker B

        conn_a.close()
        conn_b.close()
    finally:
        os.remove(path)


def test_fencing_rejects_stale_writer(make_opportunity, seed_channel, engine_conn):
    """WORKFLOW_ENGINE.md §105 / DATA_MODEL.md §19.1: a late write from a
    no-longer-current attempt must be discarded (fenced out), not applied."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::fence")

    attempt1 = claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)
    assert attempt1 is not None

    # Simulate attempt 1's lease expiring and a second attempt being claimed
    # (e.g. via recovery). Directly mimic what recovery would do: release
    # attempt 1 and let a new claim happen.
    now = enginedb.now_iso()
    engine_conn.execute(
        "UPDATE application_attempts SET attempt_state='FINISHED', execution_phase='NOT_STARTED', "
        "finished_at=?, updated_at=? WHERE attempt_id=?",
        (now, now, attempt1.attempt_id),
    )
    engine_conn.execute(
        "UPDATE opportunities SET application_state='READY', current_attempt_id=NULL WHERE opportunity_id=?",
        (opp_id,),
    )
    engine_conn.execute(
        "INSERT INTO work_queue (opportunity_id, ready_state, age_band, priority_score, candidate_channel, updated_at) "
        "VALUES (?, 'READY', '0_3D', 0.9, 'indeed', ?)",
        (opp_id, now),
    )

    attempt2 = claim.claim_next(engine_conn, worker_id="w2", lease_seconds=900)
    assert attempt2 is not None
    assert attempt2.attempt_id != attempt1.attempt_id

    # Now attempt 1 "reports late" (stale worker tries to write a result).
    result = transitions.record_submitted(
        engine_conn, attempt1.attempt_id, opp_id, "indeed", confirmation_text="late", now=now
    )
    assert result.fenced_out is True

    # The opportunity must still reflect attempt 2's ownership, not attempt 1's write.
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["current_attempt_id"] == attempt2.attempt_id
    assert opp["application_state"] == "APPLYING"  # unchanged by the stale write

    # Attempt 1's own row can still record its evidence (never discarded —
    # only the opportunity-level write is fenced).
    attempt1_row = enginedb.fetch_attempt(engine_conn, attempt1.attempt_id)
    assert attempt1_row["outcome"] == "SUBMITTED"


def test_revalidate_candidate_rejects_non_ready(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::notready", application_state="COMPLETED")
    assert claim.revalidate_candidate(engine_conn, opp_id, "indeed") is False


def test_revalidate_candidate_rejects_blocked_channel(make_opportunity, seed_channel, engine_conn):
    seed_channel("indeed", status="ANTIBOT_BLOCKED")
    opp_id = make_opportunity("canon::blocked")
    assert claim.revalidate_candidate(engine_conn, opp_id, "indeed") is False


def test_revalidate_candidate_rejects_expired_horizon(make_opportunity, seed_channel, engine_conn):
    import datetime as dt

    seed_channel("indeed")
    old_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    opp_id = make_opportunity("canon::old", age_reference_at=old_ts, age_band="EXPIRED")
    assert claim.revalidate_candidate(engine_conn, opp_id, "indeed") is False
