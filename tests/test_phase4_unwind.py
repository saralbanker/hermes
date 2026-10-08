import time
from pathlib import Path
import sys
import pytest

# Ensure src is on sys.path
SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import states as S
import indeed_apply as ia
from browser_watchdog import AttemptAbortContext, HardTimeoutError
from DrissionPage.errors import PageDisconnectedError, BrowserConnectError


class FakeDisconnectedPage:
    def __init__(self):
        self.call_count = 0

    def run_js(self, script):
        self.call_count += 1
        raise PageDisconnectedError("CDP connection closed")

    def ele(self, selector, timeout=2):
        raise PageDisconnectedError("CDP connection closed")


def test_control_discovery_short_circuits_on_page_disconnected():
    page = FakeDisconnectedPage()
    abort_ctx = AttemptAbortContext()

    start = time.monotonic()
    with pytest.raises(HardTimeoutError, match="browser disconnected"):
        ia._click_next_or_submit(page, dry_run=False, abort_context=abort_ctx)
    elapsed = time.monotonic() - start

    # Must exit immediately on disconnection, NOT retry 6 times (12-13s)
    assert elapsed < 1.0
    assert page.call_count == 1


def test_control_discovery_short_circuits_on_abort_context():
    page = FakeDisconnectedPage()
    abort_ctx = AttemptAbortContext()
    abort_ctx.trigger_timeout("watchdog forced abort")

    start = time.monotonic()
    with pytest.raises(HardTimeoutError, match="watchdog forced abort"):
        ia._click_next_or_submit(page, dry_run=False, abort_context=abort_ctx)
    elapsed = time.monotonic() - start

    assert elapsed < 0.2
    assert page.call_count == 0  # Did not even invoke JS


def test_interstitial_wait_short_circuits_on_abort():
    class FakePage:
        def url(self): return "https://indeed.com"

    abort_ctx = AttemptAbortContext()
    abort_ctx.trigger_timeout("deadline reached")

    start = time.monotonic()
    with pytest.raises(HardTimeoutError, match="deadline reached"):
        ia._wait_out_interstitial(FakePage(), deadline=time.monotonic() + 20, abort_context=abort_ctx)
    elapsed = time.monotonic() - start

    assert elapsed < 0.2


def test_drive_application_short_circuits_on_abort():
    class FakePage:
        url = "https://indeed.com"

    abort_ctx = AttemptAbortContext()
    abort_ctx.trigger_timeout("timeout at step 1")

    with pytest.raises(HardTimeoutError, match="timeout at step 1"):
        ia._drive_application(
            FakePage(),
            job={"url": "https://indeed.com/job/1"},
            cover_letter="",
            resume_path="",
            screenshot_path="",
            dry_run=False,
            deadline=time.monotonic() + 300,
            abort_context=abort_ctx,
        )


def test_form_changed_no_control_propagates_timeout():
    page = FakeDisconnectedPage()
    abort_ctx = AttemptAbortContext()
    abort_ctx.trigger_timeout("aborted during no-control dump")

    with pytest.raises(HardTimeoutError, match="aborted during no-control dump"):
        ia._form_changed_no_control(page, "text", "html", "", abort_context=abort_ctx)


def test_interstitial_reloads_once_when_check_never_clears(monkeypatch):
    """Fresh profiles are challenged on their first Indeed load; the page must be reloaded
    once after the passive wait, and the reload's page class is what counts."""
    class FakePage:
        def __init__(self):
            self.loads = []

        def get(self, url, timeout=None):
            self.loads.append(url)

    page = FakePage()
    challenge = ("https://in.indeed.com/viewjob?jk=1", "Just a moment...", "", "")
    job_page = ("https://in.indeed.com/viewjob?jk=1", "Dev - Indeed", "Apply now", "")
    monkeypatch.setattr(ia, "INTERSTITIAL_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(ia.time, "sleep", lambda s: None)
    monkeypatch.setattr(ia, "_snapshot", lambda p: job_page if p.loads else challenge)
    monkeypatch.setattr(ia, "classify_page",
                        lambda u, t, x, h: "security_interstitial" if t == "Just a moment..." else "job_page")

    cls = ia._wait_out_interstitial(page, deadline=time.monotonic() + 60)

    assert cls == "job_page"
    assert page.loads == ["https://in.indeed.com/viewjob?jk=1"]


def test_fill_selects_uses_tag_locator_not_bare_css():
    """A bare 'css:select' goes to CDP DOM.performSearch, which also plain-text matches and
    hit 61 <link> tags on Indeed's resume-selection page (2026-10-07 incident)."""
    class FakePage:
        def __init__(self):
            self.locators = []

        def eles(self, locator, timeout=None):
            self.locators.append(locator)
            return []

    page = FakePage()
    assert ia._fill_selects(page) is None
    assert page.locators == ["tag:select"]
