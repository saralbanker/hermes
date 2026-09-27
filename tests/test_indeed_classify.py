"""
Unit tests for indeed_apply.classify_page() — a pure function, no browser needed.

Each fixture in tests/fixtures/indeed/ is a small HTML snippet representative of
one page class Indeed can serve. The most important case (job_page.html and
security_interstitial.html) both contain the header's permanent "Sign in" link;
the old classifier matched on that word alone and misread 853 real Cloudflare
challenge pages as login walls during the last production run. These tests
guard against that regression directly.
"""
from __future__ import annotations

from pathlib import Path

import bs4
import pytest

from indeed_apply import classify_page

FIXTURES = Path(__file__).parent / "fixtures" / "indeed"


def _load(name: str) -> tuple[str, str]:
    """(title, html) from a fixture file."""
    html = (FIXTURES / name).read_text()
    soup = bs4.BeautifulSoup(html, "html.parser")
    title = soup.title.text if soup.title else ""
    return title, html


def _text(html: str) -> str:
    return bs4.BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


@pytest.mark.parametrize(
    "fixture, url, expected",
    [
        ("job_page.html", "https://in.indeed.com/viewjob?jk=abc123", "job_page"),
        ("security_interstitial.html", "https://in.indeed.com/viewjob?jk=abc123", "security_interstitial"),
        ("login.html", "https://secure.indeed.com/auth", "login"),
        ("otp.html", "https://secure.indeed.com/challenge/otp", "otp"),
        ("captcha.html", "https://in.indeed.com/viewjob?jk=abc123", "captcha"),
        ("success.html", "https://smartapply.indeed.com/beta/indeedapply/postapply", "success"),
        ("already_applied.html", "https://in.indeed.com/viewjob?jk=abc123", "already_applied"),
        ("expired.html", "https://in.indeed.com/viewjob?jk=abc123", "expired"),
        ("application.html", "https://smartapply.indeed.com/beta/indeedapply/form/contact-info", "application"),
    ],
)
def test_classify_page(fixture, url, expected):
    title, html = _load(fixture)
    text = _text(html)
    assert classify_page(url, title, text, html) == expected


def test_cloudflare_page_never_classifies_as_login_despite_sign_in_link():
    """Regression guard: the Indeed header's "Sign in" link is present on nearly
    every page, including Cloudflare interstitials. The word alone must never
    be enough to call something a login wall."""
    title, html = _load("security_interstitial.html")
    assert "Sign in" in html
    text = _text(html)
    assert classify_page("https://in.indeed.com/viewjob?jk=abc123", title, text, html) != "login"


def test_job_page_with_sign_in_header_is_not_login():
    title, html = _load("job_page.html")
    assert "Sign in" in html
    text = _text(html)
    assert classify_page("https://in.indeed.com/viewjob?jk=abc123", title, text, html) == "job_page"


def test_unknown_page_falls_back_safely():
    assert classify_page("https://example.com/", "Example Domain", "hello world", "<html></html>") == "unknown"


def test_empty_inputs_do_not_raise():
    assert classify_page("", "", "", "") == "unknown"


def test_real_signed_in_job_page_is_not_a_wall():
    """Regression (2026-09-23): live Indeed viewjob page captured from Xvfb Chrome.
    The old classifier matched script/i18n strings in the HTML and returned
    security_interstitial / otp for this ordinary page."""
    from pathlib import Path
    from indeed_apply import classify_page
    fx = Path(__file__).parent / "fixtures" / "indeed"
    html = (fx / "real_job_page_cf_script.html").read_text()
    title, text = (fx / "real_job_page_cf_script.txt").read_text().split("\n\x00\n", 1)
    assert classify_page("https://in.indeed.com/viewjob?jk=abc", title, text, html) == "job_page"


def test_pick_button_prefers_visible_semantic_controls():
    from indeed_apply import _pick_button
    header = [["0", "reject all", ""], ["1", "save and close", "ExitLinkWithModalComponent-exitButton"]]
    assert _pick_button(header + [["2", "continue", "continue-button"]]) == ("2", False)
    assert _pick_button(header + [["3", "submit your application", ""]]) == ("3", True)
    assert _pick_button(header) == (None, False)


def test_indeed_404_is_expired():
    from indeed_apply import classify_page
    text = "Sign in\nWe can’t find this page\nIt looks like this page doesn't exist or isn't available right now."
    assert classify_page("https://in.indeed.com/viewjob?jk=x", "Page not found", text, "<html></html>") == "expired"
