"""
Phase 7 Validation: Full-path composition validation.
Verifies the end-to-end claim -> launch -> local submit dispatch -> kill -> unwind -> persist -> restart -> recovery scenario.
Ensures no duplicate dispatch occurs on recovery and all phase invariants hold.
"""

import http.server
import socketserver
import threading
import time
from pathlib import Path
import sys
import pytest

# Ensure src is on sys.path
SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import db
import apply
import indeed_apply as ia
import states as S
from browser_watchdog import AttemptAbortContext, HardTimeoutError


@pytest.fixture
def temp_comp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "composition_test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db


def _insert_job(db_mod, url, status=S.TAILORED, attempts=0, phase=None, company="Acme Corp", title="Software Eng"):
    conn = db_mod.get_conn()
    conn.execute(
        """
        INSERT INTO jobs (url, company, title, location, job_board, apply_channel, status, attempts, phase)
        VALUES (?, ?, ?, 'Remote', 'indeed', 'indeed', ?, ?, ?)
        """,
        (url, company, title, status, attempts, phase),
    )
    conn.commit()
    conn.close()


def _get_job(db_mod, url):
    conn = db_mod.get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    conn.close()
    return dict(row) if row else None


class LocalDispatchHandler(http.server.BaseHTTPRequestHandler):
    dispatched_requests = []

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else ""
        LocalDispatchHandler.dispatched_requests.append({
            "path": self.path,
            "body": body,
            "timestamp": time.time(),
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format, *args):
        pass


@pytest.fixture
def local_endpoint():
    LocalDispatchHandler.dispatched_requests.clear()
    server = socketserver.TCPServer(("127.0.0.1", 0), LocalDispatchHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def test_composition_dispatch_before_click_return_timeout_persists_unconfirmed_and_prevents_retry(temp_comp_db, local_endpoint, monkeypatch):
    """
    Simulates the critical risk window:
    1. Job is claimed (phase=PRE_SUBMIT).
    2. Submit step is reached.
    3. Pre-click phase commit updates DB to SUBMIT_MAY_HAVE_DISPATCHED.
    4. Click executes, sending HTTP request to local endpoint.
    5. Watchdog abort triggers before click returns (or browser crashes immediately upon dispatch).
    6. Browser unwinds in bounded time; ApplyResult is SUBMISSION_UNCONFIRMED.
    7. Persistence stores status='submission_unconfirmed', phase='SUBMIT_MAY_HAVE_DISPATCHED'.
    8. Simulated restart runs reset_stuck_applying().
    9. Job is NOT requeued to tailored. Build queue does not include this job.
    10. No duplicate dispatch occurs.
    """
    cfg = {"resumes": {"default": "resumes/default.pdf"}, "limits": {"total_per_day": 10}, "search": {"stretch_share": 0.3}}
    monkeypatch.setattr("submission_gate.run_submission_gate", lambda j, c: [])
    monkeypatch.setattr("submission_gate.classify_gate_outcome", lambda f: "ok")
    monkeypatch.setattr(apply, "run_submission_gate", lambda j, c: [])
    monkeypatch.setattr(apply, "classify_gate_outcome", lambda f: "ok")

    url = "https://indeed.com/job/comp_dispatch_timeout"
    _insert_job(temp_comp_db, url, status=S.TAILORED, attempts=0, company="Alpha Inc", title="Core Dev")

    import urllib.request

    abort_ctx = AttemptAbortContext()

    def fake_route(job, cover, resume, shot, dry_run):
        # 1. Verify job is currently in applying with phase PRE_SUBMIT
        current = _get_job(temp_comp_db, job["url"])
        assert current["status"] == S.APPLYING
        assert current["phase"] == S.PHASE_PRE_SUBMIT

        # 2. Simulate reaching final submit step: commit submit risk
        committed = temp_comp_db.update_job_phase(job["url"], S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, job["attempts"])
        assert committed is True

        # 3. Dispatch HTTP request to local endpoint
        req = urllib.request.Request(f"{local_endpoint}/submit", data=b'{"action":"submit"}', method="POST")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

        # Verify endpoint received request
        assert len(LocalDispatchHandler.dispatched_requests) == 1

        # 4. Watchdog abort fires before click returns
        abort_ctx.trigger_timeout("watchdog kill immediately after submit dispatch")

        # Raise HardTimeoutError as DrissionPage would on process kill
        raise HardTimeoutError("browser connection lost after submit dispatch")

    monkeypatch.setattr(apply, "route", fake_route)

    # Execute apply_one()
    job_payload = {"url": url, "company": "Alpha Inc", "title": "Core Dev", "job_board": "indeed"}
    t0 = time.time()
    result = apply.apply_one(job_payload, cfg, dry_run=False)
    unwind_duration = time.time() - t0

    # Verification: bounded unwind (< 5.0 seconds)
    assert unwind_duration < 5.0

    # Verification: classified as SUBMISSION_UNCONFIRMED
    assert result is not None
    assert result.state == S.SUBMISSION_UNCONFIRMED

    # Verification: persisted state in DB
    persisted = _get_job(temp_comp_db, url)
    assert persisted["status"] == S.SUBMISSION_UNCONFIRMED
    assert persisted["phase"] == S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED
    assert persisted["attempts"] == 1

    # SIMULATE SYSTEM RESTART / CRASH RECOVERY
    recovered = apply.reset_stuck_applying(max_age_minutes=0)
    assert recovered == 0  # Not returned to queue

    # Check DB state after recovery
    post_recovery = _get_job(temp_comp_db, url)
    assert post_recovery["status"] == S.SUBMISSION_UNCONFIRMED
    assert post_recovery["phase"] == S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED

    # Check Queue eligibility
    tailored_jobs = [dict(j) for j in temp_comp_db.get_jobs_by_status(S.TAILORED)]
    queue = apply.build_queue(tailored_jobs, cfg, remaining=10, done={})
    assert len(queue) == 0

    # Assert exactly 1 dispatch occurred in total, no second attempt
    assert len(LocalDispatchHandler.dispatched_requests) == 1


def test_composition_pre_submit_timeout_recovers_cleanly_and_allows_safe_retry(temp_comp_db, monkeypatch):
    """
    Simulates pre-submit timeout (e.g. during form fill):
    1. Job is claimed (phase=PRE_SUBMIT).
    2. Watchdog timeout occurs before submit step is ever reached.
    3. Result is TIMEOUT.
    4. Persisted state transitions back to TAILORED (attempts=1 < 3).
    5. Next queue build includes this job for retry.
    """
    cfg = {"resumes": {"default": "resumes/default.pdf"}, "limits": {"total_per_day": 10}, "search": {"stretch_share": 0.3}}
    monkeypatch.setattr("submission_gate.run_submission_gate", lambda j, c: [])
    monkeypatch.setattr("submission_gate.classify_gate_outcome", lambda f: "ok")
    monkeypatch.setattr(apply, "run_submission_gate", lambda j, c: [])
    monkeypatch.setattr(apply, "classify_gate_outcome", lambda f: "ok")

    url = "https://indeed.com/job/comp_presubmit_timeout"
    _insert_job(temp_comp_db, url, status=S.TAILORED, attempts=0, company="Beta LLC", title="Backend Lead")

    def fake_route(job, cover, resume, shot, dry_run):
        # Fails during form fill, phase is still PRE_SUBMIT
        raise HardTimeoutError("timeout during question answer typing")

    monkeypatch.setattr(apply, "route", fake_route)

    job_payload = {"url": url, "company": "Beta LLC", "title": "Backend Lead", "job_board": "indeed"}
    result = apply.apply_one(job_payload, cfg, dry_run=False)

    assert result is not None
    assert result.state == S.TIMEOUT

    # DB state: retried to tailored because attempts=1 < 3
    persisted = _get_job(temp_comp_db, url)
    assert persisted["status"] == S.TAILORED
    assert persisted["phase"] == S.PHASE_PRE_SUBMIT
    assert persisted["attempts"] == 1

    # Queue admits it for retry
    tailored_jobs = [dict(j) for j in temp_comp_db.get_jobs_by_status(S.TAILORED)]
    queue = apply.build_queue(tailored_jobs, cfg, remaining=10, done={})
    assert len(queue) == 1
    assert queue[0]["url"] == url


def test_composition_confirmed_success_persists_and_is_immutable_across_restarts(temp_comp_db, local_endpoint, monkeypatch):
    """
    Simulates full successful path:
    1. Job is claimed (phase=PRE_SUBMIT).
    2. Submit step commits SUBMIT_MAY_HAVE_DISPATCHED.
    3. Click dispatches request.
    4. Click returns, commits CONFIRMATION_PENDING.
    5. Confirmation screen observed, commits CONFIRMED.
    6. Persisted as SUBMITTED with phase=CONFIRMED.
    7. System restart / crash recovery runs.
    8. Status remains SUBMITTED, never requeued or altered.
    """
    cfg = {"resumes": {"default": "resumes/default.pdf"}, "limits": {"total_per_day": 10}, "search": {"stretch_share": 0.3}}
    monkeypatch.setattr("submission_gate.run_submission_gate", lambda j, c: [])
    monkeypatch.setattr("submission_gate.classify_gate_outcome", lambda f: "ok")
    monkeypatch.setattr(apply, "run_submission_gate", lambda j, c: [])
    monkeypatch.setattr(apply, "classify_gate_outcome", lambda f: "ok")

    url = "https://indeed.com/job/comp_success"
    _insert_job(temp_comp_db, url, status=S.TAILORED, attempts=0, company="Gamma Corp", title="Fullstack Eng")

    import urllib.request

    def fake_route(job, cover, resume, shot, dry_run):
        # 1. Submit pre-click commit
        temp_comp_db.update_job_phase(job["url"], S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, job["attempts"])
        # 2. Click dispatches
        req = urllib.request.Request(f"{local_endpoint}/submit", data=b'{"action":"submit"}', method="POST")
        urllib.request.urlopen(req)
        # 3. Post-click commit
        temp_comp_db.update_job_phase(job["url"], S.PHASE_CONFIRMATION_PENDING, job["attempts"])
        # 4. Confirm evidence commit
        temp_comp_db.update_job_phase(job["url"], S.PHASE_CONFIRMED, job["attempts"])
        return S.ApplyResult(S.SUBMITTED, evidence="Application submitted successfully confirmation")

    monkeypatch.setattr(apply, "route", fake_route)

    job_payload = {"url": url, "company": "Gamma Corp", "title": "Fullstack Eng", "job_board": "indeed"}
    result = apply.apply_one(job_payload, cfg, dry_run=False)

    assert result is not None
    assert result.state == S.SUBMITTED

    persisted = _get_job(temp_comp_db, url)
    assert persisted["status"] == S.SUBMITTED
    assert persisted["phase"] == S.PHASE_CONFIRMED

    # Crash recovery does not touch submitted jobs
    recovered = apply.reset_stuck_applying(max_age_minutes=0)
    assert recovered == 0

    post_recovery = _get_job(temp_comp_db, url)
    assert post_recovery["status"] == S.SUBMITTED
    assert post_recovery["phase"] == S.PHASE_CONFIRMED
