"""Phase 5: src/engine_apply.py's new tailoring wiring (cover_letter=None ->
real generation via src/engine/ai/generate.py, WORKFLOW_ENGINE.md §47 CLAIM
-> TAILOR -> RESOLVE CHANNEL -> APPLY). No network/browser: run_indeed_apply
and gateway.chat are both monkeypatched."""
from __future__ import annotations

import indeed_apply
import states as S
import engine_apply
from engine import db as enginedb
from engine.ai import gateway

ENABLED_CFG = {"engine": {"enabled": True}}


def _add_source(engine_conn, opportunity_id: int) -> None:
    now = enginedb.now_iso()
    engine_conn.execute(
        "INSERT INTO source_observations (opportunity_id, source_name, source_url, observed_at, "
        "observation_status, created_at) VALUES (?, 'indeed', 'https://indeed.com/job/1', ?, 'ACTIVE', ?)",
        (opportunity_id, now, now),
    )


def test_tailor_generates_real_letter_before_submit(make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::tailor-wire")
    _add_source(engine_conn, opp_id)

    monkeypatch.setattr(
        gateway, "chat",
        lambda role, prompt, **kw: gateway.CallResult(
            content="I'm drawn to this role because it matches my backend project work. "
                    "I built AWIS, an event-sourced workflow engine in Go with 773 test functions.",
            latency_seconds=0.2,
        ),
    )

    captured = {}

    def fake_run_indeed_apply(job, cover_letter, resume_path, screenshot_path, dry_run=False, on_progress=None):
        captured["cover_letter"] = cover_letter
        on_progress("external_work_started")
        on_progress("submit_intent")
        return S.ApplyResult(S.SUBMITTED, evidence="application submitted")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", fake_run_indeed_apply)

    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", None, "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "COMPLETED"
    assert "AWIS" in captured["cover_letter"]
    assert captured["cover_letter"].endswith(
        __import__("tailor").CLOSING
    )


def test_explicit_cover_letter_skips_generation(make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path):
    """Phase 3's original call shape — passing an explicit string — must
    still work unchanged (regression guard)."""
    seed_channel("indeed")
    opp_id = make_opportunity("canon::explicit-letter")
    _add_source(engine_conn, opp_id)

    chat_called = {"called": False}
    monkeypatch.setattr(gateway, "chat", lambda *a, **kw: chat_called.update(called=True))

    captured = {}

    def fake_run_indeed_apply(job, cover_letter, resume_path, screenshot_path, dry_run=False, on_progress=None):
        captured["cover_letter"] = cover_letter
        return S.ApplyResult(S.SUBMISSION_UNCONFIRMED, detail="x")

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", fake_run_indeed_apply)

    engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", "explicit cover letter", "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert captured["cover_letter"] == "explicit cover letter"
    assert chat_called["called"] is False


def test_tailoring_ai_failure_releases_without_consuming_attempt(
    make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    seed_channel("indeed")
    opp_id = make_opportunity("canon::tailor-fail")
    _add_source(engine_conn, opp_id)

    def boom(*a, **kw):
        raise RuntimeError("facts.md unreadable")  # genuinely unexpected, not AI-unavailable
    monkeypatch.setattr(engine_apply, "_tailor", lambda conn, claimed, job, now: (None,
        __import__("engine.ai.failure", fromlist=["release_on_ai_failure"]).release_on_ai_failure(
            conn, claimed.attempt_id, claimed.opportunity_id, RuntimeError("boom"), now)))

    tr = engine_apply.apply_indeed_via_engine(
        engine_conn, "w1", None, "resume.pdf", str(tmp_path), cfg=ENABLED_CFG
    )
    assert tr.new_application_state == "READY"
    from engine.retry import countable_attempt_count
    assert countable_attempt_count(engine_conn, opp_id) == 0
