"""scripts/remediate_retired_project_letters.py — smoke test of the remediation logic
(scan/apply_remediation) against a throwaway SQLite fixture.

Deliberately does NOT call main()/backup_db(): those touch real paths by design (ROOT /
"output" for the DB backup, db.DB_PATH for the live DB) — this is a one-time production
script never meant to run in CI. Instead this test exercises scan()/apply_remediation()
directly against temp_db's isolated connection (never db/applications.db), proving the
exact safety property the plan requires: submission_unconfirmed rows are reported but
NEVER touched even when they contain retired-project text, and submitted rows are reported
but never modified either. Loaded via importlib, same convention as
tests/test_engine_worker_lock.py / tests/test_release_manual_review_script.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "remediate_retired_project_letters", ROOT / "scripts" / "remediate_retired_project_letters.py"
)
remediate = importlib.util.module_from_spec(_spec)
sys.modules["remediate_retired_project_letters"] = remediate
_spec.loader.exec_module(remediate)


def _seed(temp_db, tmp_path, url, *, status, letter_text, company="Acme", title="Backend Engineer"):
    cover_path = tmp_path / f"{abs(hash(url))}-cover.txt"
    cover_path.write_text(letter_text)
    j = {"url": url, "company": company, "title": title, "description": "python api",
         "job_board": "other", "location": "Remote", "salary_min": None, "salary_max": None,
         "date_posted": None, "status": status}
    temp_db.upsert_job(j)
    temp_db.update_job(url, {"cover_letter_path": str(cover_path)})
    return str(cover_path)


RETIRED_LETTER = "Dear Acme,\n\nI previously built Shade Ledger, a billing system."
CLEAN_LETTER = "Dear Acme,\n\nI previously built Neuro-Zenith, an AI platform."


def test_scan_separates_mutable_from_report_only_by_status(temp_db, tmp_path):
    _seed(temp_db, tmp_path, "https://x/tailored-retired", status="tailored", letter_text=RETIRED_LETTER)
    _seed(temp_db, tmp_path, "https://x/scored-retired", status="scored", letter_text=RETIRED_LETTER)
    _seed(temp_db, tmp_path, "https://x/unconfirmed-retired", status="submission_unconfirmed",
          letter_text=RETIRED_LETTER)
    _seed(temp_db, tmp_path, "https://x/submitted-retired", status="submitted", letter_text=RETIRED_LETTER)
    _seed(temp_db, tmp_path, "https://x/clean", status="tailored", letter_text=CLEAN_LETTER)
    _seed(temp_db, tmp_path, "https://x/manual-review-retired", status="manual_review",
          letter_text=RETIRED_LETTER)  # neither mutable nor report-only — left out entirely

    conn = temp_db.get_conn()
    result = remediate.scan(conn)
    conn.close()

    mutable_urls = {e["url"] for e in result["mutable"]}
    report_only_urls = {e["url"] for e in result["report_only"]}

    assert mutable_urls == {"https://x/tailored-retired", "https://x/scored-retired"}
    assert report_only_urls == {"https://x/unconfirmed-retired", "https://x/submitted-retired"}
    # The clean letter never appears in either bucket; manual_review is excluded entirely.
    assert "https://x/clean" not in mutable_urls | report_only_urls
    assert "https://x/manual-review-retired" not in mutable_urls | report_only_urls
    assert all(e["retired"] == ["Shade Ledger"] for e in result["mutable"] + result["report_only"])


def test_apply_remediation_only_touches_the_mutable_set(temp_db, tmp_path):
    """explicit safety assertion: a submission_unconfirmed row with retired-project text in
    its cover letter is never modified by apply_remediation, even though scan() found it;
    a submitted row is likewise reported only, never modified."""
    _seed(temp_db, tmp_path, "https://x/tailored-retired", status="tailored", letter_text=RETIRED_LETTER)
    _seed(temp_db, tmp_path, "https://x/unconfirmed-retired", status="submission_unconfirmed",
          letter_text=RETIRED_LETTER)
    _seed(temp_db, tmp_path, "https://x/submitted-retired", status="submitted", letter_text=RETIRED_LETTER)

    conn = temp_db.get_conn()
    result = remediate.scan(conn)
    remediate.apply_remediation(conn, result["mutable"])

    def _row(url):
        return dict(conn.execute(
            "SELECT status, cover_letter_path FROM jobs WHERE url=?", (url,)
        ).fetchone())

    mutated = _row("https://x/tailored-retired")
    assert mutated["status"] == "scored"
    assert mutated["cover_letter_path"] is None

    unconfirmed = _row("https://x/unconfirmed-retired")
    assert unconfirmed["status"] == "submission_unconfirmed"       # untouched
    assert unconfirmed["cover_letter_path"] is not None            # cover letter left in place

    submitted = _row("https://x/submitted-retired")
    assert submitted["status"] == "submitted"                      # untouched, immutable
    assert submitted["cover_letter_path"] is not None

    conn.close()


def test_scan_ignores_rows_with_no_cover_letter_or_no_retired_mention(temp_db, tmp_path):
    _seed(temp_db, tmp_path, "https://x/clean-tailored", status="tailored", letter_text=CLEAN_LETTER)
    url_no_letter = "https://x/no-letter"
    temp_db.upsert_job({"url": url_no_letter, "company": "Acme", "title": "X", "description": "",
                       "job_board": "other", "location": "Remote", "salary_min": None,
                       "salary_max": None, "date_posted": None, "status": "scored"})

    conn = temp_db.get_conn()
    result = remediate.scan(conn)
    conn.close()

    all_urls = {e["url"] for e in result["mutable"] + result["report_only"]}
    assert all_urls == set()
