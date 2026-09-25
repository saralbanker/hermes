"""Offline tests for the Indeed session/account safeguards added after the 2026-09-24
submission-vs-history investigation (see output/reports/indeed_reconciliation.md):
_check_indeed_login (refuse to apply anonymously), _verify_in_applied_history and
_gmail_confirmation (post-submit evidence). No real browser, no real IMAP connection —
everything network-facing is faked or monkeypatched.
"""
from __future__ import annotations

import indeed_apply as ia


class _FakeEle:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakePage:
    """Minimal stand-in for the DrissionPage object _snapshot()/_check_indeed_login()/
    _verify_in_applied_history() read from: .get(), .url, .title, .html, .ele()."""

    def __init__(self, url: str, title: str, text: str, html: str) -> None:
        self.url, self.title, self.text, self.html = url, title, text, html
        self.visited: list[str] = []

    def get(self, url: str, timeout: int = 30) -> None:
        self.visited.append(url)

    def ele(self, _selector: str, timeout: int = 1):
        return _FakeEle(self.text)


def _reset_session_cache() -> None:
    ia._session_checked = False
    ia._session_logged_in = True


# ---------------------------------------------------------------------------
# _check_indeed_login
# ---------------------------------------------------------------------------

def test_check_indeed_login_refuses_when_applied_page_shows_login_wall(monkeypatch):
    _reset_session_cache()
    page = _FakePage(url="https://secure.indeed.com/account/login", title="Sign in",
                     text="Sign in to continue", html='<input type="password">')
    detail = ia._check_indeed_login(page)
    assert detail is not None
    assert "guest" in detail.lower() or "not signed in" in detail.lower()
    assert page.visited == [ia.MYJOBS_APPLIED_URL]


def test_check_indeed_login_passes_when_applied_page_loads_normally(monkeypatch):
    _reset_session_cache()
    page = _FakePage(url=ia.MYJOBS_APPLIED_URL, title="My jobs | Indeed",
                     text="0 Saved 68 Applied 0 Interviews saralbanker1@gmail.com",
                     html="<html></html>")
    assert ia._check_indeed_login(page) is None


def test_check_indeed_login_is_cached_across_calls_in_one_process(monkeypatch):
    """One Indeed profile, one account, for the whole run — the expensive check runs once."""
    _reset_session_cache()
    page = _FakePage(url=ia.MYJOBS_APPLIED_URL, title="My jobs", text="68 Applied", html="")
    assert ia._check_indeed_login(page) is None
    page.visited.clear()
    assert ia._check_indeed_login(page) is None
    assert page.visited == []  # second call used the cached result, no second navigation


def test_check_indeed_login_never_blocks_on_an_ambiguous_failure(monkeypatch):
    _reset_session_cache()

    class _ExplodingPage:
        def get(self, *a, **kw):
            raise RuntimeError("network hiccup")

    assert ia._check_indeed_login(_ExplodingPage()) is None


# ---------------------------------------------------------------------------
# _verify_in_applied_history
# ---------------------------------------------------------------------------

def test_verify_in_applied_history_finds_company_name():
    page = _FakePage(url=ia.MYJOBS_APPLIED_URL, title="My jobs",
                     text="Backend Developer Intern ChatSpark Remote Applied today on Indeed",
                     html="")
    assert ia._verify_in_applied_history(page, {"company": "ChatSpark"}) == "; verified in Applied history"


def test_verify_in_applied_history_reports_a_miss_without_failing():
    page = _FakePage(url=ia.MYJOBS_APPLIED_URL, title="My jobs", text="Some other company entirely",
                     html="")
    result = ia._verify_in_applied_history(page, {"company": "Nagarro"})
    assert "NOT found" in result


def test_verify_in_applied_history_flags_a_logged_out_session():
    page = _FakePage(url="https://secure.indeed.com/account/login", title="Sign in",
                     text="Sign in to continue", html='<input type="password">')
    result = ia._verify_in_applied_history(page, {"company": "Nagarro"})
    assert "guest apply" in result


# ---------------------------------------------------------------------------
# _gmail_confirmation
# ---------------------------------------------------------------------------

def test_gmail_confirmation_returns_empty_string_when_not_configured(monkeypatch):
    import otp_resolver
    monkeypatch.setattr(otp_resolver, "_get_app_password", lambda: None)
    assert ia._gmail_confirmation("Any Job Title") == ""


def test_gmail_confirmation_never_raises_on_imap_failure(monkeypatch):
    import otp_resolver
    monkeypatch.setattr(otp_resolver, "_get_app_password", lambda: "fake-app-password")

    class _ExplodingIMAP:
        def __init__(self, *a, **kw):
            raise ConnectionError("no network")

    import imaplib
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _ExplodingIMAP)
    result = ia._gmail_confirmation("Backend Developer Intern")
    assert result.startswith("; gmail confirmation check failed")
