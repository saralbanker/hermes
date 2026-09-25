"""Offline tests for the generic direct-company-form engine: regex classification and
error-code -> ApplyResult mapping. No network, no browser — nothing here launches
Playwright."""
from __future__ import annotations

import pytest

import direct_form as df
import states as S


# ---------------------------------------------------------------------------
# Cookie-accept / Next-button / wall-detection regexes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Accept All Cookies", "Accept all", "Allow all cookies", "Allow All",
    "I Agree", "I accept", "Got it", "Agree and continue",
])
def test_cookie_accept_re_matches_common_banner_labels(text):
    assert df.COOKIE_ACCEPT_RE.match(text)


@pytest.mark.parametrize("text", [
    "Reject All", "Cookies Settings", "Manage preferences", "Decline",
])
def test_cookie_accept_re_never_matches_reject_or_settings(text):
    assert not df.COOKIE_ACCEPT_RE.match(text)


@pytest.mark.parametrize("text", ["Next", "Continue", "Proceed", "Proceed to next step"])
def test_next_re_matches_step_advance_labels(text):
    assert df.NEXT_RE.match(text)


@pytest.mark.parametrize("text", ["Submit", "Submit Application", "Apply now", "Back"])
def test_next_re_does_not_match_submit_or_back(text):
    assert not df.NEXT_RE.match(text)


def test_login_wall_re_matches_only_with_apply_context():
    assert df.LOGIN_WALL_RE.search("Please sign in to continue your application")
    assert not df.LOGIN_WALL_RE.search("Sign in")  # header link — not a wall by itself


def test_account_wall_re_matches_signup_requirement():
    assert df.ACCOUNT_WALL_RE.search("Create an account to apply for this role")
    assert not df.ACCOUNT_WALL_RE.search("Create a great cover letter")


# ---------------------------------------------------------------------------
# _map_error — direct_form-specific codes, then fallthrough to ats_apply's mapper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected_state", [
    ("login_wall", S.FORM_CHANGED),
    ("account_wall", S.FORM_CHANGED),
    ("form_not_submitted", S.FORM_CHANGED),
    ("posting_closed", S.EXPIRED),               # falls through to ats_apply._result_for_error
    ("captcha_blocked", S.CAPTCHA_REQUIRED),
    ("unanswerable:Pronouns", S.FORM_CHANGED),
    ("unconfirmed", S.SUBMISSION_UNCONFIRMED),
])
def test_map_error_returns_expected_state(code, expected_state):
    result = df._map_error(code, screenshot="shot.png")
    assert isinstance(result, S.ApplyResult)
    assert result.state == expected_state
    assert result.screenshot == "shot.png"


def test_map_error_login_wall_is_not_the_indeed_login_required_state():
    """A generic company site's login wall is not Hermes's own Indeed session expiring —
    it must never trigger indeed_setup.py re-login guidance."""
    result = df._map_error("login_wall", screenshot=None)
    assert result.state != S.LOGIN_REQUIRED


# ---------------------------------------------------------------------------
# run_direct_apply — no URL to open at all
# ---------------------------------------------------------------------------

def test_run_direct_apply_fails_explicitly_with_no_url():
    result = df.run_direct_apply({"url": None, "direct_apply_url": None}, "cover", "resume.pdf", "shot.png")
    assert result.state == S.FORM_CHANGED
    assert "no direct apply url" in result.detail.lower()


def test_run_direct_apply_falls_back_to_job_url_when_no_direct_url_set(monkeypatch):
    """A job discovered directly on a company's own site (no aggregator redirect involved)
    has no direct_apply_url — job['url'] itself is the form to open."""
    seen = {}

    def fake_apply_in_browser(ctx, url, *_args, **_kw):
        seen["url"] = url
        return S.ApplyResult(S.DRY_RUN_OK, detail="ok")

    monkeypatch.setattr(df, "_apply_in_browser", fake_apply_in_browser)
    monkeypatch.setattr(df, "sync_playwright", lambda: _FakePW())
    monkeypatch.setattr(df, "_launch", lambda pw: _FakeCtx())

    result = df.run_direct_apply({"url": "https://acme.example/careers/123", "direct_apply_url": None},
                                 "cover", "resume.pdf", "shot.png", dry_run=True)
    assert seen["url"] == "https://acme.example/careers/123"
    assert result.state == S.DRY_RUN_OK


class _FakeCtx:
    def close(self):
        pass


class _FakePW:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
