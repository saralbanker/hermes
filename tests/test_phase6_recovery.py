import pytest
from pathlib import Path
import sys

# Ensure src is on sys.path
SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import db
import apply
import states as S


@pytest.fixture
def temp_rec_db(tmp_path, monkeypatch):
    db_file = tmp_path / "rec_test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db


def _insert_job(db_mod, url, status=S.APPLYING, attempts=1, phase=None, last_attempt_at=None):
    conn = db_mod.get_conn()
    conn.execute(
        """
        INSERT INTO jobs (url, company, title, location, job_board, status, attempts, phase, last_attempt_at)
        VALUES (?, 'Test Co', 'Software Engineer', 'Remote', 'indeed', ?, ?, ?, ?)
        """,
        (url, status, attempts, phase, last_attempt_at),
    )
    conn.commit()
    conn.close()


def _get_job(db_mod, url):
    conn = db_mod.get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    conn.close()
    return dict(row) if row else None


def test_recovery_submit_may_have_dispatched_never_requeues(temp_rec_db):
    url = "https://indeed.com/job/rec_dispatched"
    _insert_job(temp_rec_db, url, status=S.APPLYING, attempts=1, phase=S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED)

    # Worker crashes and restarts; reset_stuck_applying runs
    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0  # NOT requeued to tailored

    job = _get_job(temp_rec_db, url)
    assert job["status"] == S.SUBMISSION_UNCONFIRMED
    assert job["attempts"] == 1  # Attempts preserved
    assert "crash in submit phase" in job["status_reason"]


def test_recovery_confirmation_pending_never_requeues(temp_rec_db):
    url = "https://indeed.com/job/rec_pending"
    _insert_job(temp_rec_db, url, status=S.APPLYING, attempts=1, phase=S.PHASE_CONFIRMATION_PENDING)

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0

    job = _get_job(temp_rec_db, url)
    assert job["status"] == S.SUBMISSION_UNCONFIRMED
    assert job["attempts"] == 1
    assert "crash in submit phase" in job["status_reason"]


def test_recovery_confirmed_phase_invariant_violation(temp_rec_db):
    url = "https://indeed.com/job/rec_confirmed_mismatch"
    _insert_job(temp_rec_db, url, status=S.APPLYING, attempts=1, phase=S.PHASE_CONFIRMED)

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0

    job = _get_job(temp_rec_db, url)
    assert job["status"] == S.SUBMISSION_UNCONFIRMED
    assert "invariant violation" in job["status_reason"]


def test_recovery_pre_submit_requeues_when_attempts_remain(temp_rec_db):
    url = "https://indeed.com/job/rec_presubmit_ok"
    _insert_job(temp_rec_db, url, status=S.APPLYING, attempts=1, phase=S.PHASE_PRE_SUBMIT)

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 1  # Requeued to tailored

    job = _get_job(temp_rec_db, url)
    assert job["status"] == S.TAILORED
    assert job["attempts"] == 1
    assert "reset_after_crash" in job["status_reason"]


def test_recovery_pre_submit_fails_when_attempts_exhausted(temp_rec_db):
    url = "https://indeed.com/job/rec_presubmit_exhausted"
    _insert_job(temp_rec_db, url, status=S.APPLYING, attempts=S.MAX_ATTEMPTS, phase=S.PHASE_PRE_SUBMIT)

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0

    job = _get_job(temp_rec_db, url)
    assert job["status"] == S.FAILED
    assert job["attempts"] == S.MAX_ATTEMPTS
    assert "exceeded MAX_ATTEMPTS after crash" in job["status_reason"]


def test_recovery_missing_or_corrupt_phase_fails_closed(temp_rec_db):
    url_none = "https://indeed.com/job/rec_phase_none"
    url_corrupt = "https://indeed.com/job/rec_phase_corrupt"
    _insert_job(temp_rec_db, url_none, status=S.APPLYING, attempts=1, phase=None)
    _insert_job(temp_rec_db, url_corrupt, status=S.APPLYING, attempts=1, phase="BOGUS")

    requeued = apply.reset_stuck_applying(0)
    assert requeued == 0

    job_none = _get_job(temp_rec_db, url_none)
    assert job_none["status"] == S.SUBMISSION_UNCONFIRMED
    assert "missing or unknown phase" in job_none["status_reason"]

    job_corrupt = _get_job(temp_rec_db, url_corrupt)
    assert job_corrupt["status"] == S.SUBMISSION_UNCONFIRMED
    assert "missing or unknown phase" in job_corrupt["status_reason"]


def test_build_queue_eligibility_after_recovery(temp_rec_db):
    # Setup multiple jobs recovered after a crash:
    # 1. Recovered from PRE_SUBMIT (now tailored, attempts=1) -> eligible
    _insert_job(temp_rec_db, "https://indeed.com/job/q_presubmit", status=S.TAILORED, attempts=1, phase=S.PHASE_PRE_SUBMIT)
    # 2. Recovered from submit-risk (now submission_unconfirmed, attempts=1) -> not eligible
    _insert_job(temp_rec_db, "https://indeed.com/job/q_risk", status=S.SUBMISSION_UNCONFIRMED, attempts=1)
    # 3. Recovered from exhausted pre-submit (now failed, attempts=3) -> not eligible
    _insert_job(temp_rec_db, "https://indeed.com/job/q_failed", status=S.FAILED, attempts=3)

    cfg = {"search": {"stretch_share": 0.3}}
    # Fetch tailored jobs
    tailored = [dict(j) for j in temp_rec_db.get_jobs_by_status(S.TAILORED)]
    queue = apply.build_queue(tailored, cfg, remaining=10, done={})

    assert len(queue) == 1
    assert queue[0]["url"] == "https://indeed.com/job/q_presubmit"
