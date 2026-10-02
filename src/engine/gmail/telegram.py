"""Telegram delivery — the real Bot API (`https://api.telegram.org/bot<token>/sendMessage`).

No credentials exist on this host as of Phase 6 (confirmed: no
TELEGRAM_BOT_TOKEN/chat-id in .env, .env.example, or config.yaml). Reads
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from the environment (same
os.environ.get() pattern src/otp_resolver.py uses for GMAIL_APP_PASSWORD —
see .env.example for setup instructions). Every test in this phase mocks
HTTP — there is no valid token to make a real call with, and a real call
against an invalid/missing token would only prove network reachability,
not correctness. This is a genuine environment gap the orchestrator must
close before live delivery can be verified end-to-end.

Only invoked (by pipeline.py) for notification_level in
{Telegram Notification, High Priority Telegram Notification} — see
notification.py's TELEGRAM_TIERS.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 2  # SYSTEM_RULES.md pattern: bounded retry, never unbounded
RETRY_BACKOFF_SECONDS = 2


class TelegramUnavailable(RuntimeError):
    """Credentials missing, network unreachable, or the API returned a
    non-ok response after bounded retry."""


@dataclass(frozen=True)
class TelegramCredentials:
    bot_token: str
    chat_id: str


def load_credentials() -> TelegramCredentials | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return TelegramCredentials(token, chat_id)


def send_message(text: str, *, credentials: TelegramCredentials | None = None,
                  sleep_fn=time.sleep) -> bool:
    """Returns True on confirmed delivery (API responded ok=true). Raises
    TelegramUnavailable if credentials are missing or every bounded retry
    failed — callers never silently swallow a real delivery failure."""
    creds = credentials if credentials is not None else load_credentials()
    if creds is None:
        raise TelegramUnavailable("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not configured")

    url = f"{API_BASE}/bot{creds.bot_token}/sendMessage"
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            resp = requests.post(
                url, json={"chat_id": creds.chat_id, "text": text}, timeout=DEFAULT_TIMEOUT
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return True
            last_error = TelegramUnavailable(f"Telegram API error: {data}")
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
        if attempt <= MAX_RETRIES:
            sleep_fn(RETRY_BACKOFF_SECONDS * attempt)
    raise TelegramUnavailable(f"send_message failed after {MAX_RETRIES + 1} attempts: {last_error}")
