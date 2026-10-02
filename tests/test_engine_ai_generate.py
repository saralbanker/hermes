"""Phase 4: src/engine/ai/generate.py — generation role, reusing tailor.py's
honesty/validation machinery. Fully mocked at the gateway boundary."""
from __future__ import annotations

from engine.ai import gateway, generate


JOB = {"company": "Acme", "title": "Backend Engineer", "description": "python api"}


def _mock_chat(monkeypatch, responses: list[str]):
    calls = iter(responses)

    def fake_chat(role, prompt, **kw):
        return gateway.CallResult(content=next(calls), latency_seconds=0.3)

    monkeypatch.setattr(gateway, "chat", fake_chat)


def test_select_resume_variant_delegates_to_tailor():
    import tailor as _tailor
    assert generate.select_resume_variant("AI Engineer", "rag llm") == \
        _tailor.select_resume_variant("AI Engineer", "rag llm")


def test_generate_cover_letter_accepts_valid_llm_output(monkeypatch):
    _mock_chat(monkeypatch, [
        "I'm drawn to Acme's backend work because it matches my own project experience. "
        "I built AWIS, an event-sourced workflow engine in Go with 773 test functions."
    ])
    result = generate.generate_cover_letter(JOB, ["python", "api"], "backend")
    assert result.source == "llm"
    assert result.attempts == 1
    assert "AWIS" in result.letter
    import tailor as _tailor
    assert result.letter.endswith(_tailor.CLOSING)
    assert not _tailor.validate_letter(result.letter)


def test_generate_cover_letter_retries_once_on_validation_failure(monkeypatch):
    _mock_chat(monkeypatch, [
        "I have 10 years of enterprise-grade Java experience with AWS and Kubernetes at scale.",  # rejected
        "I'm drawn to Acme's backend work. I built AWIS, an event-sourced workflow engine in Go "
        "with 773 test functions.",
    ])
    result = generate.generate_cover_letter(JOB, ["python"], "backend")
    assert result.source == "llm"
    assert result.attempts == 2


def test_generate_cover_letter_falls_back_to_template_after_two_failures(monkeypatch):
    _mock_chat(monkeypatch, [
        "I have 10 years of enterprise-grade Java experience with AWS at scale.",
        "Another bad draft claiming 99% success rate and Kubernetes expertise at scale.",
    ])
    result = generate.generate_cover_letter(JOB, ["python"], "backend")
    assert result.source == "template"
    import tailor as _tailor
    assert result.letter == _tailor.template_letter(JOB, "backend")


def test_generate_cover_letter_falls_back_to_template_when_ai_unavailable(monkeypatch):
    def boom(*a, **kw):
        raise gateway.AIUnavailable("ollama down")
    monkeypatch.setattr(gateway, "chat", boom)
    result = generate.generate_cover_letter(JOB, ["python"], "fullstack")
    assert result.source == "template"


def test_generate_cover_letter_never_exceeds_two_model_calls(monkeypatch):
    call_count = {"n": 0}

    def fake_chat(role, prompt, **kw):
        call_count["n"] += 1
        return gateway.CallResult(content="bad draft with 99% success rate at scale", latency_seconds=0.1)

    monkeypatch.setattr(gateway, "chat", fake_chat)
    generate.generate_cover_letter(JOB, ["python"], "backend")
    assert call_count["n"] == 2  # §41 Generation Retry: ONE bounded retry, never a third call
