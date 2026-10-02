"""Phase 6: src/engine/gmail/telegram.py — Bot API client. No real network
call (no valid credentials exist on this host) — requests.post is fully
mocked, same boundary-mocking pattern as every prior phase."""
from __future__ import annotations

import pytest
import requests

from engine.gmail import telegram


class _FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


CREDS = telegram.TelegramCredentials(bot_token="123:ABC", chat_id="999")


def test_load_credentials_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram.load_credentials() is None


def test_load_credentials_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    creds = telegram.load_credentials()
    assert creds == CREDS


def test_send_message_raises_when_no_credentials():
    with pytest.raises(telegram.TelegramUnavailable):
        telegram.send_message("hello", credentials=None)


def test_send_message_success(monkeypatch):
    monkeypatch.setattr(
        telegram.requests, "post", lambda url, json, timeout: _FakeResponse({"ok": True})
    )
    assert telegram.send_message("hello", credentials=CREDS) is True


def test_send_message_uses_correct_url_and_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    telegram.send_message("hello world", credentials=CREDS)
    assert captured["url"] == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert captured["json"] == {"chat_id": "999", "text": "hello world"}


def test_send_message_retries_bounded_then_raises(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, json, timeout):
        calls["n"] += 1
        raise requests.ConnectionError("refused")

    sleeps = []
    monkeypatch.setattr(telegram.requests, "post", fake_post)
    with pytest.raises(telegram.TelegramUnavailable):
        telegram.send_message("hello", credentials=CREDS, sleep_fn=sleeps.append)
    assert calls["n"] == telegram.MAX_RETRIES + 1
    assert len(sleeps) == telegram.MAX_RETRIES


def test_send_message_succeeds_after_transient_failure(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, json, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("transient")
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    assert telegram.send_message("hello", credentials=CREDS, sleep_fn=lambda s: None) is True
    assert calls["n"] == 2


def test_send_message_raises_on_api_error_response(monkeypatch):
    monkeypatch.setattr(
        telegram.requests, "post",
        lambda url, json, timeout: _FakeResponse({"ok": False, "description": "bad token"}, status=401),
    )
    with pytest.raises(telegram.TelegramUnavailable):
        telegram.send_message("hello", credentials=CREDS, sleep_fn=lambda s: None)
