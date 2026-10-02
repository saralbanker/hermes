"""Phase 4: src/engine/ai/resource_arbiter.py — SYSTEM_RULES.md §24 joint
RSS-ceiling rule, AI_SYSTEM.md §74 Active Browser Priority."""
from __future__ import annotations

from engine.ai import resource_arbiter as ra


def test_measure_ollama_rss_returns_real_nonnegative_number():
    """Real measurement (no mocking) — proves the psutil-based scan runs
    without error on this host, per AI_SYSTEM.md §101 'RSS where
    measurable' being a real operational metric, not an estimate."""
    assert ra.measure_ollama_rss_bytes() >= 0


def test_measure_browser_rss_with_explicit_pids_is_empty_for_bogus_pid():
    assert ra.measure_browser_rss_bytes(browser_pids=[999999999]) == 0


def test_active_browser_priority_always_proceeds_even_over_ceiling(monkeypatch):
    """AI_SYSTEM.md §74: an active browser attempt's own AI call must never
    be deferred by the joint ceiling — deferring it would itself violate §74."""
    monkeypatch.setattr(ra, "measure_browser_rss_bytes", lambda *a, **kw: 50 * 1024**3)
    monkeypatch.setattr(ra, "measure_ollama_rss_bytes", lambda: 50 * 1024**3)
    decision = ra.arbitrate_model_load(priority=ra.Priority.ACTIVE_BROWSER)
    assert decision.proceed is True
    assert "§74" in decision.reason or "active" in decision.reason.lower()


def test_background_ai_defers_when_combined_rss_exceeds_ceiling(monkeypatch):
    monkeypatch.setattr(ra, "measure_browser_rss_bytes", lambda *a, **kw: 6 * 1024**3)
    monkeypatch.setattr(ra, "measure_ollama_rss_bytes", lambda: 4 * 1024**3)
    decision = ra.arbitrate_model_load(priority=ra.Priority.BACKGROUND_AI, ceiling_bytes=9 * 1024**3)
    assert decision.proceed is False
    assert decision.combined_bytes == 10 * 1024**3


def test_background_ai_proceeds_when_combined_rss_within_ceiling(monkeypatch):
    monkeypatch.setattr(ra, "measure_browser_rss_bytes", lambda *a, **kw: 2 * 1024**3)
    monkeypatch.setattr(ra, "measure_ollama_rss_bytes", lambda: 2 * 1024**3)
    decision = ra.arbitrate_model_load(priority=ra.Priority.BACKGROUND_AI, ceiling_bytes=9 * 1024**3)
    assert decision.proceed is True


def test_arbitrate_browser_open_defers_when_ollama_rss_too_high(monkeypatch):
    """The other half of §24's rule: checking Ollama RSS before browser work."""
    monkeypatch.setattr(ra, "measure_browser_rss_bytes", lambda *a, **kw: 1 * 1024**3)
    monkeypatch.setattr(ra, "measure_ollama_rss_bytes", lambda: 9 * 1024**3)
    decision = ra.arbitrate_browser_open(ceiling_bytes=9 * 1024**3)
    assert decision.proceed is False


def test_release_pressure_calls_gateway_unload(monkeypatch):
    called = {}
    monkeypatch.setattr(ra.gateway, "unload", lambda role: called.setdefault("role", role))
    ra.release_pressure("generation")
    assert called["role"] == "generation"
