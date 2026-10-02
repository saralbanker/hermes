"""Phase 5: src/engine/discovery.py — source ingestion, normalization/dedup
across sources, re-observation refresh. No network: `discover.collect` is
monkeypatched (same established pattern as the indeed/apply tests)."""
from __future__ import annotations

import pandas as pd

from engine import db as enginedb, discovery


CFG = {
    "search": {"min_score": 6.5, "stretch_min_score": 7.5, "min_similarity": 0.55,
               "boards": ["indeed"], "max_job_age_days": 21, "core_max_years": 4,
               "stretch_max_years": 8},
    "geo": {"home_lat": 23.03, "home_lon": 72.58, "radius_km": 9999, "night_radius_km": 9999},
    "salary": {"min_inr_per_month_india": 0, "min_inr_per_month_global": 0,
               "target_inr_per_month": 100000, "usd_to_inr": 88},
}


def _job(**overrides) -> dict:
    base = {
        "url": "https://in.indeed.com/viewjob?jk=abc123",
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "location": "Remote, India",
        "job_board": "indeed",
        "description": "python fastapi postgresql, 1-3 years",
        "salary_min": None,
        "salary_max": None,
        "date_posted": None,
        "apply_channel": "indeed",
        "ats_meta": None,
    }
    base.update(overrides)
    return base


def test_ingest_row_creates_new_opportunity_and_observation(engine_conn):
    result = discovery.ingest_row(engine_conn, _job(), CFG)
    assert result["created"] is True
    assert result["opportunity_id"] is not None

    opp = enginedb.fetch_opportunity(engine_conn, result["opportunity_id"])
    assert opp["company_display"] == "Acme Corp"
    assert opp["hard_eligibility_state"] == "ELIGIBLE"
    assert opp["application_state"] == "EVALUATING"

    obs = engine_conn.execute(
        "SELECT COUNT(*) AS n FROM source_observations WHERE opportunity_id = ?",
        (result["opportunity_id"],),
    ).fetchone()
    assert obs["n"] == 1


def test_ingest_row_same_role_different_source_merges_to_one_opportunity(engine_conn):
    """The actual point of using canonical_key here: cross-source dedup."""
    r1 = discovery.ingest_row(
        engine_conn, _job(url="https://in.indeed.com/viewjob?jk=1", job_board="indeed"), CFG
    )
    r2 = discovery.ingest_row(
        engine_conn,
        _job(url="https://boards.greenhouse.io/acme/jobs/1", job_board="greenhouse", apply_channel="greenhouse"),
        CFG,
    )
    assert r1["opportunity_id"] == r2["opportunity_id"]
    assert r2["created"] is False

    opp_count = engine_conn.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"]
    assert opp_count == 1
    obs_count = engine_conn.execute("SELECT COUNT(*) AS n FROM source_observations").fetchone()["n"]
    assert obs_count == 2


def test_ingest_row_stores_and_recovers_description_text(engine_conn):
    long_description = "python fastapi postgresql docker ci/cd rest api design " * 5
    result = discovery.ingest_row(engine_conn, _job(description=long_description), CFG)
    row = engine_conn.execute(
        "SELECT description_ref FROM source_observations WHERE opportunity_id = ?",
        (result["opportunity_id"],),
    ).fetchone()
    assert row["description_ref"]

    from engine import description_store
    recovered = description_store.read(row["description_ref"])
    assert "fastapi" in recovered


def test_ingest_row_marks_ineligible_without_touching_application_state_wrongly(engine_conn):
    # salary below floor -> ineligible
    cfg = {**CFG, "salary": {**CFG["salary"], "min_inr_per_month_india": 10_000_000,
                              "min_inr_per_month_global": 10_000_000}}
    result = discovery.ingest_row(
        engine_conn, _job(salary_min=50000, salary_max=60000, currency="INR"), cfg
    )
    opp = enginedb.fetch_opportunity(engine_conn, result["opportunity_id"])
    assert opp["hard_eligibility_state"] == "INELIGIBLE"
    assert opp["application_state"] == "OBSERVED"


def test_reobservation_does_not_clobber_ready_opportunity(engine_conn):
    result = discovery.ingest_row(engine_conn, _job(), CFG)
    opp_id = result["opportunity_id"]
    engine_conn.execute(
        "UPDATE opportunities SET application_state = 'READY' WHERE opportunity_id = ?", (opp_id,)
    )
    # Re-discover the same role from a second source.
    discovery.ingest_row(
        engine_conn, _job(url="https://boards.greenhouse.io/acme/jobs/1", job_board="greenhouse"), CFG
    )
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "READY"  # untouched


def test_ingest_row_skips_rows_with_no_url(engine_conn):
    result = discovery.ingest_row(engine_conn, _job(url=""), CFG)
    assert result["skipped"] == "no_url"
    count = engine_conn.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"]
    assert count == 0


def test_wwr_job_board_is_tagged_with_the_wwr_candidate_channel_not_its_apply_channel(engine_conn):
    """Phase 7: a WWR-origin opportunity's candidate channel must be the discovery board
    ("wwr"), not src/sources_wwr.py's own apply_channel field ("redirect", or an inline-
    detected "greenhouse"/"lever") — see src/engine_apply.py::apply_wwr_via_engine's
    channel_filter="wwr" contract."""
    result = discovery.ingest_row(
        engine_conn,
        _job(url="https://weworkremotely.com/remote-jobs/acme-engineer", job_board="wwr",
             apply_channel="redirect"),
        CFG,
    )
    opp = enginedb.fetch_opportunity(engine_conn, result["opportunity_id"])
    assert opp["latest_application_route"] == "wwr"


def test_wwr_job_board_with_inline_greenhouse_apply_channel_is_still_tagged_wwr(engine_conn):
    """Even when src/sources_wwr.py already found an inline Greenhouse/Lever link at
    discovery, the candidate channel stays "wwr" — the resolved ATS is only recorded on the
    attempt (transitions.resolve_channel) once an engine claim actually resolves it, not at
    discovery time."""
    result = discovery.ingest_row(
        engine_conn,
        _job(url="https://weworkremotely.com/remote-jobs/acme-engineer", job_board="wwr",
             apply_channel="greenhouse"),
        CFG,
    )
    opp = enginedb.fetch_opportunity(engine_conn, result["opportunity_id"])
    assert opp["latest_application_route"] == "wwr"


def test_indeed_job_board_channel_is_unaffected_by_the_wwr_override(engine_conn):
    result = discovery.ingest_row(engine_conn, _job(job_board="indeed", apply_channel="indeed"), CFG)
    opp = enginedb.fetch_opportunity(engine_conn, result["opportunity_id"])
    assert opp["latest_application_route"] == "indeed"


def test_wellfound_job_board_is_tagged_with_the_wellfound_candidate_channel_not_its_apply_channel(engine_conn):
    """Phase 8: same override as Phase 7's WWR tagging, now for Wellfound — a
    Wellfound-origin opportunity's candidate channel must be the discovery board
    ("wellfound"), not src/sources_wellfound.py's own apply_channel field ("redirect", or
    the "wellfound_direct" sentinel for a directApply:true posting) — see
    src/engine_apply.py::apply_wellfound_via_engine's channel_filter="wellfound" contract."""
    result = discovery.ingest_row(
        engine_conn,
        _job(url="https://wellfound.com/jobs/1234567-senior-engineer", job_board="wellfound",
             apply_channel="redirect"),
        CFG,
    )
    opp = enginedb.fetch_opportunity(engine_conn, result["opportunity_id"])
    assert opp["latest_application_route"] == "wellfound"


def test_wellfound_job_board_with_direct_apply_only_sentinel_is_still_tagged_wellfound(engine_conn):
    """Even when src/sources_wellfound.py already determined (from the posting's own public
    JSON-LD, directApply:true) that there is no external employer route at all, the
    candidate channel stays "wellfound" — route resolution (and the NO_SUPPORTED_ROUTE
    outcome that follows for this exact case) only happens once an engine claim actually
    resolves it, not at discovery time."""
    result = discovery.ingest_row(
        engine_conn,
        _job(url="https://wellfound.com/jobs/1234567-senior-engineer", job_board="wellfound",
             apply_channel="wellfound_direct"),
        CFG,
    )
    opp = enginedb.fetch_opportunity(engine_conn, result["opportunity_id"])
    assert opp["latest_application_route"] == "wellfound"


def test_indeed_job_board_channel_is_unaffected_by_the_wellfound_override(engine_conn):
    result = discovery.ingest_row(engine_conn, _job(job_board="indeed", apply_channel="indeed"), CFG)
    opp = enginedb.fetch_opportunity(engine_conn, result["opportunity_id"])
    assert opp["latest_application_route"] == "indeed"


def test_wwr_and_wellfound_boards_are_independent_candidate_channels(engine_conn):
    """Cross-check: tagging one redirect-sourced board must not leak onto the other."""
    wwr = discovery.ingest_row(
        engine_conn, _job(url="https://weworkremotely.com/remote-jobs/x", job_board="wwr"), CFG
    )
    wellfound = discovery.ingest_row(
        engine_conn, _job(url="https://wellfound.com/jobs/9-x", job_board="wellfound",
                           company="Other Co", title="Other Role"),
        CFG,
    )
    assert enginedb.fetch_opportunity(engine_conn, wwr["opportunity_id"])["latest_application_route"] == "wwr"
    assert enginedb.fetch_opportunity(engine_conn, wellfound["opportunity_id"])["latest_application_route"] == "wellfound"


def test_run_discovery_cycle_uses_discover_collect(engine_conn, monkeypatch):
    import discover as _discover

    df = pd.DataFrame([{
        "job_url": "https://in.indeed.com/viewjob?jk=xyz", "company": "Acme", "title": "Engineer",
        "location": "Remote", "site": "indeed", "description": "python", "min_amount": None,
        "max_amount": None, "currency": "INR", "date_posted": None,
    }])
    monkeypatch.setattr(_discover, "collect", lambda cfg, limit: df)

    from engine import discovery as _discovery_mod
    monkeypatch.setattr(_discovery_mod, "_discover", _discover)

    counts = discovery.run_discovery_cycle(engine_conn, CFG)
    assert counts["raw"] == 1
    assert counts["created"] == 1
