"""Phase 7: the additive `on_progress` parameter added to src/ats_apply.py and
src/direct_form.py (mirroring src/indeed_apply.py's Phase 3 pattern) — unit-level proof
that the two execution_phase boundaries (BROWSER_SYSTEM.md §70 "external_work_started",
§72 "submit_intent") actually fire at the right point, with no browser/network involved.

Minimal hand-rolled fakes, not a real Playwright page — just enough surface for
_open_form/_open (navigation) and _submit/_submit_direct (the final click) to run.
"""
from __future__ import annotations

import ats_apply
import direct_form


# ---------------------------------------------------------------------------
# _open_form (ats_apply.py) / _open (direct_form.py) — "external_work_started"
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status):
        self.status = status


class _FakeNavPage:
    def __init__(self, status=200, raise_exc=None):
        self._status = status
        self._raise_exc = raise_exc
        self.navigated = []

    def goto(self, url, **kwargs):
        self.navigated.append(url)
        if self._raise_exc:
            raise self._raise_exc
        return _FakeResponse(self._status)


def test_ats_open_form_fires_external_work_started_after_successful_navigation():
    page = _FakeNavPage(status=404)  # closed posting — exercised after on_progress fires
    calls = []
    code = ats_apply._open_form(page, {"apply_url": "https://job-boards.greenhouse.io/x/y"},
                                on_progress=calls.append)
    assert calls == ["external_work_started"]
    assert code == "posting_closed"


def test_ats_open_form_never_fires_on_progress_when_navigation_itself_fails():
    page = _FakeNavPage(raise_exc=ats_apply.PWTimeoutError("nav timeout"))
    calls = []
    code = ats_apply._open_form(page, {"apply_url": "https://job-boards.greenhouse.io/x/y"},
                                on_progress=calls.append)
    assert calls == []
    assert code.startswith("network_error:")


def test_direct_form_open_fires_external_work_started_after_successful_navigation():
    page = _FakeNavPage(status=410)
    calls = []
    code = direct_form._open(page, "https://acme.example/careers/1", on_progress=calls.append)
    assert calls == ["external_work_started"]
    assert code == "posting_closed"


def test_direct_form_open_never_fires_on_progress_when_navigation_itself_fails():
    page = _FakeNavPage(raise_exc=direct_form.PWTimeoutError("nav timeout"))
    calls = []
    code = direct_form._open(page, "https://acme.example/careers/1", on_progress=calls.append)
    assert calls == []
    assert code.startswith("network_error:")


# ---------------------------------------------------------------------------
# _submit (ats_apply.py) / _submit_direct (direct_form.py) — "submit_intent"
# ---------------------------------------------------------------------------

class _FakeButtonLocator:
    def __init__(self, count=1, click_exc=None):
        self._count = count
        self._click_exc = click_exc
        self.clicked = False

    def count(self):
        return self._count

    @property
    def last(self):
        return self

    def click(self, *args, **kwargs):
        self.clicked = True
        if self._click_exc:
            raise self._click_exc


class _FakeKeyboard:
    def press(self, *args, **kwargs):
        pass


class _FakeSubmitPage:
    def __init__(self, button, body_sequence):
        self._button = button
        self._body_sequence = list(body_sequence)
        self.url = "https://x/apply"
        self.keyboard = _FakeKeyboard()
        self.frames = []  # _captcha_challenge_visible iterates this; empty = no captcha

    def locator(self, _selector):
        return self._button

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, _ms):
        pass

    def inner_text(self, _selector):
        return self._body_sequence.pop(0) if self._body_sequence else ""

    def on(self, _event, _callback):
        pass

    def remove_listener(self, _event, _callback):
        pass


def test_ats_submit_fires_submit_intent_right_after_the_click_succeeds():
    button = _FakeButtonLocator(count=1)
    # First inner_text call is _submit's pre-click baseline read; the second is the first
    # post-click poll, which already carries the success text.
    page = _FakeSubmitPage(button, body_sequence=["", "Thank you for applying to this role"])
    calls = []
    code, evidence = ats_apply._submit(page, on_progress=calls.append)
    assert calls == ["submit_intent"]
    assert code is None
    assert "thank you" in evidence.lower()


def test_ats_submit_never_fires_on_progress_when_the_click_itself_fails():
    button = _FakeButtonLocator(count=1, click_exc=ats_apply.PWTimeoutError("click timeout"))
    page = _FakeSubmitPage(button, body_sequence=[""])
    calls = []
    code, evidence = ats_apply._submit(page, on_progress=calls.append)
    assert calls == []
    assert code.startswith("network_error:")


def test_direct_form_submit_fires_submit_intent_right_after_the_click_succeeds():
    button = _FakeButtonLocator(count=1)
    page = _FakeSubmitPage(button, body_sequence=["Your application has been received"])
    calls = []
    code, evidence = direct_form._submit_direct(page, on_progress=calls.append)
    assert calls == ["submit_intent"]
    assert code is None


def test_direct_form_submit_never_fires_on_progress_when_the_click_itself_fails():
    button = _FakeButtonLocator(count=1, click_exc=direct_form.PWTimeoutError("click timeout"))
    page = _FakeSubmitPage(button, body_sequence=[])
    calls = []
    code, evidence = direct_form._submit_direct(page, on_progress=calls.append)
    assert calls == []
    assert code.startswith("network_error:")


# ---------------------------------------------------------------------------
# Legacy call path (src/apply.py, via run_ats_apply/run_direct_apply's default
# on_progress=None) must remain completely unaffected.
# ---------------------------------------------------------------------------

def test_open_form_default_on_progress_is_none_and_nothing_breaks():
    page = _FakeNavPage(status=404)
    assert ats_apply._open_form(page, {"apply_url": "https://x"}) == "posting_closed"


def test_direct_open_default_on_progress_is_none_and_nothing_breaks():
    page = _FakeNavPage(status=410)
    assert direct_form._open(page, "https://acme.example/careers/1") == "posting_closed"
