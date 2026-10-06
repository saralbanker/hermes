"""Submission-gate coverage of every engine_apply path that can reach a run_*_apply function:

  * _drive_and_record                    -> indeed_apply.run_indeed_apply
  * _drive_redirect_channel_and_record   -> ats_apply.run_ats_apply, direct_form.run_direct_apply
    (WWR and Wellfound share it)

For each: a gate-blocked job must NOT call the run_* function. classify_gate_outcome's three
block kinds are each truthfully distinguished and bounded/unbounded as the plan requires:

  * A genuine gate finding or a job-data-specific gate exception (error_class
    'gate_finding'/'gate_job_data_error') is a BOUNDED-RETRY condition: occurrences 1-2 of
    MAX_VALIDATION_ATTEMPTS release the opportunity back to READY (execution_phase stays
    NOT_STARTED, uncounted toward MAX_ATTEMPTS, counted only by
    countable_validation_failure_count) for a fresh tailor regeneration; occurrence 3
    exhausts the budget into terminal MANUAL_REVIEW.
  * A gate-infra problem (GateConfigError/GateContractError, error_class 'gate_infra_error')
    recurs identically for every job regardless of that job's own data — it is classified
    infra_error and MUST NEVER count toward the validation budget: it always releases to
    READY and is repeatable indefinitely, never MANUAL_REVIEW from a single occurrence (or
    any number of occurrences, since it is never counted at all).

A clean job must still reach the run_* function. No browser, no network.
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
from engine import db as enginedb, retry
from engine.policy import MAX_VALIDATION_ATTEMPTS

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


def _attempt_latest(engine_conn, opp_id):
    return enginedb.fetch_latest_attempt(engine_conn, opp_id)


def _requeue(engine_conn, opp_id, channel):
    now = enginedb.now_iso()
    engine_conn.execute(
        "INSERT INTO work_queue (opportunity_id, ready_state, age_band, priority_score, "
        "candidate_channel, updated_at) VALUES (?, 'READY', '0_3D', 0.9, ?, ?)",
        (opp_id, channel, now),
    )


def _assert_bounded_release(engine_conn, opp_id, tr, calls, channel, *, expected_error_class):
    """Occurrence 1 or 2 of MAX_VALIDATION_ATTEMPTS: released to READY, uncounted toward
    MAX_ATTEMPTS, counted only by countable_validation_failure_count."""
    assert calls == [], "a gate-blocked job must never reach a run_*_apply function"
    assert tr.new_application_state == "READY"
    attempt = _attempt_latest(engine_conn, opp_id)
    assert attempt["error_class"] == expected_error_class
    assert attempt["execution_phase"] == "NOT_STARTED"
    assert attempt["outcome"] is None
    assert enginedb.fetch_opportunity(engine_conn, opp_id)["application_state"] == "READY"
    health = enginedb.fetch_channel_health(engine_conn, channel)
    assert health["status"] == "HEALTHY" and health["failure_streak"] == 0


def _assert_exhausted_manual_review(engine_conn, opp_id, tr, calls, channel, *, expected_error_class):
    """Occurrence MAX_VALIDATION_ATTEMPTS: terminal MANUAL_REVIEW via record_terminal_failure,
    execution_phase still NOT_STARTED (no external work ever began)."""
    assert calls == [], "a gate-blocked job must never reach a run_*_apply function"
    assert tr.new_application_state == "MANUAL_REVIEW"
    attempt = _attempt_latest(engine_conn, opp_id)
    assert attempt["outcome"] == "TERMINAL_FAILURE"
    assert attempt["error_class"] == expected_error_class
    assert attempt["execution_phase"] == "NOT_STARTED"
    assert attempt["retry_eligible"] == 0
    assert enginedb.fetch_opportunity(engine_conn, opp_id)["application_state"] == "MANUAL_REVIEW"
    assert engine_conn.execute(
        "SELECT COUNT(*) AS n FROM work_queue WHERE opportunity_id = ?", (opp_id,)).fetchone()["n"] == 0
    health = enginedb.fetch_channel_health(engine_conn, channel)
    assert health["status"] == "HEALTHY" and health["failure_streak"] == 0


def _assert_infra_release(engine_conn, opp_id, tr, calls, channel):
    """Gate-infra problem: ALWAYS released to READY, uncounted by either budget — never
    MANUAL_REVIEW, regardless of how many times it recurs."""
    assert calls == [], "a gate-blocked job must never reach a run_*_apply function"
    assert tr.new_application_state == "READY"
    attempt = _attempt_latest(engine_conn, opp_id)
    assert attempt["error_class"] == "gate_infra_error"
    assert attempt["execution_phase"] == "NOT_STARTED"
    assert attempt["outcome"] is None
    assert enginedb.fetch_opportunity(engine_conn, opp_id)["application_state"] == "READY"


@pytest.mark.parametrize("path_key", list(PATHS))
@pytest.mark.parametrize("company,letter", [
    ("Unknown", GOOD_LETTER),                                   # invalid company
    ("Acme Corp", "Dear Globex,\n\nI'd love to join Globex."),  # letter names another company
    ("Acme Corp", GOOD_LETTER + "\n\n[Your Name]"),             # unresolved placeholder
])
def test_gate_finding_is_bounded_retry_then_manual_review(
    path_key, company, letter, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    channel = PATHS[path_key][0]
    opp_id, calls = _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch, company=company)

    for _ in range(MAX_VALIDATION_ATTEMPTS - 1):
        tr = _run(path_key, engine_conn, tmp_path, letter)
        _assert_bounded_release(engine_conn, opp_id, tr, calls, channel, expected_error_class="gate_finding")
        _requeue(engine_conn, opp_id, channel)

    tr = _run(path_key, engine_conn, tmp_path, letter)
    _assert_exhausted_manual_review(engine_conn, opp_id, tr, calls, channel, expected_error_class="gate_finding")


@pytest.mark.parametrize("path_key", list(PATHS))
def test_gate_crash_is_bounded_retry_then_manual_review(
    path_key, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """A generic (non-GateConfigError/GateContractError) exception from the gate is THIS
    job's data breaking something unanticipated — classified job_data_error, bounded exactly
    like a genuine finding, never infra."""
    channel = PATHS[path_key][0]
    opp_id, calls = _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch)

    def boom(job, letter):
        raise RuntimeError("gate blew up")

    monkeypatch.setattr(gate, "validate_job_submission", boom)

    for _ in range(MAX_VALIDATION_ATTEMPTS - 1):
        tr = _run(path_key, engine_conn, tmp_path, GOOD_LETTER)
        _assert_bounded_release(engine_conn, opp_id, tr, calls, channel, expected_error_class="gate_job_data_error")
        assert "RuntimeError" in (_attempt_latest(engine_conn, opp_id)["error_code"] or "")
        _requeue(engine_conn, opp_id, channel)

    tr = _run(path_key, engine_conn, tmp_path, GOOD_LETTER)
    _assert_exhausted_manual_review(engine_conn, opp_id, tr, calls, channel, expected_error_class="gate_job_data_error")
    assert "RuntimeError" in (_attempt_latest(engine_conn, opp_id)["error_code"] or "")


@pytest.mark.parametrize("path_key", list(PATHS))
@pytest.mark.parametrize("returned", [None, False, 0, ("x",), [None]])
def test_gate_contract_violation_is_infra_error_repeatable_indefinitely(
    path_key, returned, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    channel = PATHS[path_key][0]
    opp_id, calls = _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch)
    monkeypatch.setattr(gate, "validate_job_submission", lambda job, letter: returned)

    for _ in range(MAX_VALIDATION_ATTEMPTS + 2):  # more than the budget — must never exhaust
        tr = _run(path_key, engine_conn, tmp_path, GOOD_LETTER)
        _assert_infra_release(engine_conn, opp_id, tr, calls, channel)
        _requeue(engine_conn, opp_id, channel)

    assert retry.countable_validation_failure_count(engine_conn, opp_id) == 0


def test_gate_config_error_is_infra_error_not_manual_review(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    channel = PATHS["indeed"][0]
    opp_id, calls = _setup("indeed", make_opportunity, seed_channel, engine_conn, monkeypatch)

    def boom(job, letter):
        raise gate.GateConfigError("profile/facts.md is empty")

    monkeypatch.setattr(gate, "validate_job_submission", boom)
    tr = _run("indeed", engine_conn, tmp_path, GOOD_LETTER)
    _assert_infra_release(engine_conn, opp_id, tr, calls, channel)
    assert retry.countable_validation_failure_count(engine_conn, opp_id) == 0


@pytest.mark.parametrize("path_key", list(PATHS))
def test_clean_job_still_reaches_its_run_function(
    path_key, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    opp_id, calls = _setup(path_key, make_opportunity, seed_channel, engine_conn, monkeypatch)
    tr = _run(path_key, engine_conn, tmp_path, GOOD_LETTER)
    assert calls == [("Acme Corp", GOOD_LETTER)]
    assert tr.new_application_state == "COMPLETED"
    assert _attempt_latest(engine_conn, opp_id)["outcome"] == "SUBMITTED"


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


def test_ashby_route_with_bad_data_is_bounded_gate_finding_not_antibot(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """A gate finding is caught BEFORE the Ashby-specific anti-bot refusal ever runs —
    truthfully classified as a bounded gate finding (occurrence 1 of MAX_VALIDATION_ATTEMPTS),
    never conflated with the anti-bot channel block Ashby would otherwise produce, and never
    jumping straight to MANUAL_REVIEW from a single occurrence."""
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
    assert tr.new_application_state == "READY"
    attempt = _attempt_latest(engine_conn, opp_id)
    assert attempt["error_class"] == "gate_finding"
    assert attempt["execution_phase"] == "NOT_STARTED"
    assert enginedb.fetch_channel_health(engine_conn, "wwr")["status"] == "HEALTHY"


def test_record_outcome_has_no_special_case_for_validation_failed_anymore(
    make_opportunity, seed_channel, engine_conn, monkeypatch
):
    """VALIDATION_FAILED is no longer a real _record_outcome input in production (the gate
    blocks and records its own outcome via _gate_or_record_block before any run_*_apply call
    or _record_outcome dispatch — see _drive_and_record/_drive_redirect_channel_and_record).
    The explicit mapping that used to exist here was deleted, not just reordered: constructing
    this input directly now falls through to the generic unmapped_state fail-closed branch."""
    from engine import claim
    seed_channel("indeed")
    opp_id = make_opportunity("canon::mapping")
    now = enginedb.now_iso()
    claimed = claim.claim_next(engine_conn, "w1", 900, now, channel_filter="indeed")
    tr = engine_apply._record_outcome(engine_conn, claimed, S.ApplyResult(S.VALIDATION_FAILED, "why"), now)
    attempt = _attempt_latest(engine_conn, opp_id)
    assert tr.new_application_state == "MANUAL_REVIEW"
    assert attempt["error_class"] == f"unmapped_state:{S.VALIDATION_FAILED}"
    assert attempt["outcome"] == "TERMINAL_FAILURE"
    assert attempt["execution_phase"] == "NOT_STARTED"
