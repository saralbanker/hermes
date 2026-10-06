"""scripts/release_manual_review.py — the legacy manual-release path (§5.1).

Loaded via importlib (same convention as tests/test_engine_worker_lock.py for
scripts/hermes_engine_worker.py) rather than imported as a package, since scripts/ has no
__init__.py. Every test monkeypatches both db.DB_PATH (via the temp_db fixture) and the
script's own RELEASE_LOG constant to a tmp_path file — never the real
output/manual_review_releases.jsonl, and never db/applications.db.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "release_manual_review", ROOT / "scripts" / "release_manual_review.py"
)
release_manual_review = importlib.util.module_from_spec(_spec)
sys.modules["release_manual_review"] = release_manual_review
_spec.loader.exec_module(release_manual_review)


def _seed_row(temp_db, url, *, validation_attempts, attempts, status):
    j = {"url": url, "company": "Acme", "title": "Backend Engineer", "description": "python api",
         "job_board": "other", "location": "Remote", "salary_min": None, "salary_max": None,
         "date_posted": None, "status": status}
    temp_db.upsert_job(j)
    temp_db.update_job(url, {
        "validation_attempts": validation_attempts, "attempts": attempts,
        "cover_letter_path": "output/tailored/some-cover.txt",
        "status_reason": "finding: cover letter is empty, missing, or whitespace-only",
    })


def _row(temp_db, url):
    conn = temp_db.get_conn()
    row = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone())
    conn.close()
    return row


def test_release_grants_a_fresh_budget_to_an_exhausted_row(temp_db, tmp_path, monkeypatch):
    """A row at MAX_VALIDATION_ATTEMPTS (status='manual_review') becomes eligible again with
    a genuinely fresh budget: attempts=0, validation_attempts=0, status back to 'scored'
    (forcing tailor.py to regenerate the cover letter), cover_letter_path cleared."""
    log_path = tmp_path / "releases.jsonl"
    monkeypatch.setattr(release_manual_review, "RELEASE_LOG", log_path)
    url = "https://x/exhausted"
    _seed_row(temp_db, url, validation_attempts=3, attempts=2, status="manual_review")

    entry = release_manual_review.release(url, note="reviewed, looks fine now")

    row = _row(temp_db, url)
    assert row["status"] == "scored"
    assert row["attempts"] == 0
    assert row["validation_attempts"] == 0
    assert row["cover_letter_path"] is None
    assert row["status_reason"] == "manual_release: see output/manual_review_releases.jsonl (operational log)"

    assert entry["url"] == url
    assert entry["validation_attempts_at_release"] == 3
    assert entry["note"] == "reviewed, looks fine now"
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    logged = json.loads(log_lines[0])
    assert logged["url"] == url and logged["company"] == "Acme"


def test_release_refuses_a_row_not_in_manual_review(temp_db, tmp_path, monkeypatch):
    log_path = tmp_path / "releases.jsonl"
    monkeypatch.setattr(release_manual_review, "RELEASE_LOG", log_path)
    url = "https://x/still-tailored"
    _seed_row(temp_db, url, validation_attempts=1, attempts=1, status="tailored")

    with pytest.raises(release_manual_review.ReleaseError, match="not 'manual_review'"):
        release_manual_review.release(url)

    row = _row(temp_db, url)
    assert row["status"] == "tailored"            # untouched
    assert row["validation_attempts"] == 1         # untouched
    assert not log_path.exists()


def test_release_refuses_a_nonexistent_url(temp_db, tmp_path, monkeypatch):
    log_path = tmp_path / "releases.jsonl"
    monkeypatch.setattr(release_manual_review, "RELEASE_LOG", log_path)
    with pytest.raises(release_manual_review.ReleaseError, match="no job row"):
        release_manual_review.release("https://x/does-not-exist")
    assert not log_path.exists()


def test_list_manual_review_reports_only_manual_review_rows(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(release_manual_review, "RELEASE_LOG", tmp_path / "releases.jsonl")
    _seed_row(temp_db, "https://x/mr1", validation_attempts=3, attempts=1, status="manual_review")
    _seed_row(temp_db, "https://x/not-mr", validation_attempts=1, attempts=1, status="tailored")

    rows = release_manual_review.list_manual_review()
    urls = {r["url"] for r in rows}
    assert urls == {"https://x/mr1"}
