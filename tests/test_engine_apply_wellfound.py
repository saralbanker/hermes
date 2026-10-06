"""Phase 8: the Wellfound channel hardened onto src/engine/ —
src/engine_apply.py::apply_wellfound_via_engine. Mirrors
tests/test_engine_apply_wwr.py (Phase 7) closely: both channels now share
_apply_redirect_channel_via_engine / _resolve_redirect_route /
_drive_redirect_channel_and_record, parameterized only by channel key.

No browser, no network: ats_apply.run_ats_apply, direct_form.run_direct_apply and
redirect_resolver.resolve_apply_target are all monkeypatched at the module level, so a fake
stands in and calls the real `on_progress` callback exactly where the real driver would.
This also doubles as the mechanism that guarantees no live call to wellfound.com or any
employer/ATS site is ever made by this test file.
"""
from __future__ import annotations

import json

import ats_apply
import direct_form
import redirect_resolver
import states as S
import engine_apply
from engine import channel_health as ch, db as enginedb


ENABLED_CFG = {"engine": {"enabled": True}}


def _add_source(engine_conn, opportunity_id: int,
                 url: str = "https://wellfound.com/jobs/1234567-senior-engineer",
                 raw_metadata: str | None = None) -> None:
    now = enginedb.now_iso()
    engine_conn.execute(
        """
        INSERT INTO source_observations (
            opportunity_id, source_name, source_url, observed_at, raw_metadata,
            observation_status, created_at
        ) VALUES (?, 'wellfound', ?, ?, ?, 'ACTIVE', ?)
        """,
        (opportunity_id, url, now, raw_metadata, now),
    )


def _fake_run(result_builder):
    def _fake(job, cover_letter, resume_path, screenshot_path, dry_run=False, on_progress=None):
        return result_builder(on_progress)

    return _fake


def test_engine_disabled_by_default_refuses_to_run(engine_conn):
    import pytest

    with pytest.raises(engine_apply.EngineDisabledError):
        engine_apply.apply_wellfound_via_engine(
            engine_conn, "w1", "cover", "resume.pdf", "/tmp/shots", cfg={"engine": {"enabled": False}}
        )


def test_returns_none_when_no_wellfound_candidates(engine_conn):
    assert engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", "/tmp/shots", cfg=ENABLED_CFG
    ) is None


def test_channel_filter_only_selects_wellfound_candidates(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """A work_queue row tagged for a different channel (e.g. a WWR-sourced opportunity)
    must never be picked up by channel_filter='wellfound'."""
    seed_channel("wellfound")
    seed_channel("wwr")
    wwr_id = make_opportunity("canon::other-channel", candidate_channel="wwr",
                               company_normalized="otherco", job_title_normalized="engineer")
    _add_source(engine_conn, wwr_id, url="https://weworkremotely.com/remote-jobs/x")

    assert engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    ) is None
    wwr_opp = enginedb.fetch_opportunity(engine_conn, wwr_id)
    assert wwr_opp["application_state"] == "READY"  # untouched


def test_direct_apply_only_sentinel_resolves_to_unsupported_channel_without_any_browser_call(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """The Phase 8 finding: src/sources_wellfound.py already determined at discovery time
    (from the posting's own public JSON-LD, directApply:true) that this listing has no
    external employer apply route — Wellfound's own login-gated one-click apply is the only
    action, and this project will not log into or navigate toward it. redirect_resolver
    .resolve_apply_target must never even be called for this case."""
    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-direct-only", candidate_channel="wellfound")
    ats_meta = json.dumps({"direct_apply_only": True})
    _add_source(engine_conn, opp_id, raw_metadata=ats_meta)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("redirect_resolver.resolve_apply_target must not be called "
                              "for a direct_apply_only posting")

    monkeypatch.setattr(redirect_resolver, "resolve_apply_target", _must_not_be_called)

    tr = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "OBSERVED"
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["hard_eligibility_reason"] == "NO_SUPPORTED_ROUTE"

    attempt = engine_conn.execute(
        "SELECT outcome FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    # Same terminal outcome vocabulary transitions.record_unsupported_channel always uses
    # (reused unchanged, same as WWR's equivalent redirect-resolver finding) — no new state.
    assert attempt["outcome"] == "UNSUPPORTED_CHANNEL"
    # No channel work was attempted at all — wellfound stays HEALTHY, nothing degraded.
    assert enginedb.fetch_channel_health(engine_conn, "wellfound")["status"] == "HEALTHY"


def test_full_submit_flow_via_inline_ats_meta_dispatches_to_ats_apply(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """src/sources_wellfound.py already found a direct Greenhouse link embedded in the
    posting's description at discovery time (carried as source_observations.raw_metadata) —
    no redirect resolution needed, dispatch straight to ats_apply.run_ats_apply."""
    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-inline-gh", candidate_channel="wellfound")
    ats_meta = json.dumps({"ats": "greenhouse", "apply_url": "https://job-boards.greenhouse.io/acme/jobs/1"})
    _add_source(engine_conn, opp_id, raw_metadata=ats_meta)

    captured = {}

    def build_result(on_progress):
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMITTED, evidence="Thank you for applying")

    def fake_run_ats_apply(job, cover_letter, resume_path, screenshot_path, dry_run=False, on_progress=None):
        captured["job"] = job
        return build_result(on_progress)

    monkeypatch.setattr(ats_apply, "run_ats_apply", fake_run_ats_apply)

    tr = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover letter text", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "COMPLETED"
    assert json.loads(captured["job"]["ats_meta"])["ats"] == "greenhouse"

    attempt = engine_conn.execute(
        "SELECT * FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempt["execution_phase"] == "OBSERVED"
    assert attempt["outcome"] == "SUBMITTED"
    assert attempt["channel"] == "greenhouse"  # resolve_channel recorded the execution route

    # channel_health bookkeeping stays on the Wellfound source channel, not "greenhouse".
    wf_health = enginedb.fetch_channel_health(engine_conn, "wellfound")
    assert wf_health["status"] == "HEALTHY"
    assert wf_health["success_count"] == 1
    assert enginedb.fetch_channel_health(engine_conn, "greenhouse") is None


def test_full_submit_flow_via_redirect_resolved_direct_form(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """No inline ATS link and no direct_apply_only sentinel at discovery — this is the
    (currently unobserved live, but not assumed impossible) case of a Wellfound posting
    whose Apply action leads to an unrecognized employer form; redirect_resolver
    .resolve_apply_target is consulted exactly as it is for WWR."""
    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-direct-form", candidate_channel="wellfound")
    _add_source(engine_conn, opp_id)

    monkeypatch.setattr(
        redirect_resolver, "resolve_apply_target",
        lambda url: {"final_url": "https://acme.example/careers/42", "channel": None,
                     "ats_meta": None, "error": "unsupported_destination:acme.example"},
    )

    captured = {}

    def build_result(on_progress):
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMITTED, evidence="Your application has been received")

    def fake_run_direct_apply(job, cover_letter, resume_path, screenshot_path, dry_run=False, on_progress=None):
        captured["job"] = job
        return build_result(on_progress)

    monkeypatch.setattr(direct_form, "run_direct_apply", fake_run_direct_apply)

    tr = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover letter text", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "COMPLETED"
    assert captured["job"]["direct_apply_url"] == "https://acme.example/careers/42"

    attempt = engine_conn.execute(
        "SELECT channel, outcome FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempt["channel"] == "direct"
    assert attempt["outcome"] == "SUBMITTED"
    assert enginedb.fetch_channel_health(engine_conn, "wellfound")["status"] == "HEALTHY"


def test_redirect_resolver_unsupported_destination_marks_unsupported_channel(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-account-wall", candidate_channel="wellfound")
    _add_source(engine_conn, opp_id)

    monkeypatch.setattr(
        redirect_resolver, "resolve_apply_target",
        lambda url: {"final_url": "https://wellfound.com/login", "channel": None,
                     "ats_meta": None, "error": "account_required:wellfound.com requires an account"},
    )

    tr = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "OBSERVED"
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["hard_eligibility_reason"] == "NO_SUPPORTED_ROUTE"


def test_redirect_resolver_browser_error_releases_without_consuming_attempt(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """A resolver-side browser/CDP hiccup is an infra-class failure, same as WWR's own
    pre-navigation infra failures — released for free, channel_health untouched."""
    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-resolver-crash", candidate_channel="wellfound")
    _add_source(engine_conn, opp_id)

    monkeypatch.setattr(
        redirect_resolver, "resolve_apply_target",
        lambda url: {"final_url": None, "channel": None, "ats_meta": None,
                     "error": "redirect_browser_error:RuntimeError: boom"},
    )

    tr = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "READY"
    from engine.retry import countable_attempt_count
    assert countable_attempt_count(engine_conn, opp_id) == 0
    assert enginedb.fetch_channel_health(engine_conn, "wellfound")["status"] == "HEALTHY"


def test_antibot_rejection_from_ats_apply_degrades_wellfound_channel(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """ats_apply.py's own bot-risk-rejection classification (BLOCKED_ANTIBOT) must map to
    CHANNEL_BLOCKED + channel_health.ANTIBOT_BLOCKED on the Wellfound source channel."""
    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-antibot", candidate_channel="wellfound")
    ats_meta = json.dumps({"ats": "greenhouse", "apply_url": "https://job-boards.greenhouse.io/acme/jobs/2"})
    _add_source(engine_conn, opp_id, raw_metadata=ats_meta)

    def build_result(on_progress):
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.BLOCKED_ANTIBOT, detail="bot-risk check rejected the submission")

    monkeypatch.setattr(ats_apply, "run_ats_apply", _fake_run(build_result))

    tr = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "MANUAL_REVIEW"
    health = enginedb.fetch_channel_health(engine_conn, "wellfound")
    assert health["status"] == "ANTIBOT_BLOCKED"
    assert health["cooldown_until"] is not None
    attempt = engine_conn.execute(
        "SELECT outcome FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempt["outcome"] == "CHANNEL_BLOCKED"
    # "greenhouse" channel health is untouched — the shared ATS row stays HEALTHY.
    assert enginedb.fetch_channel_health(engine_conn, "greenhouse") is None or \
        enginedb.fetch_channel_health(engine_conn, "greenhouse")["status"] == "HEALTHY"


def test_ashby_route_is_refused_without_navigation_and_degrades_wellfound_channel(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-ashby", candidate_channel="wellfound")
    ats_meta = json.dumps({"ats": "ashby", "apply_url": "https://jobs.ashbyhq.com/acme/job-id/application"})
    _add_source(engine_conn, opp_id, raw_metadata=ats_meta)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("ats_apply.run_ats_apply must not be called for the ashby route")

    monkeypatch.setattr(ats_apply, "run_ats_apply", _must_not_be_called)

    tr = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "MANUAL_REVIEW"
    health = enginedb.fetch_channel_health(engine_conn, "wellfound")
    assert health["status"] == "ANTIBOT_BLOCKED"


def test_duplicate_submission_protection_after_wellfound_submit(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-dup", candidate_channel="wellfound")
    _add_source(engine_conn, opp_id)

    monkeypatch.setattr(
        redirect_resolver, "resolve_apply_target",
        lambda url: {"final_url": "https://acme.example/careers/9", "channel": None,
                     "ats_meta": None, "error": "unsupported_destination:acme.example"},
    )

    def build_result(on_progress):
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMITTED, evidence="application received")

    monkeypatch.setattr(direct_form, "run_direct_apply", _fake_run(build_result))

    tr = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "COMPLETED"

    again = engine_apply.apply_wellfound_via_engine(
        engine_conn, "w2", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert again is None


def test_linkedin_channel_health_row_does_not_exist_and_is_never_touched(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """LinkedIn is permanently unsupported and carries no channel_health row at all —
    confirm the Wellfound path never creates or touches one, however it resolves."""
    assert enginedb.fetch_channel_health(engine_conn, "linkedin") is None

    seed_channel("wellfound")
    opp_id = make_opportunity("canon::wellfound-no-linkedin", candidate_channel="wellfound")
    _add_source(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMITTED, evidence="application received")

    monkeypatch.setattr(
        redirect_resolver, "resolve_apply_target",
        lambda url: {"final_url": "https://acme.example/careers/9", "channel": None,
                     "ats_meta": None, "error": "unsupported_destination:acme.example"},
    )
    monkeypatch.setattr(direct_form, "run_direct_apply", _fake_run(build_result))

    engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert enginedb.fetch_channel_health(engine_conn, "linkedin") is None


def test_wwr_and_wellfound_channel_health_rows_are_independent(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """A Wellfound submission must not move WWR's channel_health row, and vice versa —
    confirmed here by driving a Wellfound submission and checking WWR stays untouched
    (seeded but never written to)."""
    seed_channel("wellfound")
    seed_channel("wwr")
    opp_id = make_opportunity("canon::wellfound-isolated", candidate_channel="wellfound")
    ats_meta = json.dumps({"ats": "lever", "apply_url": "https://jobs.lever.co/acme/" + "a" * 36})
    _add_source(engine_conn, opp_id, raw_metadata=ats_meta)

    def build_result(on_progress):
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMITTED, evidence="application received")

    monkeypatch.setattr(ats_apply, "run_ats_apply", _fake_run(build_result))

    engine_apply.apply_wellfound_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert enginedb.fetch_channel_health(engine_conn, "wellfound")["success_count"] == 1
    wwr_health = enginedb.fetch_channel_health(engine_conn, "wwr")
    assert wwr_health["success_count"] == 0
    assert wwr_health["status"] == "HEALTHY"
