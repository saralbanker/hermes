"""Offline tests for otp_resolver.py: app-password resolution (file vs env var, whitespace),
per-platform code extraction (Indeed's 6-digit, Greenhouse's alphanumeric), and the
since_ts freshness filter. No real IMAP connection anywhere here.
"""
from __future__ import annotations

import email
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import pytest

import otp_resolver as otp


# ---------------------------------------------------------------------------
# _get_app_password — file-vs-env priority and whitespace stripping
# ---------------------------------------------------------------------------

def test_app_password_strips_internal_whitespace_from_file(tmp_path, monkeypatch):
    # Real bug, 2026-09-25: Google's App Password page shows it grouped ("abcd efgh ijkl
    # mnop"); .strip() alone leaves the internal spaces, and imaplib's LOGIN then fails
    # with an otherwise-valid password.
    pw_file = tmp_path / "pw.txt"
    pw_file.write_text("ssex ccrs afmy ejha\n")
    monkeypatch.setattr(otp, "_APP_PW_FILE", pw_file)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert otp._get_app_password() == "ssexccrsafmyejha"


def test_app_password_prefers_file_over_a_stale_env_var(tmp_path, monkeypatch):
    # Real bug, 2026-09-25: ~/.zshrc derives GMAIL_APP_PASSWORD from this same file on
    # every new shell, so the file is the true source of truth — a shell session that
    # predates a password rotation keeps a stale env var while the file is already
    # current. File must win.
    pw_file = tmp_path / "pw.txt"
    pw_file.write_text("current pass word")
    monkeypatch.setattr(otp, "_APP_PW_FILE", pw_file)
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "stale env password")
    assert otp._get_app_password() == "currentpassword"


def test_app_password_falls_back_to_env_var_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(otp, "_APP_PW_FILE", tmp_path / "does-not-exist.txt")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "only env pass")
    assert otp._get_app_password() == "onlyenvpass"


def test_app_password_none_when_neither_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(otp, "_APP_PW_FILE", tmp_path / "does-not-exist.txt")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert otp._get_app_password() is None
    assert otp.is_configured() is False


# ---------------------------------------------------------------------------
# Per-platform code patterns
# ---------------------------------------------------------------------------

def test_indeed_pattern_extracts_six_digit_code():
    body = "Your Indeed verification code is 482913. It expires in 10 minutes."
    m = otp.PLATFORMS["indeed"]["pattern"].search(body)
    assert m and m.group(1) == "482913"


def test_greenhouse_pattern_extracts_real_alphanumeric_code():
    # Verbatim (HTML-stripped) text from a real Cloudflare/Greenhouse verification email.
    body = (" Copy and paste this code into the security code field on your application: "
            "b9rOznso After you enter the code, resubmit your application.")
    m = otp.PLATFORMS["greenhouse"]["pattern"].search(body)
    assert m and m.group(1) == "b9rOznso"


def test_extract_text_strips_html_tags():
    msg = email.message_from_string(
        "Content-Type: text/html\n\n<p>Your code: <b>ab12cd34</b></p>")
    assert "<b>" not in otp._extract_text(msg)
    assert "ab12cd34" in otp._extract_text(msg)


# ---------------------------------------------------------------------------
# _matching_code — sender verification + since_ts freshness filter
# ---------------------------------------------------------------------------

def _make_email(sender: str, body: str, when: datetime) -> email.message.Message:
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["Date"] = format_datetime(when)
    msg.set_content(body)
    return msg


GH_BODY = "Copy and paste this code into the security code field: b9rOznso"


def test_matching_code_rejects_wrong_sender():
    msg = _make_email("no-reply@some-other-ats.io", GH_BODY, datetime.now(timezone.utc))
    assert otp._matching_code(msg, otp.PLATFORMS["greenhouse"], None) is None


def test_matching_code_accepts_known_greenhouse_sender():
    msg = _make_email("Greenhouse <no-reply@us.greenhouse-mail.io>", GH_BODY,
                      datetime.now(timezone.utc))
    assert otp._matching_code(msg, otp.PLATFORMS["greenhouse"], None) == "b9rOznso"


def test_matching_code_rejects_email_older_than_since_ts():
    # A stale code from an earlier attempt on the same job must never be reused.
    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    msg = _make_email("no-reply@us.greenhouse-mail.io", GH_BODY, old)
    since_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    assert otp._matching_code(msg, otp.PLATFORMS["greenhouse"], since_ts) is None


def test_matching_code_accepts_email_newer_than_since_ts():
    fresh = datetime.now(timezone.utc)
    msg = _make_email("no-reply@us.greenhouse-mail.io", GH_BODY, fresh)
    since_ts = (fresh - timedelta(minutes=1)).timestamp()
    assert otp._matching_code(msg, otp.PLATFORMS["greenhouse"], since_ts) == "b9rOznso"


def test_fetch_otp_rejects_unknown_platform():
    with pytest.raises(ValueError):
        otp.fetch_otp(platform="workday")


def test_fetch_otp_returns_none_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(otp, "_APP_PW_FILE", tmp_path / "missing.txt")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert otp.fetch_otp(timeout=1, platform="greenhouse") is None
