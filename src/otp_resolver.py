"""
otp_resolver.py — Fetch verification codes from Gmail for unattended Indeed/ATS applies.

Platforms:
  indeed:     6-digit numeric code, sent by *.indeed.com.
  greenhouse: 6-10 character alphanumeric code ("Copy and paste this code into the
              security code field..."), sent by *.greenhouse-mail.io. Verified live
              against a real Cloudflare application, 2026-09-24.

Setup (one-time):
  1. Go to myaccount.google.com → Security → 2-Step Verification → App passwords
  2. Create app password for "Mail"
  3. Export it: export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
     (add to ~/.zshrc or ~/.bashrc to persist across sessions), or write it to
     output/gmail_app_password.txt. Google's own page displays it grouped with spaces
     for readability, but IMAP LOGIN rejects it with them — _get_app_password() strips
     all whitespace regardless of source (2026-09-25: a real, previously-undiagnosed bug —
     a valid password was rejected every time because the on-disk copy kept its spaces).

If no app password resolves, OTP fetch is skipped and the job is marked otp_required
for manual retry later.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
import time
from email.utils import parsedate_to_datetime
from pathlib import Path

GMAIL_USER = "saralbanker1@gmail.com"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

_APP_PW_FILE = Path(__file__).parent.parent / "output" / "gmail_app_password.txt"

# Poll for this many seconds waiting for the email to arrive
MAX_WAIT_SECONDS = 90
POLL_INTERVAL = 5

# Per-platform: an IMAP-side sender substring (fast server-side filter), the exact sender
# addresses to verify against (belt-and-braces against a coincidental substring match
# elsewhere), and the code's own shape/extraction pattern.
PLATFORMS: dict[str, dict] = {
    "indeed": {
        "domain": "indeed.com",
        "senders": ["no-reply@indeed.com", "noreply@indeed.com", "verification@indeed.com",
                    "security@indeed.com"],
        "pattern": re.compile(r"\b(\d{6})\b"),
    },
    "greenhouse": {
        "domain": "greenhouse-mail.io",
        "senders": ["no-reply@us.greenhouse-mail.io", "no-reply@greenhouse-mail.io"],
        "pattern": re.compile(r"\bcode\b[^:]{0,60}:\s*([A-Za-z0-9]{6,10})\b", re.IGNORECASE),
    },
}

# Backward-compatible names — indeed_apply.py and tests import these directly.
INDEED_SENDERS = PLATFORMS["indeed"]["senders"]
OTP_PATTERN = PLATFORMS["indeed"]["pattern"]


def _get_app_password() -> str | None:
    """The file is the source of truth (~/.zshrc itself derives GMAIL_APP_PASSWORD from
    this same file on every new shell — see its own export line); the env var is only a
    per-session cache of it and can go stale in a shell that predates a password rotation
    while the file is already current. Confirmed live 2026-09-25: this exact mismatch (a
    stale env var next to a fresh, working file) made every login fail even after fixing
    the whitespace bug below. File first, env var only when no file exists (e.g. a bare
    manual `export` with no repo checked out yet).

    Strips ALL whitespace, not just leading/trailing, either way: Google's App Password
    page displays the credential grouped as "abcd efgh ijkl mnop" for readability, and
    imaplib's LOGIN fails with those spaces left in (also confirmed live 2026-09-25 —
    identical password, spaces were the only difference)."""
    pw = ""
    try:
        if _APP_PW_FILE.exists():
            pw = _APP_PW_FILE.read_text()
    except Exception:
        pw = ""
    if not pw.strip():
        pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    pw = re.sub(r"\s+", "", pw)
    return pw or None


def _connect() -> imaplib.IMAP4_SSL | None:
    pw = _get_app_password()
    if not pw:
        return None
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        conn.login(GMAIL_USER, pw)
        return conn
    except Exception as e:
        print(f"  [otp] Gmail IMAP connect failed: {e}")
        return None


def _email_timestamp(msg: email.message.Message) -> float:
    """Unix timestamp of the email's own Date header, or 0.0 if unparseable (so it never
    passes a since_ts filter by accident)."""
    try:
        dt = parsedate_to_datetime(msg.get("Date", ""))
        return dt.timestamp() if dt else 0.0
    except Exception:
        return 0.0


def _extract_text(msg: email.message.Message) -> str:
    """Plain text with any HTML tags stripped — several ATS confirmation emails (Greenhouse
    included) are HTML-only, no text/plain alternative part."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                parts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
    else:
        parts.append(msg.get_payload(decode=True).decode("utf-8", errors="ignore"))
    return re.sub(r"<[^>]+>", " ", "\n".join(parts))


def _matching_code(msg: email.message.Message, spec: dict, since_ts: float | None) -> str | None:
    sender = (msg.get("From") or "").lower()
    if not any(s in sender for s in spec["senders"]):
        return None
    if since_ts and _email_timestamp(msg) < since_ts:
        return None
    match = spec["pattern"].search(_extract_text(msg))
    return match.group(1) if match else None


def _search_recent_otp(conn: imaplib.IMAP4_SSL, platform: str, since_ts: float | None) -> str | None:
    """The newest matching code for `platform` received at/after since_ts, or None."""
    spec = PLATFORMS[platform]
    conn.select("INBOX")
    _, data = conn.search(None, f'(FROM "{spec["domain"]}" SINCE "01-Jan-2020")')
    uids = data[0].split() if data[0] else []

    found: list[tuple[float, bytes, str]] = []
    for uid in uids[-15:]:  # newest last in IMAP's own ordering
        try:
            _, msg_data = conn.fetch(uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            code = _matching_code(msg, spec, since_ts)
            if code:
                found.append((_email_timestamp(msg), uid, code))
        except Exception:
            continue
    if not found:
        return None
    found.sort(key=lambda f: f[0])
    _, uid, code = found[-1]
    try:
        conn.store(uid, "+FLAGS", "\\Seen")
    except Exception:
        pass
    return code


def fetch_otp(timeout: int = MAX_WAIT_SECONDS, platform: str = "indeed",
             since_ts: float | None = None) -> str | None:
    """
    Poll Gmail for a verification code from `platform` ("indeed" | "greenhouse"), received
    at/after since_ts (pass a timestamp from just before the submit click, so a stale code
    from an earlier attempt on the same job is never reused). Returns the code, or None if
    not found / IMAP not configured within `timeout` seconds.
    """
    if platform not in PLATFORMS:
        raise ValueError(f"unknown OTP platform: {platform!r}")
    conn = _connect()
    if not conn:
        print(f"  [otp] Gmail not configured or login failed — cannot auto-fetch {platform} OTP")
        return None

    print(f"  [otp] Waiting for {platform} verification email (up to {timeout}s)...")
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            code = _search_recent_otp(conn, platform, since_ts)
            if code:
                print(f"  [otp] Code found: {code}")
                return code
            remaining = int(deadline - time.time())
            if remaining > 0:
                print(f"  [otp] Not yet — checking again in {POLL_INTERVAL}s ({remaining}s left)...")
                time.sleep(min(POLL_INTERVAL, remaining))
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    print(f"  [otp] Timed out waiting for {platform} verification email")
    return None


def is_configured() -> bool:
    return bool(_get_app_password())
