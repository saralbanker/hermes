"""Phase 4: src/engine/ai/classify.py — scoring/classification parsing and
validation (AI_SYSTEM.md §23/§59), fully mocked at the gateway boundary."""
from __future__ import annotations

import pytest

from engine.ai import classify, gateway


def _mock_chat(monkeypatch, content: str):
    monkeypatch.setattr(
        gateway, "chat",
        lambda role, prompt, **kw: gateway.CallResult(content=content, latency_seconds=0.5),
    )


def test_score_job_parses_valid_json(monkeypatch):
    _mock_chat(monkeypatch, '{"score": 8, "confidence": 0.9, "reason": "strong stack match", '
                            '"risk_flags": ["no_published_salary"]}')
    result = classify.score_job("Backend Engineer", "python api fastapi")
    assert result.score == 8.0
    assert result.confidence == 0.9
    assert result.reason == "strong stack match"
    assert result.risk_flags == ["no_published_salary"]
    assert result.prompt_version == classify.PROMPT_SCHEMA_VERSION


def test_score_job_parses_json_wrapped_in_code_fence(monkeypatch):
    _mock_chat(monkeypatch, '```json\n{"score": 6, "confidence": 0.5, "reason": "ok"}\n```')
    result = classify.score_job("Engineer", "desc")
    assert result.score == 6.0


def test_score_job_rejects_malformed_json():
    with pytest.raises(ValueError):
        classify._parse("not json at all")


def test_score_job_rejects_missing_score_field():
    with pytest.raises(ValueError):
        classify._parse('{"confidence": 0.5}')


def test_score_job_rejects_out_of_range_score(monkeypatch):
    _mock_chat(monkeypatch, '{"score": 15, "confidence": 0.5, "reason": "x"}')
    with pytest.raises(ValueError):
        classify.score_job("Engineer", "desc")


def test_score_job_clamps_confidence_to_0_1(monkeypatch):
    _mock_chat(monkeypatch, '{"score": 7, "confidence": 1.5, "reason": "x"}')
    result = classify.score_job("Engineer", "desc")
    assert result.confidence == 1.0


def test_score_job_defaults_missing_risk_flags_to_empty_list(monkeypatch):
    _mock_chat(monkeypatch, '{"score": 7, "confidence": 0.5, "reason": "x"}')
    result = classify.score_job("Engineer", "desc")
    assert result.risk_flags == []


def test_score_job_propagates_ai_unavailable(monkeypatch):
    def boom(*a, **kw):
        raise gateway.AIUnavailable("ollama down")
    monkeypatch.setattr(gateway, "chat", boom)
    with pytest.raises(gateway.AIUnavailable):
        classify.score_job("Engineer", "desc")
