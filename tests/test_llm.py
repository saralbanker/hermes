"""src/llm.py — facts()/facts_full(): the retired-project redaction call site every legacy
LLM prompt builder goes through, and its fail-closed behavior on a delimiter/registry drift.

No network: nothing here calls chat()/Ollama. profile/facts.md is only ever READ for the
real-file assertions; every drift/failure case runs against a tmp copy via monkeypatching
llm.FACTS_PATH, never the real file.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import llm
from project_registry import FactsRedactionError, RETIRED_PROJECTS

ROOT = Path(__file__).parent.parent
REAL_FACTS_TEXT = (ROOT / "profile" / "facts.md").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _fresh_facts_cache():
    """lru_cache must never leak a tmp-facts result into (or out of) another test."""
    llm.facts.cache_clear()
    yield
    llm.facts.cache_clear()


@pytest.fixture
def facts_file(tmp_path, monkeypatch):
    path = tmp_path / "facts.md"
    monkeypatch.setattr(llm, "FACTS_PATH", path)

    def _write(text: str) -> Path:
        llm.facts.cache_clear()
        path.write_text(text, encoding="utf-8")
        return path

    return _write


# ---------------------------------------------------------------------------
# facts_full() / facts() — redaction on the real file
# ---------------------------------------------------------------------------

def test_facts_full_is_unredacted():
    text = llm.facts_full()
    for name in RETIRED_PROJECTS:
        assert name in text


def test_facts_strips_every_retired_section_cleanly():
    text = llm.facts()
    for name in RETIRED_PROJECTS:
        assert name not in text
    # surrounding active content survives
    assert any(active in text for active in ("Neuro-Zenith", "AWIS", "Hermes"))


def test_facts_matches_engine_candidate_text_redaction():
    """src/llm.py and src/engine/ai/embed.py read profile/facts.md independently (by
    design) but must derive the SAME redacted content from the one shared registry."""
    from engine.ai.embed import candidate_text
    assert llm.facts() == candidate_text()


# ---------------------------------------------------------------------------
# Fail-closed on a delimiter/registry drift
# ---------------------------------------------------------------------------

def test_facts_raises_on_delimiter_name_drift(facts_file):
    facts_file(REAL_FACTS_TEXT.replace("<!-- RETIRED:HeatMax -->", "<!-- RETIRED:HeatMaxTypo -->"))
    with pytest.raises(FactsRedactionError):
        llm.facts()


def test_facts_raises_when_no_retired_delimiters_exist_at_all(facts_file):
    facts_file("## Contact\n- Name: X\n\nNo retired sections delimited here at all.")
    with pytest.raises(FactsRedactionError):
        llm.facts()


def test_facts_raises_on_an_extra_unrecognized_delimiter(facts_file):
    facts_file(REAL_FACTS_TEXT + "\n<!-- RETIRED:SomethingElse -->\nx\n<!-- /RETIRED -->\n")
    with pytest.raises(FactsRedactionError):
        llm.facts()


def test_lru_cache_never_caches_a_redaction_failure(tmp_path, monkeypatch):
    path = tmp_path / "facts.md"
    path.write_text("broken, no delimiters", encoding="utf-8")
    monkeypatch.setattr(llm, "FACTS_PATH", path)
    with pytest.raises(FactsRedactionError):
        llm.facts()
    path.write_text(REAL_FACTS_TEXT, encoding="utf-8")  # fixed WITHOUT an explicit cache_clear
    assert "Shade Ledger" not in llm.facts()
    assert llm.facts.cache_info().currsize == 1


# ---------------------------------------------------------------------------
# Propagation through tailor.py:process_job — per-job failure, not a batch crash
# ---------------------------------------------------------------------------

def _seed_scored_job(temp_db, job: dict) -> None:
    temp_db.upsert_job({**job, "location": "Remote", "job_board": "other", "salary_min": None,
                       "salary_max": None, "date_posted": None, "status": "scored"})


def _job_row(temp_db, url: str) -> dict:
    conn = temp_db.get_conn()
    row = dict(conn.execute("SELECT status, status_reason FROM jobs WHERE url=?", (url,)).fetchone())
    conn.close()
    return row


def test_facts_redaction_error_fails_one_job_without_crashing_the_batch(temp_db, tmp_path, monkeypatch):
    """A FactsRedactionError inside process_job (via facts()) is caught by process_job's own
    per-job try/except, persisted as jobs.status='failed' with a 'tailor_error: ...' reason —
    never an unhandled crash — and a second, unaffected job processed afterward in the same
    batch still completes normally with status='tailored'."""
    import tailor

    monkeypatch.setattr(tailor, "ROOT", tmp_path)  # never write real output/tailored/ files

    calls = {"n": 0}

    def flaky_facts():
        calls["n"] += 1
        if calls["n"] == 1:
            raise FactsRedactionError("facts.md RETIRED delimiters drifted from project_registry")
        return "Python backend engineer with API and cloud experience."

    monkeypatch.setattr(tailor, "facts", flaky_facts)
    monkeypatch.setattr(
        tailor, "generate_cover_letter",
        lambda job, kws, variant: (f"Dear {job['company']},\n\nFine letter.\n\n{tailor.CLOSING}", "template"),
    )

    job_a = {"id": 1, "url": "https://x/facts-fail-a", "title": "Backend Engineer",
             "company": "Acme", "description": "python api"}
    job_b = {"id": 2, "url": "https://x/facts-fail-b", "title": "Backend Engineer",
             "company": "Globex", "description": "python api"}
    _seed_scored_job(temp_db, job_a)
    _seed_scored_job(temp_db, job_b)

    result_a = tailor.process_job(job_a, dry_run=False)
    assert result_a["status"] == "error"
    assert "facts.md" in result_a["error"] or "FactsRedactionError" in result_a["error"]
    row_a = _job_row(temp_db, job_a["url"])
    assert row_a["status"] == "failed"
    assert row_a["status_reason"] and row_a["status_reason"].startswith("tailor_error:")

    # The batch is not aborted: a second, independent process_job call still succeeds.
    result_b = tailor.process_job(job_b, dry_run=False)
    assert result_b["status"] == "tailored"
    row_b = _job_row(temp_db, job_b["url"])
    assert row_b["status"] == "tailored"
    assert calls["n"] == 2
