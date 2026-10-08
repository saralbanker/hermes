"""Offline tests for indeed_evidence (read-only capture for the disabled-Submit incident).
No browser: the page is a fake; sleep/clock are injected."""
from __future__ import annotations

import json

import pytest

import indeed_apply as ia
import indeed_evidence as ev
from browser_watchdog import AttemptAbortContext, HardTimeoutError


class FakePage:
    url = "https://smartapply.indeed.com/review"
    html = "<html>fresh</html>"

    def __init__(self, enable_after_calls: int | None = None) -> None:
        self.shots: list[tuple] = []
        self.js_calls = 0
        self.enable_after = enable_after_calls
        self.clicked = False

    def ele(self, *_a, **_kw):
        class _Body:
            text = "fresh text"
        return _Body()

    def get_screenshot(self, **kw) -> None:
        self.shots.append((kw.get("name"), kw.get("full_page")))

    def run_js(self, script: str):
        if script == ia._ALL_BUTTONS_JS:
            return ["Save and close", "Submit your application[disabled]"]
        self.js_calls += 1
        disabled = not (self.enable_after is not None and self.js_calls > self.enable_after)
        return json.dumps({"submit": [{"disabled": disabled, "attrs": {}, "rect": {"in_viewport": False}}],
                           "busy": {"ready_state": "complete", "aria_busy": []},
                           "invalid_aria": [], "file_inputs": [{"n_files": 1}]})

    def click(self, *_a, **_kw) -> None:  # must never be called
        self.clicked = True


def test_is_disabled_submit():
    assert ev.is_disabled_submit(["Save and close", "Submit your application[disabled]"])
    assert ev.is_disabled_submit(["submit[disabled]"])
    assert not ev.is_disabled_submit(["Submit your application"])
    assert not ev.is_disabled_submit(["Continue[disabled]"])
    assert not ev.is_disabled_submit("<scan failed: boom>")


def test_capture_is_noop_without_env(monkeypatch):
    monkeypatch.delenv(ev.EVIDENCE_ENV, raising=False)
    page = FakePage()
    assert ev.capture_disabled_submit(page, {}, "t", "h") is None
    assert page.js_calls == 0 and page.shots == []


def test_capture_writes_artifacts_and_polls(monkeypatch, tmp_path):
    monkeypatch.setenv(ev.EVIDENCE_ENV, str(tmp_path))
    page = FakePage(enable_after_calls=4)
    ticks = {"t": 0.0}
    out = ev.capture_disabled_submit(
        page, {"url": "u", "title": "Full Stack Dev!", "attempts": 2}, "stale", "stale",
        sleep=lambda s: ticks.__setitem__("t", ticks["t"] + s), clock=lambda: ticks["t"])
    names = {p.name for p in out.iterdir()}
    assert [n for n, _ in page.shots] == ["full_page.png", "full_page_final.png"]  # fake page writes no PNGs
    assert {"page.html", "visible_text.txt", "probe_t0.json",
            "probe_final.json", "submit_poll.jsonl", "meta.json"} <= names
    assert (out / "page.html").read_text() == "<html>fresh</html>"  # fresh read, not the stale snapshot
    assert (out / "visible_text.txt").read_text() == "fresh text"
    assert all(full for _, full in page.shots)
    rows = [json.loads(line) for line in (out / "submit_poll.jsonl").read_text().splitlines()]
    assert [r["t"] for r in rows] == [5.0 * i for i in range(13)]  # every 5 s for 60 s
    meta = json.loads((out / "meta.json").read_text())
    assert meta["submit_enabled_at_s"] == 20.0 and meta["samples"] == 13
    assert "full-stack-dev" in out.name and not page.clicked


def test_form_changed_result_unchanged_and_capture_invoked(monkeypatch, tmp_path):
    monkeypatch.setenv(ev.EVIDENCE_ENV, str(tmp_path))
    seen = {}
    monkeypatch.setattr(ev, "capture_disabled_submit",
                        lambda page, job, text, html, abort_context=None: seen.update(job=job))
    r = ia._form_changed_no_control(FakePage(), "t", "h", "", job={"url": "u"})
    assert r.state == "form_changed" and "Submit your application[disabled]" in r.detail
    assert seen["job"] == {"url": "u"}


def test_hard_timeout_wins_during_poll(monkeypatch, tmp_path):
    monkeypatch.setenv(ev.EVIDENCE_ENV, str(tmp_path))
    ctx = AttemptAbortContext()
    ctx.trigger_timeout("watchdog fired")
    with pytest.raises(HardTimeoutError):
        ev.capture_disabled_submit(FakePage(), {}, "t", "h", abort_context=ctx, sleep=lambda s: None)
