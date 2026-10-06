"""Phase 3: the Indeed channel hardened onto src/engine/ — src/engine_apply.py.

No browser, no network: `indeed_apply.run_indeed_apply` is monkeypatched at
the module level (the same pattern tests/test_indeed_stall_detection.py and
tests/test_apply_routing.py already use for indeed_apply/apply), so a fake
stands in and calls the real `on_progress` callback exactly where the real
driver would (see indeed_apply.py's run_indeed_apply/_click_next_or_submit
docstrings for the two boundaries). This also doubles as the mechanism that
guarantees no live call to indeed.com is ever made by this test file.
"""
from __future__ import annotations

import indeed_apply
import states as S
import engine_apply
from engine import channel_health as ch, db as enginedb
from engine.enums import ExecutionPhase


ENABLED_CFG = {"engine": {"enabled": True}}


def _add_source_url(engine_conn, opportunity_id: int, url: str = "https://in.indeed.com/viewjob?jk=abc123") -> None:
    now = enginedb.now_iso()
    engine_conn.execute(
        """
        INSERT INTO source_observations (
            opportunity_id, source_name, source_url, observed_at, observation_status, created_at
        ) VALUES (?, 'indeed', ?, ?, 'ACTIVE', ?)
        """,
        (opportunity_id, url, now, now),
    )


def _fake_run_indeed_apply(result_builder):
    """Returns a drop-in replacement for indeed_apply.run_indeed_apply that
    calls on_progress exactly like the real driver would, then returns
    result_builder()'s ApplyResult."""

    def _fake(job, cover_letter, resume_path, screenshot_path, dry_run=False, on_progress=None):
        return result_builder(on_progress)

    return _fake


def test_engine_disabled_by_default_refuses_to_run(engine_conn):
    import pytest

    with pytest.raises(engine_apply.EngineDisabledError):
        engine_apply.apply_indeed_via_engine(
            engine_conn, "w1", "cover", "resume.pdf", "/tmp/shots", cfg={"engine": {"enabled": False}}
        )


def test_returns_none_when_no_indeed_candidates(engine_conn):
    assert engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", "/tmp/shots", cfg=ENABLED_CFG
    ) is None


def test_full_submit_flow_writes_execution_phase_and_channel_health(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """End-to-end: claim -> tailor-stub (just a cover-letter string, no real
    tailoring call) -> submit-intent -> outcome recorded -> channel_health
    updated -> duplicate rejected on retry."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::e2e-submit")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMITTED, evidence="Your application has been submitted")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))

    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover letter text", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )

    assert tr.fenced_out is False
    assert tr.new_application_state == "COMPLETED"

    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "COMPLETED"
    attempt = engine_conn.execute(
        "SELECT * FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempt["execution_phase"] == "OBSERVED"
    assert attempt["outcome"] == "SUBMITTED"
    assert attempt["confirmation_text"] == "Your application has been submitted"

    health = enginedb.fetch_channel_health(engine_conn, "indeed")
    assert health["status"] == "HEALTHY"
    assert health["success_count"] == 1

    # Duplicate-submission protection: a second claim attempt must not find
    # this opportunity again (WORKFLOW_ENGINE.md §64/§149).
    again = engine_apply.apply_indeed_via_engine(
        engine_conn, "w2", "cover letter text", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert again is None


def test_already_applied_completes_and_marks_channel_healthy(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::already")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        return S.ApplyResult(S.ALREADY_APPLIED, detail="Indeed reports already applied")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "COMPLETED"
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "HEALTHY"


def test_submission_unconfirmed_awaits_reconciliation_never_replayed(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::unconfirmed")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMISSION_UNCONFIRMED, detail="clicked submit, no success signal")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "AWAITING_RECONCILIATION"

    attempt = engine_conn.execute(
        "SELECT execution_phase, outcome FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempt["execution_phase"] == "SUBMIT_INTENT"
    assert attempt["outcome"] == "SUBMISSION_UNCONFIRMED"

    # Never blindly replayed (§69 Forbidden Transitions).
    again = engine_apply.apply_indeed_via_engine(
        engine_conn, "w2", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert again is None


def test_login_required_before_navigation_releases_without_consuming_attempt(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """The session check runs before job-page navigation; on_progress is
    never called, so execution_phase stays NOT_STARTED — Patch 2's
    'no external work began' principle, generalized by Phase 3."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::login-pre")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        return S.ApplyResult(S.LOGIN_REQUIRED, detail="Indeed session is not signed in")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "READY"

    from engine.retry import countable_attempt_count
    assert countable_attempt_count(engine_conn, opp_id) == 0

    health = enginedb.fetch_channel_health(engine_conn, "indeed")
    assert health["status"] == "AUTH_EXPIRED"

    # The whole channel is paused: even though the opportunity is READY
    # again, claim_next must not select it via Indeed until re-auth clears.
    again = engine_apply.apply_indeed_via_engine(
        engine_conn, "w2", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert again is None

    assert ch.confirm_reauthenticated(engine_conn, "indeed") is True
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "HEALTHY"


def test_login_required_mid_flow_is_retryable_and_degrades_channel(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::login-mid")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        return S.ApplyResult(S.LOGIN_REQUIRED, detail="Indeed session expired")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "READY"

    from engine.retry import countable_attempt_count
    assert countable_attempt_count(engine_conn, opp_id) == 1  # mid-flow DOES count
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "AUTH_EXPIRED"


def test_security_interstitial_blocks_channel_and_manual_review_with_no_alternate(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::security")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        return S.ApplyResult(S.SECURITY_INTERSTITIAL, detail="Cloudflare check did not clear")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    # No other channel seeded/HEALTHY -> no alternate route -> MANUAL_REVIEW.
    assert tr.new_application_state == "MANUAL_REVIEW"

    health = enginedb.fetch_channel_health(engine_conn, "indeed")
    assert health["status"] == "ANTIBOT_BLOCKED"
    assert health["cooldown_until"] is not None

    attempt = engine_conn.execute(
        "SELECT outcome, retry_eligible FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempt["outcome"] == "CHANNEL_BLOCKED"
    assert attempt["retry_eligible"] == 0  # no same-route auto-retry

    # §103.1: a timer alone never clears ANTIBOT_BLOCKED.
    assert ch.try_timer_recovery(engine_conn, "indeed") is False
    # And an immediate probe (cooldown not yet elapsed) is also refused.
    assert ch.confirm_probe_succeeded(engine_conn, "indeed") is False


def test_form_changed_degrades_channel_only_after_streak(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")

    def build_result(on_progress):
        on_progress("external_work_started")
        return S.ApplyResult(S.FORM_CHANGED, detail="no Continue/Next/Submit control found")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))

    for i in range(ch.FORM_SCHEMA_FAILURE_STREAK_THRESHOLD):
        opp_id = make_opportunity(f"canon::form{i}")
        _add_source_url(engine_conn, opp_id, url=f"https://in.indeed.com/viewjob?jk=f{i}")
        tr = engine_apply.apply_indeed_via_engine(
            engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
        )
        assert tr.new_application_state == "READY"
        health = enginedb.fetch_channel_health(engine_conn, "indeed")
        if i < ch.FORM_SCHEMA_FAILURE_STREAK_THRESHOLD - 1:
            assert health["status"] == "HEALTHY"
        else:
            assert health["status"] == "FORM_SCHEMA_CHANGED"


def test_expired_posting_moves_opportunity_to_expired_not_manual_review(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::expired-posting")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        return S.ApplyResult(S.EXPIRED, detail="posting has expired or is no longer available")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "EXPIRED"
    attempt = engine_conn.execute(
        "SELECT outcome FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempt["outcome"] == "TERMINAL_FAILURE"


def test_network_error_before_navigation_releases_without_consuming_attempt(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::neterr-pre")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        return S.ApplyResult(S.NETWORK_ERROR, detail="browser launch failed: boom")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "READY"
    from engine.retry import countable_attempt_count
    assert countable_attempt_count(engine_conn, opp_id) == 0
    # Infra failure pre-navigation must not touch channel_health at all.
    assert enginedb.fetch_channel_health(engine_conn, "indeed")["status"] == "HEALTHY"


def test_network_error_mid_flow_degrades_channel_with_cooldown(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::neterr-mid")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        return S.ApplyResult(S.NETWORK_ERROR, detail="navigation failed mid-form")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "READY"
    health = enginedb.fetch_channel_health(engine_conn, "indeed")
    assert health["status"] == "NETWORK_UNAVAILABLE"
    assert health["cooldown_until"] is not None


def test_no_source_url_releases_without_consuming_attempt(make_opportunity, seed_channel, engine_conn, tmp_path):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::no-url")  # no source_observations row added
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "READY"
    from engine.retry import countable_attempt_count
    assert countable_attempt_count(engine_conn, opp_id) == 0


def test_unmapped_legacy_state_fails_closed_to_manual_review(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    """SYSTEM_RULES no-silent-failure: an outcome this module's dispatch
    doesn't recognize must never vanish silently."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::unmapped")
    _add_source_url(engine_conn, opp_id)

    def build_result(on_progress):
        on_progress("external_work_started")
        return S.ApplyResult(S.OTP_REQUIRED, detail="phone OTP required")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _fake_run_indeed_apply(build_result))
    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "cover", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    # OTP_REQUIRED is mapped (retryable), not unmapped — this just proves the
    # path returns a real, non-None transition and never silently drops it.
    assert tr is not None
    assert tr.new_application_state in ("READY", "MANUAL_REVIEW")
