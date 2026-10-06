"""Phase 4: src/engine/ai/gateway.py — HTTP client + failure mapping, fully
mocked (requests.post/get monkeypatched — no real network, matching this
repo's established no-network-in-unit-tests convention)."""
from __future__ import annotations

import pytest
import requests

from engine.ai import gateway


class _FakeResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._json


def test_chat_returns_content_and_latency(monkeypatch):
    monkeypatch.setattr(
        gateway.requests, "post",
        lambda *a, **kw: _FakeResponse({"message": {"content": " hello "}}),
    )
    result = gateway.chat("scoring", "prompt")
    assert result.content == "hello"
    assert result.latency_seconds >= 0


def test_chat_raises_aiunavailable_on_connection_error(monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(gateway.requests, "post", boom)
    with pytest.raises(gateway.AIUnavailable):
        gateway.chat("scoring", "prompt")


def test_chat_raises_aitimeout_on_timeout(monkeypatch):
    def boom(*a, **kw):
        raise requests.Timeout("too slow")
    monkeypatch.setattr(gateway.requests, "post", boom)
    with pytest.raises(gateway.AITimeout):
        gateway.chat("scoring", "prompt")


def test_chat_raises_aiunavailable_on_http_error_status(monkeypatch):
    """A 500 (e.g. a crashed backend model) must be caught, not propagate
    as an unhandled requests.HTTPError."""
    monkeypatch.setattr(
        gateway.requests, "post",
        lambda *a, **kw: _FakeResponse({"error": "backend crashed"}, status=500),
    )
    with pytest.raises(gateway.AIUnavailable):
        gateway.chat("scoring", "prompt")


def test_chat_raises_aiunavailable_on_malformed_response(monkeypatch):
    monkeypatch.setattr(gateway.requests, "post", lambda *a, **kw: _FakeResponse({"unexpected": "shape"}))
    with pytest.raises(gateway.AIUnavailable):
        gateway.chat("scoring", "prompt")


def test_embed_returns_vectors(monkeypatch):
    monkeypatch.setattr(
        gateway.requests, "post",
        lambda *a, **kw: _FakeResponse({"embeddings": [[0.1, 0.2], [0.3, 0.4]]}),
    )
    vectors, latency = gateway.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert latency >= 0


def test_health_reports_unavailable_when_ollama_unreachable(monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(gateway.requests, "get", boom)
    h = gateway.health("scoring")
    assert h["available"] is False
    assert h["reason"]


def test_health_reports_available_when_model_installed(monkeypatch):
    model = gateway.load_role_config().model_for("scoring")
    monkeypatch.setattr(
        gateway.requests, "get",
        lambda *a, **kw: _FakeResponse({"models": [{"name": f"{model}:latest"}]}),
    )
    h = gateway.health("scoring")
    assert h["available"] is True


def test_health_reports_unavailable_when_model_not_installed(monkeypatch):
    monkeypatch.setattr(
        gateway.requests, "get",
        lambda *a, **kw: _FakeResponse({"models": [{"name": "some-other-model:latest"}]}),
    )
    h = gateway.health("scoring")
    assert h["available"] is False
