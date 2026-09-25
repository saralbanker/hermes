"""Offline tests for redirect_resolver's shared destination classifier and the new
resolve_indeed_external (Indeed's own 'Apply on company site' redirect, e.g.
/applystart?jk=...). No browser: _open_browser is monkeypatched with a fake page.
"""
from __future__ import annotations

import json

import redirect_resolver as rr


def test_classify_destination_recognizes_a_known_ats():
    result = rr._classify_destination(
        "https://in.indeed.com/applystart?jk=x",
        "https://jobs.lever.co/acme/6f78b170-9600-4b2d-9682-feead160100d", "")
    assert result["error"] is None
    assert result["channel"] == "lever"


def test_classify_destination_flags_account_wall():
    result = rr._classify_destination(
        "https://himalayas.app/companies/acme/jobs/x",
        "https://himalayas.app/signup/talent?redirect=x", "")
    assert result["error"].startswith("account_required:")


def test_classify_destination_flags_sponsored_link():
    result = rr._classify_destination(
        "https://himalayas.app/companies/acme/jobs/x",
        "https://aiapply.co/?utm_source=jobboardsads&utm_campaign=x", "")
    assert result["error"].startswith("sponsored_link:")


def test_classify_destination_does_not_flag_a_legitimate_tracked_career_page():
    """Indeed's own 'Apply on company site' redirects attach utm_source=indeed_integration
    to perfectly legitimate employer career pages (verified live: careers.avalara.com) —
    a deep, job-specific path must not be misclassified as a sponsored/ad link."""
    result = rr._classify_destination(
        "https://in.indeed.com/applystart?jk=x",
        "https://careers.avalara.com/careers-home/jobs/17244/job?utm_source=indeed_integration"
        "&iis=Job%20Board&indeed-apply-token=abc123", "")
    assert result["error"] == "unsupported_destination:careers.avalara.com"


def test_classify_destination_falls_back_to_unsupported():
    result = rr._classify_destination(
        "https://in.indeed.com/applystart?jk=x", "https://careers.acme.com/job/123", "")
    assert result["error"] == "unsupported_destination:careers.acme.com"


class _FakePage:
    def __init__(self, url: str, html: str = "") -> None:
        self.url = url
        self.html = html

    def get(self, _url: str, timeout: int = 30) -> None:
        pass

    def quit(self) -> None:
        pass


def test_resolve_indeed_external_reaches_a_known_ats(monkeypatch):
    monkeypatch.setattr(rr, "_open_browser",
                        lambda: _FakePage("https://boards.greenhouse.io/acme/jobs/7764109003"))
    monkeypatch.setattr(rr.time, "sleep", lambda *_a: None)
    result = rr.resolve_indeed_external("https://in.indeed.com/applystart?jk=abc")
    assert result["error"] is None
    assert result["channel"] == "greenhouse"


def test_resolve_indeed_external_reports_browser_failure_without_raising(monkeypatch):
    def _explode():
        raise RuntimeError("CDP connection refused")

    monkeypatch.setattr(rr, "_open_browser", _explode)
    result = rr.resolve_indeed_external("https://in.indeed.com/applystart?jk=abc")
    assert result["final_url"] is None
    assert result["error"].startswith("redirect_browser_error:")
