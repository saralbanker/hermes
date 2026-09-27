"""Offline test for _drive_application's stall detection — the fix for a confirmed real
timeout (MyProFunnels Ventures Pvt Ltd, 2026-09-25, output/hermes_cron.log /
screenshots/myprofunnels-ventures-pvt-ltd-web-developer.png): a required <select> whose
"*" was not found by _is_required's DOM-walk was silently left unanswered, so every filler
reported success, Continue kept failing the same validation, and the identical page
reappeared every loop iteration until the full 6-minute budget was burned. Two identical
'application' snapshots in a row must now fail fast with a precise reason instead.

No browser: _snapshot/classify_page/_handle_classified_page are all monkeypatched.
"""
from __future__ import annotations

import indeed_apply as ia
import states as S


def test_identical_application_snapshot_twice_fails_fast(monkeypatch):
    calls = {"n": 0}

    # Every classify/snapshot call returns the exact same page — nothing ever changes,
    # simulating a Continue click that silently failed validation.
    monkeypatch.setattr(ia, "_snapshot", lambda page: ("https://smartapply.indeed.com/x",
                                                        "Application", "same question text", "<html></html>"))
    monkeypatch.setattr(ia, "classify_page", lambda *a: "application")

    def fake_handle(*_a, **_kw):
        # The real _handle_classified_page would fill (no-op, already filled) and click
        # Continue (no-op, validation blocks it) and return None to keep driving.
        calls["n"] += 1
        return None

    monkeypatch.setattr(ia, "_handle_classified_page", fake_handle)
    monkeypatch.setattr(ia, "_screenshot", lambda *_a, **_kw: None)

    import time
    result = ia._drive_application({}, {"title": "x"}, "cover", "resume.pdf", "shot.png",
                                    dry_run=False, deadline=time.monotonic() + 300)
    assert result.state == S.FORM_CHANGED
    assert "did not advance" in result.detail
    # Failed on the SECOND identical snapshot, not after burning the whole time budget.
    assert calls["n"] == 1


def test_genuinely_advancing_multi_step_form_is_not_flagged_as_stalled(monkeypatch):
    pages = [
        ("https://smartapply.indeed.com/step1", "Step 1", "question one", "<html>1</html>"),
        ("https://smartapply.indeed.com/step2", "Step 2", "question two", "<html>2</html>"),
    ]
    calls = {"n": 0}

    def fake_snapshot(_page):
        return pages[min(calls["n"], len(pages) - 1)]

    def fake_handle(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] >= len(pages):
            return S.ApplyResult(S.SUBMITTED, evidence="done")
        return None

    monkeypatch.setattr(ia, "_snapshot", fake_snapshot)
    monkeypatch.setattr(ia, "classify_page", lambda *a: "application")
    monkeypatch.setattr(ia, "_handle_classified_page", fake_handle)
    monkeypatch.setattr(ia, "_screenshot", lambda *_a, **_kw: None)

    import time
    result = ia._drive_application({}, {"title": "x"}, "cover", "resume.pdf", "shot.png",
                                    dry_run=False, deadline=time.monotonic() + 300)
    # Each step is a genuinely different page (different URL/text) — never flagged as a
    # stall, which only fires on two IDENTICAL consecutive snapshots.
    assert result.state == S.SUBMITTED
