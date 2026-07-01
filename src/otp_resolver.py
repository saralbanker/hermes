"""
otp_resolver.py — Fetch verification codes from Gmail for unattended Indeed applies.

Indeed sends OTP to the registered email when it wants to verify identity.
This module polls Gmail via IMAP to extract that code automatically.

Setup (one-time):
  1. Go to myaccount.google.com → Security → 2-Step Verification → App passwords
  2. Create app password for "Mail"
  3. Export it: export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
     (add to ~/.zshrc or ~/.bashrc to persist across sessions)

If GMAIL_APP_PASSWORD is not set, OTP fetch is skipped and the job is marked
otp_required for manual retry later.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
import time

GMAIL_USER = "saralbanker1@gmail.com"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Poll for this many seconds waiting for the email to arrive
MAX_WAIT_SECONDS = 90
POLL_INTERVAL = 5

# Indeed verification emails come from these senders
INDEED_SENDERS = [
    "no-reply@indeed.com",
    "noreply@indeed.com",
    "verification@indeed.com",
    "security@indeed.com",
]

OTP_PATTERN = re.compile(r"\b(\d{6})\b")


def _get_app_password() -> str | None:
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    return pw if pw else None


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


def _search_recent_otp(conn: imaplib.IMAP4_SSL) -> str | None:
    """Search for an OTP code in unread Indeed emails received in the last 3 minutes."""
    conn.select("INBOX")
    # UNSEEN from Indeed sent in last 3 minutes
    _, data = conn.search(None, '(UNSEEN FROM "indeed.com" SINCE "01-Jan-2020")')
    uids = data[0].split() if data[0] else []

    for uid in reversed(uids[-10:]):  # check last 10 unread, newest first
        try:
            _, msg_data = conn.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            # Verify sender
            sender = msg.get("From", "").lower()
            if not any(s in sender for s in INDEED_SENDERS):
                continue

            # Extract body text
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            # Find 6-digit OTP
            matches = OTP_PATTERN.findall(body)
            if matches:
                # Mark as read so we don't reuse it
                conn.store(uid, "+FLAGS", "\\Seen")
                return matches[0]

        except Exception:
            continue

    return None


def fetch_otp(timeout: int = MAX_WAIT_SECONDS) -> str | None:
    """
    Poll Gmail for an Indeed verification code.
    Returns the 6-digit code string, or None if not found / IMAP not configured.
    """
    pw = _get_app_password()
    if not pw:
        print("  [otp] GMAIL_APP_PASSWORD not set — cannot auto-fetch OTP")
        print("  [otp] Set it with: export GMAIL_APP_PASSWORD='xxxx xxxx xxxx xxxx'")
        return None

    conn = _connect()
    if not conn:
        return None

    print(f"  [otp] Waiting for Indeed verification email (up to {timeout}s)...")
    deadline = time.time() + timeout

    try:
        while time.time() < deadline:
            code = _search_recent_otp(conn)
            if code:
                print(f"  [otp] Code found: {code}")
                return code
            remaining = int(deadline - time.time())
            if remaining > 0:
                print(f"  [otp] Not yet — checking again in {POLL_INTERVAL}s ({remaining}s left)...")
                time.sleep(POLL_INTERVAL)
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    print("  [otp] Timed out waiting for verification email")
    return None


def is_configured() -> bool:
    return bool(_get_app_password())
