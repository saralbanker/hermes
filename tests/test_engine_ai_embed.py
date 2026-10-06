"""src/engine/ai/embed.py:candidate_text() — the engine's own independent read of
profile/facts.md (deliberately isolated from src/llm.py per the Phase 4 brief), and its
fail-closed redaction behavior. Mirrors tests/test_llm.py's coverage of llm.py:facts(), but
verified independently since embed.py does its own file I/O rather than importing llm.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.ai import embed
from project_registry import FactsRedactionError, RETIRED_PROJECTS

ROOT = Path(__file__).parent.parent
REAL_FACTS_TEXT = (ROOT / "profile" / "facts.md").read_text(encoding="utf-8")


@pytest.fixture
def facts_file(tmp_path, monkeypatch):
    path = tmp_path / "facts.md"
    monkeypatch.setattr(embed, "FACTS_PATH", path)

    def _write(text: str) -> Path:
        path.write_text(text, encoding="utf-8")
        return path

    return _write


def test_candidate_text_strips_every_retired_section_cleanly():
    text = embed.candidate_text()
    for name in RETIRED_PROJECTS:
        assert name not in text
    assert any(active in text for active in ("Neuro-Zenith", "AWIS", "Hermes"))


def test_candidate_text_matches_llm_facts_redaction():
    """Same registry, same redaction result, read via two independent file I/O paths."""
    import llm
    llm.facts.cache_clear()
    assert embed.candidate_text() == llm.facts()


def test_candidate_text_raises_on_delimiter_drift(facts_file):
    facts_file(REAL_FACTS_TEXT.replace("<!-- RETIRED:HeatMax -->", "<!-- RETIRED:HeatMaxTypo -->"))
    with pytest.raises(FactsRedactionError):
        embed.candidate_text()


def test_candidate_text_raises_when_no_delimiters_exist(facts_file):
    facts_file("No retired sections delimited at all in this fact sheet.")
    with pytest.raises(FactsRedactionError):
        embed.candidate_text()


def test_candidate_text_is_not_cached_so_a_fix_takes_effect_immediately(facts_file):
    """Unlike llm.py's facts(), candidate_text() has no lru_cache — a fix must take effect
    on the very next call with no cache_clear step needed."""
    facts_file("broken")
    with pytest.raises(FactsRedactionError):
        embed.candidate_text()
    facts_file(REAL_FACTS_TEXT)
    assert "Shade Ledger" not in embed.candidate_text()


# ---------------------------------------------------------------------------
# Propagation through engine_apply.py's _tailor -> release_on_ai_failure bridge
# ---------------------------------------------------------------------------

def test_facts_redaction_error_in_generation_releases_via_ai_failure_bridge(
    make_opportunity, seed_channel, engine_conn, monkeypatch
):
    """A FactsRedactionError raised while building the generation prompt (candidate_text(),
    via generate._llm_body) is not caught inside generate.generate_cover_letter's own
    narrow (AIUnavailable/AITimeout) retry loop, so it propagates out to
    engine_apply.py:_tailor's try/except, which reuses the existing AI-failure bridge
    (release_on_ai_failure -> record_tailoring_failure): execution_phase stays NOT_STARTED,
    uncounted toward MAX_ATTEMPTS, exactly like any other AI-provider outage."""
    import engine_apply
    from engine import claim, db as enginedb
    from engine.ai import generate as generate_mod

    seed_channel("indeed")
    opp_id = make_opportunity("canon::facts-drift")
    now = enginedb.now_iso()
    claimed = claim.claim_next(engine_conn, "w1", 900, now, channel_filter="indeed")
    assert claimed is not None

    def boom():
        raise FactsRedactionError("facts.md RETIRED delimiters drifted from project_registry")

    # generate.py imported candidate_text by name (`from .embed import candidate_text`), so
    # the patch must target generate's own bound name, not embed's module attribute.
    monkeypatch.setattr(generate_mod, "candidate_text", boom)
    job = {"title": "Backend Engineer", "description": "python api", "company": "Acme"}

    cover_letter, tailor_failure = engine_apply._tailor(engine_conn, claimed, job, now)

    assert cover_letter is None
    assert tailor_failure is not None
    assert tailor_failure.new_application_state == "READY"
    from engine.retry import countable_attempt_count
    assert countable_attempt_count(engine_conn, opp_id) == 0
    attempt = enginedb.fetch_attempt(engine_conn, claimed.attempt_id)
    assert attempt["execution_phase"] == "NOT_STARTED"
    assert attempt["error_class"] == "ai_failure:unexpected_exception"
