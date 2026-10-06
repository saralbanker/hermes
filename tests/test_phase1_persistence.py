import sqlite3
import pytest
from pathlib import Path
import sys

# Ensure src is on sys.path
SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import states as S
import db
import apply


@pytest.fixture
def temp_phase_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_applications.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db


def _insert_job(db_mod, url="https://indeed.com/job/1", status="tailored", attempts=0, phase=None):
    conn = db_mod.get_conn()
    conn.execute(
        """
        INSERT INTO jobs (url, company, title, location, job_board, status, attempts, phase)
        VALUES (?, 'Test Co', 'Software Engineer', 'Remote', 'indeed', ?, ?, ?)
        """,
        (url, status, attempts, phase),
    )
    conn.commit()
    conn.close()


def _get_job(db_mod, url):
    conn = db_mod.get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    conn.close()
    return dict(row) if row else None


def test_claim_job_initializes_phase_pre_submit(temp_phase_db):
    url = "https://indeed.com/job/claim_test"
    _insert_job(temp_phase_db, url=url, status=S.TAILORED, attempts=0)

    claimed = temp_phase_db.claim_job(url)
    assert claimed is True

    job = _get_job(temp_phase_db, url)
    assert job["status"] == S.APPLYING
    assert job["phase"] == S.PHASE_PRE_SUBMIT
    assert job["attempts"] == 1


def test_conditional_phase_update_success(temp_phase_db):
    url = "https://indeed.com/job/cond_test"
    _insert_job(temp_phase_db, url=url, status=S.TAILORED, attempts=0)
    assert temp_phase_db.claim_job(url) is True

    # Job is now applying with attempts=1 and phase=PRE_SUBMIT
    updated = temp_phase_db.update_job_phase(url, S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, attempt=1)
    assert updated is True

    job = _get_job(temp_phase_db, url)
    assert job["phase"] == S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED
    assert temp_phase_db.get_job_phase(url) == S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED


def test_conditional_phase_update_fails_on_attempt_mismatch(temp_phase_db):
    url = "https://indeed.com/job/cond_mismatch"
    _insert_job(temp_phase_db, url=url, status=S.TAILORED, attempts=0)
    assert temp_phase_db.claim_job(url) is True

    # Attempt count in DB is 1, passing attempt=2 must fail
    updated = temp_phase_db.update_job_phase(url, S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, attempt=2)
    assert updated is False

    job = _get_job(temp_phase_db, url)
    assert job["phase"] == S.PHASE_PRE_SUBMIT


def test_conditional_phase_update_fails_when_not_applying(temp_phase_db):
    url = "https://indeed.com/job/not_applying"
    _insert_job(temp_phase_db, url=url, status=S.TAILORED, attempts=1, phase=S.PHASE_PRE_SUBMIT)

    # Job status is tailored, not applying
    updated = temp_phase_db.update_job_phase(url, S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, attempt=1)
    assert updated is False

    job = _get_job(temp_phase_db, url)
    assert job["phase"] == S.PHASE_PRE_SUBMIT


def test_migration_adds_phase_column_to_existing_db(tmp_path, monkeypatch):
    old_db_file = tmp_path / "old_applications.db"
    monkeypatch.setattr(db, "DB_PATH", old_db_file)

    # Simulate an old DB created from schema.sql without the phase column
    conn = sqlite3.connect(old_db_file)
    schema_sql = db.SCHEMA_PATH.read_text().replace("phase                   TEXT,\n", "")
    conn.executescript(schema_sql)
    for col, col_type in db.MIGRATION_COLUMNS.items():
        if col != "phase":
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
    conn.execute(
        "INSERT INTO jobs (url, company, title, status, attempts) VALUES ('https://x/old', 'C', 'T', 'tailored', 0)"
    )
    conn.commit()
    conn.close()

    # Run init_db to migrate
    db.init_db()

    conn = sqlite3.connect(old_db_file)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    assert "phase" in cols
    row = conn.execute("SELECT url, phase FROM jobs WHERE url = 'https://x/old'").fetchone()
    assert row[0] == "https://x/old"
    assert row[1] is None
    conn.close()


def test_migration_fails_closed_existing_stale_applying_rows_without_phase(tmp_path, monkeypatch):
    old_db_file = tmp_path / "stale_applications.db"
    monkeypatch.setattr(db, "DB_PATH", old_db_file)

    # Simulate an old DB with a stale applying row
    conn = sqlite3.connect(old_db_file)
    schema_sql = db.SCHEMA_PATH.read_text().replace("phase                   TEXT,\n", "")
    conn.executescript(schema_sql)
    for col, col_type in db.MIGRATION_COLUMNS.items():
        if col != "phase":
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
    conn.execute(
        "INSERT INTO jobs (url, company, title, status, attempts) VALUES ('https://x/stale', 'C', 'T', 'applying', 1)"
    )
    conn.commit()
    conn.close()

    # Run init_db to migrate
    db.init_db()

    conn = sqlite3.connect(old_db_file)
    row = conn.execute("SELECT status, status_reason FROM jobs WHERE url = 'https://x/stale'").fetchone()
    conn.close()
    assert row[0] == S.SUBMISSION_UNCONFIRMED
    assert "unresolved applying row without phase" in row[1]


def test_recovery_unknown_or_missing_phase_fails_closed(temp_phase_db):
    url_null = "https://indeed.com/job/null_phase"
    url_unknown = "https://indeed.com/job/unknown_phase"
    _insert_job(temp_phase_db, url=url_null, status=S.APPLYING, attempts=1, phase=None)
    _insert_job(temp_phase_db, url=url_unknown, status=S.APPLYING, attempts=1, phase="CORRUPTED_PHASE")

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0

    job_null = _get_job(temp_phase_db, url_null)
    assert job_null["status"] == S.SUBMISSION_UNCONFIRMED
    assert job_null["attempts"] == 1

    job_unk = _get_job(temp_phase_db, url_unknown)
    assert job_unk["status"] == S.SUBMISSION_UNCONFIRMED
    assert job_unk["attempts"] == 1


def test_recovery_submit_risk_phases_never_requeue(temp_phase_db):
    url_dispatched = "https://indeed.com/job/dispatched"
    url_pending = "https://indeed.com/job/pending"
    _insert_job(temp_phase_db, url=url_dispatched, status=S.APPLYING, attempts=1, phase=S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED)
    _insert_job(temp_phase_db, url=url_pending, status=S.APPLYING, attempts=1, phase=S.PHASE_CONFIRMATION_PENDING)

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0

    job_d = _get_job(temp_phase_db, url_dispatched)
    assert job_d["status"] == S.SUBMISSION_UNCONFIRMED
    assert job_d["attempts"] == 1

    job_p = _get_job(temp_phase_db, url_pending)
    assert job_p["status"] == S.SUBMISSION_UNCONFIRMED
    assert job_p["attempts"] == 1


def test_recovery_pre_submit_requeues_if_under_cap(temp_phase_db):
    url = "https://indeed.com/job/pre_submit_requeue"
    _insert_job(temp_phase_db, url=url, status=S.APPLYING, attempts=1, phase=S.PHASE_PRE_SUBMIT)

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 1

    job = _get_job(temp_phase_db, url)
    assert job["status"] == S.TAILORED
    assert job["attempts"] == 1


def test_recovery_pre_submit_fails_if_cap_reached(temp_phase_db):
    url = "https://indeed.com/job/pre_submit_fail"
    _insert_job(temp_phase_db, url=url, status=S.APPLYING, attempts=S.MAX_ATTEMPTS, phase=S.PHASE_PRE_SUBMIT)

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0

    job = _get_job(temp_phase_db, url)
    assert job["status"] == S.FAILED
    assert "exceeded MAX_ATTEMPTS" in job["status_reason"]


def test_recovery_confirmed_phase_mismatch_fails_closed(temp_phase_db):
    url = "https://indeed.com/job/confirmed_mismatch"
    _insert_job(temp_phase_db, url=url, status=S.APPLYING, attempts=1, phase=S.PHASE_CONFIRMED)

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0

    job = _get_job(temp_phase_db, url)
    assert job["status"] == S.SUBMISSION_UNCONFIRMED
    assert "invariant violation" in job["status_reason"]


def test_record_result_persists_confirmed_phase(temp_phase_db):
    url = "https://indeed.com/job/record_submitted"
    _insert_job(temp_phase_db, url=url, status=S.APPLYING, attempts=1, phase=S.PHASE_CONFIRMATION_PENDING)

    res = S.ApplyResult(S.SUBMITTED, evidence="application submitted @ https://indeed.com/confirm")
    apply.record_result({"url": url}, res)

    job = _get_job(temp_phase_db, url)
    assert job["status"] == S.SUBMITTED
    assert job["phase"] == S.PHASE_CONFIRMED
