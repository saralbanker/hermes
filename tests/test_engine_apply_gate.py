"""Submission-gate coverage of every engine_apply path that can reach a run_*_apply function:

  * _drive_and_record                    -> indeed_apply.run_indeed_apply
  * _drive_redirect_channel_and_record   -> ats_apply.run_ats_apply, direct_form.run_direct_apply
    (WWR and Wellfound share it)

For each: a gate-blocked job must NOT call the run_* function and must land as a terminal
VALIDATION_FAILED outcome (record_terminal_failure, error_class="validation_failed",
execution_phase NOT_STARTED), a gate crash must block the same way, and a clean job must
still reach the run_* function. No browser, no network.
"""
from __future__ import annotations

import json

import pytest

import ats_apply
import direct_form
import engine_apply
import indeed_apply
import redirect_resolver
import states as S
import submission_gate as gate
from engine import db as enginedb

ENABLED_CFG = {"engine": {"enabled": True}}
GOOD_LETTER = "Dear Acme Hiring Team,\n\nI'd love to join Acme and build great things with you."
GH_META = json.dumps({"ats": "greenhouse", "apply_url": "https://job-boards.greenhouse.io/acme/jobs/1"})

# Per path: (channel_key, apply function, run_* module, run_* name, source_name, url)
PATHS = {
    "indeed": ("indeed", engine_apply.apply_indeed_via_engine, indeed_apply, "run_indeed_apply",
               "indeed", "https://in.indeed.com/viewjob?jk=abc123"),
    "wwr_ats": ("wwr", engine_apply.apply_wwr_via_engine, ats_apply, "run_ats_apply",
                "wwr", "https://weworkremotely.com/remote-jobs/acme-engineer"),
    "wwr_direct": ("wwr", engine_apply.apply_wwr_via_engine, direct_form, "run_direct_apply",
                   "wwr", "https://weworkremotely.com/remote-jobs/acme-engineer"),
    "wellfound_ats": ("wellfound", engine_apply.apply_wellfound_via_engine, ats_apply, "run_ats_apply",
                      "wellfound", "https://wellfound.com/jobs/1-engineer"),
    "wellfound_direct": ("wellfound", engine_apply.apply_wellfound_via_engine, direct_form,
                         "run_direct_apply", "wellfound", "https://wellfound.com/jobs/1-engineer"),
}


def _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch, *, company="Acme Corp"):
    """Create one READY opportunity for the path, stub the resolver, and install a spy for
    the path's run_* function. Returns (opp_id, calls)."""
    channel, _fn, module, run_name, source, url = PATHS[path_key]
    seed_channel(channel)
    opp_id = make_opportunity(f"canon::{path_key}", candidate_channel=channel, company_display=company)
    now = enginedb.now_iso()
    use_inline_ats = path_key.endswith("_ats")
    engine_conn.execute(
        "INSERT INTO source_observations (opportunity_id, source_name, source_url, observed_at, "
        "raw_metadata, observation_status, created_at) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?)",
        (opp_id, source, url, now, GH_META if use_inline_ats else None, now),
    )
    monkeypatch.setattr(
        redirect_resolver, "resolve_apply_target",
        lambda u: {"final_url": "https://acme.example/careers/1", "channel": None, "ats_meta": None,
                   "error": "unsupported_destination:acme.example"},
    )
    calls: list[tuple] = []

    def spy(job, cover_letter, resume_path, screenshot_path, dry_run=False, on_progress=None):
        calls.append((job["company"], cover_letter))
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMITTED, evidence="Thanks for applying")

    monkeypatch.setattr(module, run_name, spy)
    return opp_id, calls


def _run(path_key, engine_conn, tmp_path, letter):
    fn = PATHS[path_key][1]
    return fn(engine_conn, "w1", letter, "resume.pdf", str(tmp_path), cfg=ENABLED_CFG)


def _attempt(engine_conn, opp_id):
    return engine_conn.execute(
        "SELECT * FROM application_attempts WHERE opportunity_id = ?", (opp_id,)).fetchone()


def _assert_terminal_validation_block(engine_conn, opp_id, tr, calls, channel):
    assert calls == [], "a gate-blocked job must never reach a run_*_apply function"
    assert tr.new_application_state == "MANUAL_REVIEW"
    attempt = _attempt(engine_conn, opp_id)
    assert attempt["outcome"] == "TERMINAL_FAILURE"
    assert attempt["error_class"] == "validation_failed"          # explicit, not "unmapped_state:..."
    assert attempt["execution_phase"] == "NOT_STARTED"            # no external work began
    assert attempt["retry_eligible"] == 0
    assert enginedb.fetch_opportunity(engine_conn, opp_id)["application_state"] == "MANUAL_REVIEW"
    assert engine_conn.execute(
        "SELECT COUNT(*) AS n FROM work_queue WHERE opportunity_id = ?", (opp_id,)).fetchone()["n"] == 0
    health = enginedb.fetch_channel_health(engine_conn, channel)
    assert health["status"] == "HEALTHY" and health["failure_streak"] == 0   # channel unaffected


@pytest.mark.parametrize("path_key", list(PATHS))
@pytest.mark.parametrize("company,letter", [
    ("Unknown", GOOD_LETTER),                                   # invalid company
    ("Acme Corp", "Dear Globex,\n\nI'd love to join Globex."),  # letter names another company
    ("Acme Corp", GOOD_LETTER + "\n\n[Your Name]"),             # unresolved placeholder
])
def test_gate_blocks_before_every_run_function(
    path_key, company, letter, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    opp_id, calls = _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch, company=company)
    tr = _run(path_key, engine_conn, tmp_path, letter)
    _assert_terminal_validation_block(engine_conn, opp_id, tr, calls, PATHS[path_key][0])


@pytest.mark.parametrize("path_key", list(PATHS))
def test_gate_crash_blocks_before_every_run_function(
    path_key, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    opp_id, calls = _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch)

    def boom(job, letter):
        raise RuntimeError("gate blew up")

    monkeypatch.setattr(gate, "validate_job_submission", boom)
    tr = _run(path_key, engine_conn, tmp_path, GOOD_LETTER)
    _assert_terminal_validation_block(engine_conn, opp_id, tr, calls, PATHS[path_key][0])
    assert "RuntimeError" in (_attempt(engine_conn, opp_id)["error_code"] or "")


@pytest.mark.parametrize("path_key", list(PATHS))
@pytest.mark.parametrize("returned", [None, False, 0, ("x",), [None]])
def test_gate_contract_violation_blocks_every_run_function(
    path_key, returned, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    opp_id, calls = _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch)
    monkeypatch.setattr(gate, "validate_job_submission", lambda job, letter: returned)
    tr = _run(path_key, engine_conn, tmp_path, GOOD_LETTER)
    _assert_terminal_validation_block(engine_conn, opp_id, tr, calls, PATHS[path_key][0])


@pytest.mark.parametrize("path_key", list(PATHS))
def test_clean_job_still_reaches_its_run_function(
    path_key, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    opp_id, calls = _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch)
    tr = _run(path_key, engine_conn, tmp_path, GOOD_LETTER)
    assert calls == [("Acme Corp", GOOD_LETTER)]
    assert tr.new_application_state == "COMPLETED"
    assert _attempt(engine_conn, opp_id)["outcome"] == "SUBMITTED"


def test_gate_runs_after_redirect_resolution_with_the_final_job(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """The redirect driver gates AFTER _resolve_redirect_route, so the gate sees (and the
    submitter receives) the exact same job dict — no post-gate mutation window."""
    opp_id, calls = _setup("wwr_direct", make_opportunity, seed_channel, engine_conn, monkeypatch)
    gated: list[dict] = []
    real = gate.validate_job_submission
    monkeypatch.setattr(gate, "validate_job_submission",
                        lambda job, letter: gated.append(dict(job)) or real(job, letter))
    _run("wwr_direct", engine_conn, tmp_path, GOOD_LETTER)
    assert len(gated) == 1 and gated[0]["direct_apply_url"] == "https://acme.example/careers/1"
    assert calls and calls[0][0] == gated[0]["company"]


def test_ashby_route_with_bad_data_is_validation_failed_not_antibot(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("wwr")
    opp_id = make_opportunity("canon::wwr-ashby-bad", candidate_channel="wwr", company_display="Unknown")
    now = enginedb.now_iso()
    engine_conn.execute(
        "INSERT INTO source_observations (opportunity_id, source_name, source_url, observed_at, "
        "raw_metadata, observation_status, created_at) VALUES (?, 'wwr', ?, ?, ?, 'ACTIVE', ?)",
        (opp_id, "https://weworkremotely.com/remote-jobs/x", now,
         json.dumps({"ats": "ashby", "apply_url": "https://jobs.ashbyhq.com/x/1"}), now),
    )
    tr = engine_apply.apply_wwr_via_engine(engine_conn, "w1", GOOD_LETTER, "resume.pdf", str(tmp_path),
                                           cfg=ENABLED_CFG)
    assert tr.new_application_state == "MANUAL_REVIEW"
    assert _attempt(engine_conn, opp_id)["error_class"] == "validation_failed"
    assert enginedb.fetch_channel_health(engine_conn, "wwr")["status"] == "HEALTHY"


def test_record_outcome_maps_validation_failed_explicitly(make_opportunity, seed_channel, engine_conn, monkeypatch):
    """Direct unit check of the explicit mapping (not the unmapped_state fallback)."""
    from engine import claim
    seed_channel("indeed")
    opp_id = make_opportunity("canon::mapping")
    now = enginedb.now_iso()
    claimed = claim.claim_next(engine_conn, "w1", 900, now, channel_filter="indeed")
    tr = engine_apply._record_outcome(engine_conn, claimed, S.ApplyResult(S.VALIDATION_FAILED, "why"), now)
    attempt = _attempt(engine_conn, opp_id)
    assert tr.new_application_state == "MANUAL_REVIEW"
    assert attempt["error_class"] == "validation_failed" and attempt["error_code"] == "why"
    assert attempt["outcome"] == "TERMINAL_FAILURE" and attempt["execution_phase"] == "NOT_STARTED"
