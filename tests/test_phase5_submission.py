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
def temp_sub_db(tmp_path, monkeypatch):
    db_file = tmp_path / "sub_test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db


def _insert_test_job(db_mod, url, status=S.TAILORED, attempts=0, phase=None):
    conn = db_mod.get_conn()
    conn.execute(
        """
        INSERT INTO jobs (url, company, title, location, job_board, apply_channel, status, attempts, phase)
        VALUES (?, 'Acme Corp', 'Lead Engineer', 'Remote', 'indeed', 'indeed', ?, ?, ?)
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


class MockButtonElement:
    def __init__(self, on_click_hook=None):
        self.on_click_hook = on_click_hook

    def click(self, by_js=None):
        if self.on_click_hook:
            self.on_click_hook()


class MockIndeedPage:
    def __init__(self, on_click_hook=None):
        self.on_click_hook = on_click_hook
        self.buttons = [["0", "submit application", "ia-submitbutton"]]

    def run_js(self, script):
        return self.buttons

    def ele(self, selector, timeout=2):
        if "data-hermes-btn" in selector:
            return MockButtonElement(self.on_click_hook)
        return None


def test_no_click_occurs_if_phase_commit_fails(temp_sub_db):
    url = "https://indeed.com/job/fail_commit"
    _insert_test_job(temp_sub_db, url, status=S.TAILORED, attempts=0)
    # Claim job so attempts=1, phase=PRE_SUBMIT
    assert temp_sub_db.claim_job(url) is True

    clicked = []
    page = MockIndeedPage(on_click_hook=lambda: clicked.append(True))
    # Pass mismatched attempt (e.g. attempt=99) so update_job_phase fails
    job_bad_attempt = {"url": url, "attempts": 99}

    with pytest.raises(RuntimeError, match="Failed to commit SUBMIT_MAY_HAVE_DISPATCHED"):
        ia._click_next_or_submit(page, dry_run=False, job=job_bad_attempt)

    # Click must NOT have been called!
    assert clicked == []
    # Phase must remain PRE_SUBMIT
    assert temp_sub_db.get_job_phase(url) == S.PHASE_PRE_SUBMIT


def test_interrupt_after_phase_commit_before_click(temp_sub_db):
    url = "https://indeed.com/job/pre_click_interrupt"
    _insert_test_job(temp_sub_db, url, status=S.TAILORED, attempts=0)
    assert temp_sub_db.claim_job(url) is True

    abort_ctx = AttemptAbortContext()

    def kill_before_click():
        abort_ctx.trigger_timeout("killed before click dispatched")
        raise HardTimeoutError("killed before click")

    page = MockIndeedPage(on_click_hook=kill_before_click)
    job_info = {"url": url, "attempts": 1}

    with pytest.raises(HardTimeoutError):
        ia._click_next_or_submit(page, dry_run=False, abort_context=abort_ctx, job=job_info)

    # Phase was committed before click
    assert temp_sub_db.get_job_phase(url) == S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED

    # Classifying timeout in this phase MUST yield SUBMISSION_UNCONFIRMED
    res = ia._classify_timeout_result(job_info, abort_ctx.timeout_reason)
    assert res.state == S.SUBMISSION_UNCONFIRMED

    # Persist through apply.py record_result
    final_status = apply.record_result(job_info, res)
    assert final_status == S.SUBMISSION_UNCONFIRMED
    assert _get_job(temp_sub_db, url)["status"] == S.SUBMISSION_UNCONFIRMED


def test_local_request_dispatched_before_click_returns_then_killed(temp_sub_db):
    """Real HTTP test server records submission request while click is in flight;
    watchdog kills Chrome before click returns."""
    received_requests = []
    server_started = threading.Event()

    class LocalSubmitHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received_requests.append(self.path)
            # Server delays response so timeout / kill occurs while in flight
            time.sleep(1.0)
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), LocalSubmitHandler)
    server_port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = "https://indeed.com/job/inflight_dispatch"
    _insert_test_job(temp_sub_db, url, status=S.TAILORED, attempts=0)
    assert temp_sub_db.claim_job(url) is True

    abort_ctx = AttemptAbortContext()

    def simulate_dispatch_and_kill():
        import urllib.request
        # Dispatch request to local server
        req = urllib.request.Request(f"http://127.0.0.1:{server_port}/submit", data=b"form_data=1")
        # In a real browser, CDP triggers the network request before click() returns
        def post_async():
            try:
                urllib.request.urlopen(req, timeout=2.0)
            except Exception:
                pass
        t = threading.Thread(target=post_async, daemon=True)
        t.start()
        time.sleep(0.2)
        # Verify local server actually received the request
        assert len(received_requests) == 1
        # Now kill / abort before click returns
        abort_ctx.trigger_timeout("Chrome killed while request in flight before click returned")
        raise HardTimeoutError("Chrome killed during dispatch")

    try:
        page = MockIndeedPage(on_click_hook=simulate_dispatch_and_kill)
        job_info = {"url": url, "attempts": 1}

        with pytest.raises(HardTimeoutError):
            ia._click_next_or_submit(page, dry_run=False, abort_context=abort_ctx, job=job_info)

        # In DB, phase is SUBMIT_MAY_HAVE_DISPATCHED
        assert temp_sub_db.get_job_phase(url) == S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED

        # Classification must be SUBMISSION_UNCONFIRMED
        res = ia._classify_timeout_result(job_info, abort_ctx.timeout_reason)
        assert res.state == S.SUBMISSION_UNCONFIRMED

        apply.record_result(job_info, res)
        assert _get_job(temp_sub_db, url)["status"] == S.SUBMISSION_UNCONFIRMED
    finally:
        server.shutdown()
        server.server_close()


def test_interrupt_after_click_returns_before_confirmation(temp_sub_db):
    url = "https://indeed.com/job/post_click_interrupt"
    _insert_test_job(temp_sub_db, url, status=S.TAILORED, attempts=0)
    assert temp_sub_db.claim_job(url) is True

    # Click returns normally
    page = MockIndeedPage(on_click_hook=lambda: None)
    job_info = {"url": url, "attempts": 1}

    adv, was_final = ia._click_next_or_submit(page, dry_run=False, job=job_info)
    assert adv is True
    assert was_final is True
    # Now phase in DB is CONFIRMATION_PENDING
    assert temp_sub_db.get_job_phase(url) == S.PHASE_CONFIRMATION_PENDING

    # Kill occurs before confirmation
    res = ia._classify_timeout_result(job_info, "watchdog killed before confirmation page")
    assert res.state == S.SUBMISSION_UNCONFIRMED

    apply.record_result(job_info, res)
    assert _get_job(temp_sub_db, url)["status"] == S.SUBMISSION_UNCONFIRMED


def test_confirmation_observed_persists_confirmed_phase(temp_sub_db):
    url = "https://indeed.com/job/confirmed_success"
    _insert_test_job(temp_sub_db, url, status=S.TAILORED, attempts=0)
    assert temp_sub_db.claim_job(url) is True

    job_info = {"url": url, "attempts": 1}

    # Simulate success page snapshot
    class FakeSuccessPage:
        pass

    ia._snapshot = lambda p: ("https://smartapply.indeed.com/complete", "Application Complete",
                              "your application has been submitted", "<html></html>")
    ia._verify_in_applied_history = lambda p, j: "; verified in history"
    ia._gmail_confirmation = lambda t: ""

    res = ia._confirm_final_submit(FakeSuccessPage(), job_info, "")
    assert res.state == S.SUBMITTED
    # Phase in DB was atomically set to CONFIRMED
    assert temp_sub_db.get_job_phase(url) == S.PHASE_CONFIRMED

    apply.record_result(job_info, res)
    job_row = _get_job(temp_sub_db, url)
    assert job_row["status"] == S.SUBMITTED
    assert job_row["phase"] == S.PHASE_CONFIRMED

    # A late watchdog firing must NEVER downgrade CONFIRMED
    late_res = ia._classify_timeout_result(job_info, "late watchdog firing")
    assert late_res.state == S.SUBMITTED


def test_full_pipeline_attribution_preserves_phases_and_retryability(temp_sub_db, monkeypatch):
    """Full path: apply_one() -> route() -> record_result()"""
    cfg = {"resumes": {"default": "resumes/default.pdf"}, "limits": {"total_per_day": 10}}
    monkeypatch.setattr("submission_gate.run_submission_gate", lambda j, c: [])
    monkeypatch.setattr("submission_gate.classify_gate_outcome", lambda f: "ok")
    monkeypatch.setattr(apply, "run_submission_gate", lambda j, c: [])
    monkeypatch.setattr(apply, "classify_gate_outcome", lambda f: "ok")

    # 1. Pre-submit timeout below cap -> transitions to TAILORED
    url_pre = "https://indeed.com/job/pipe_pre"
    _insert_test_job(temp_sub_db, url_pre, status=S.TAILORED, attempts=0)

    def fake_route_timeout(job, *a, **kw):
        raise HardTimeoutError("pre-submit timeout during form fill")

    monkeypatch.setattr(apply, "route", fake_route_timeout)

    res1 = apply.apply_one({"url": url_pre, "company": "Co", "title": "Dev", "job_board": "indeed"}, cfg, dry_run=False)
    assert res1.state == S.TIMEOUT
    row1 = _get_job(temp_sub_db, url_pre)
    assert row1["status"] == S.TAILORED  # Retried because attempts=1 < 3
    assert row1["attempts"] == 1

    # 2. Submit-risk timeout -> transitions to SUBMISSION_UNCONFIRMED (never retried)
    url_risk = "https://indeed.com/job/pipe_risk"
    _insert_test_job(temp_sub_db, url_risk, status=S.TAILORED, attempts=0)

    def fake_route_submit_risk(job, *a, **kw):
        # Set phase in DB before raising
        temp_sub_db.update_job_phase(job["url"], S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, job["attempts"])
        raise HardTimeoutError("timeout during submit dispatch")

    monkeypatch.setattr(apply, "route", fake_route_submit_risk)

    res2 = apply.apply_one({"url": url_risk, "company": "Co", "title": "Dev", "job_board": "indeed"}, cfg, dry_run=False)
    assert res2.state == S.SUBMISSION_UNCONFIRMED
    row2 = _get_job(temp_sub_db, url_risk)
    assert row2["status"] == S.SUBMISSION_UNCONFIRMED  # NOT tailored!
    assert row2["attempts"] == 1
