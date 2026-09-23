"""
tests/test_response_watcher.py — offline, no network. Covers classification,
persistent dedupe (notify called once), and company matching for
src/response_watcher.py.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db  # noqa: E402
import response_watcher as rw  # noqa: E402


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            company TEXT,
            title TEXT,
            status TEXT,
            applied_at TEXT,
            response_status TEXT,
            response_subject TEXT,
            response_at TEXT,
            response_notified_at TEXT
        )
        """
    )
    return conn


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_interview_invitation_is_positive():
    subject = "Interview Invitation - Backend Engineer at Acme Corp"
    body = "We would like to schedule a call with you for an interview next week. Please let us know your availability."
    assert rw.classify(subject, body, "recruiter@acmecorp.com") == "positive"


def test_hackerrank_assessment_invite_is_positive():
    subject = "HackerRank Assessment Invitation for Software Engineer"
    body = "Please complete the following coding assessment via HackerRank within 5 days."
    assert rw.classify(subject, body, "noreply@hackerrank.com") == "positive"


def test_generic_automated_ack_is_not_positive():
    subject = "Thank you for applying to Acme Corp"
    body = (
        "Thank you for applying! If your profile matches our requirements, "
        "our team will reach out for an interview."
    )
    assert rw.classify(subject, body, "careers@acmecorp.com") == "ack"


def test_rejection_is_classified_correctly():
    subject = "Update on your application"
    body = (
        "Thank you for your interest in the role. Unfortunately, we have decided "
        "to move forward with other candidates at this time."
    )
    assert rw.classify(subject, body, "careers@acmecorp.com") == "rejection"


def test_indeed_job_alert_is_other():
    subject = "5 new jobs for you: Software Engineer"
    body = "New jobs matching your search on Indeed. Job alert delivered daily."
    assert rw.classify(subject, body, "jobalerts-noreply@indeed.com") == "other"


# ---------------------------------------------------------------------------
# Company matching
# ---------------------------------------------------------------------------

def test_company_matching_by_domain_and_subject():
    jobs = [
        {"url": "u1", "company": "Widget Systems Pvt Ltd", "title": "SWE"},
        {"url": "u2", "company": "Acme Corp", "title": "Backend Engineer"},
    ]

    matched_by_domain = rw.match_company(
        "hr@widgetsystems.com", "Regarding your application", "We reviewed your resume.", jobs
    )
    assert matched_by_domain is not None and matched_by_domain["url"] == "u1"

    matched_by_subject = rw.match_company(
        "noreply@somewhereelse.com", "Update on your Acme Corp application", "body text", jobs
    )
    assert matched_by_subject is not None and matched_by_subject["url"] == "u2"

    no_match = rw.match_company("random@unrelated.com", "subject", "body", jobs)
    assert no_match is None


# ---------------------------------------------------------------------------
# Dedupe + notify-once
# ---------------------------------------------------------------------------

def test_dedupe_processes_and_notifies_once():
    conn = make_conn()
    conn.execute(
        "INSERT INTO jobs(url, company, title, status) VALUES (?, ?, ?, ?)",
        ("https://boards.example/1", "Acme Corp", "Backend Engineer", "submitted"),
    )
    conn.commit()
    jobs = [dict(r) for r in conn.execute("SELECT url, company, title FROM jobs")]

    calls = []

    def fake_notify(title, body, urgent=False):
        calls.append((title, body, urgent))
        return True

    subject = "Interview Invitation - Backend Engineer at Acme Corp"
    body = "We would like to schedule a call with you for an interview next week."
    msg_id = "<abc123@acmecorp.com>"

    first = rw.process_message(
        conn, msg_id, "recruiter@acmecorp.com", subject, body,
        "2026-09-20T10:00:00", jobs, notify_fn=fake_notify,
    )
    second = rw.process_message(
        conn, msg_id, "recruiter@acmecorp.com", subject, body,
        "2026-09-20T10:00:00", jobs, notify_fn=fake_notify,
    )

    assert first == "positive"
    assert second is None  # already-processed message_id — no reprocessing, no re-notify
    assert len(calls) == 1
    assert calls[0][2] is True  # urgent

    row = conn.execute(
        "SELECT response_status, response_subject FROM jobs WHERE url = ?",
        ("https://boards.example/1",),
    ).fetchone()
    assert row["response_status"] == "positive"
    assert row["response_subject"] == subject

    notified_row = conn.execute(
        "SELECT notified_at FROM responses WHERE message_id = ?", (msg_id,)
    ).fetchone()
    assert notified_row["notified_at"] is not None


def test_positive_response_is_never_downgraded():
    conn = make_conn()
    conn.execute(
        "INSERT INTO jobs(url, company, title, status) VALUES (?, ?, ?, ?)",
        ("https://boards.example/2", "Acme Corp", "Backend Engineer", "submitted"),
    )
    conn.commit()
    jobs = [dict(r) for r in conn.execute("SELECT url, company, title FROM jobs")]

    def fake_notify(title, body, urgent=False):
        return True

    rw.process_message(
        conn, "<positive@acmecorp.com>", "recruiter@acmecorp.com",
        "Interview Invitation at Acme Corp",
        "We would like to schedule a call with you for an interview.",
        "2026-09-20T10:00:00", jobs, notify_fn=fake_notify,
    )
    # A later, unrelated ack-style message for the same company must not downgrade it.
    rw.process_message(
        conn, "<ack@acmecorp.com>", "careers@acmecorp.com",
        "Thank you for applying to Acme Corp",
        "Thank you for applying! If your profile matches we will reach out.",
        "2026-09-21T10:00:00", jobs, notify_fn=fake_notify,
    )

    row = conn.execute(
        "SELECT response_status FROM jobs WHERE url = ?", ("https://boards.example/2",)
    ).fetchone()
    assert row["response_status"] == "positive"


# ---------------------------------------------------------------------------
# Light integration: responses table self-creation against a real (temp) db
# ---------------------------------------------------------------------------

def test_ensure_responses_table_creates_table(tmp_path, monkeypatch):
    db_path = tmp_path / "test_applications.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    conn = db.get_conn()
    try:
        rw.ensure_responses_table(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "responses" in tables
    finally:
        conn.close()
