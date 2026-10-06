import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# Ensure src is on sys.path
SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import browser_watchdog as bw
import states as S
import indeed_apply as ia


def test_watchdog_natural_exit(tmp_path):
    port = 9811
    endpoint = f"127.0.0.1:{port}"
    prof = bw.create_unique_profile(base_dir=tmp_path)

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(0.5)", f"--remote-debugging-port={port}", f"--user-data-dir={prof}"]
    )
    abort_ctx = bw.AttemptAbortContext()
    watchdog = bw.BrowserWatchdog(
        root_pid=proc.pid,
        expected_endpoint=endpoint,
        expected_profile=prof,
        deadline_seconds=5.0,  # long deadline
        abort_context=abort_ctx,
    )
    watchdog.start()

    proc.wait()  # Process finishes naturally
    timed_out = watchdog.stop(join_timeout=2.0)

    assert timed_out is False
    assert watchdog.is_timed_out is False
    assert abort_ctx.is_timed_out is False


def test_watchdog_termination_escalation_kills_root_and_descendants(tmp_path):
    port = 9812
    endpoint = f"127.0.0.1:{port}"
    prof = bw.create_unique_profile(base_dir=tmp_path)

    # Launch a process that spawns a child process and ignores SIGTERM to force SIGKILL escalation
    script = (
        "import sys, time, subprocess, signal\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, f"--remote-debugging-port={port}", f"--user-data-dir={prof}"]
    )
    abort_ctx = bw.AttemptAbortContext()
    watchdog = bw.BrowserWatchdog(
        root_pid=proc.pid,
        expected_endpoint=endpoint,
        expected_profile=prof,
        deadline_seconds=0.3,
        grace_period_seconds=0.2,
        abort_context=abort_ctx,
    )
    watchdog.start()

    # Wait for watchdog to escalate and kill
    time.sleep(1.2)
    watchdog.stop(join_timeout=2.0)

    assert watchdog.is_timed_out is True
    assert abort_ctx.is_timed_out is True
    assert proc.poll() is not None  # Root process is dead
    assert watchdog.cleanup_confirmed is True


def test_watchdog_process_generation_mismatch_prevents_signaling(tmp_path):
    port = 9813
    endpoint = f"127.0.0.1:{port}"
    prof = bw.create_unique_profile(base_dir=tmp_path)

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(0.1)", f"--remote-debugging-port={port}", f"--user-data-dir={prof}"]
    )
    abort_ctx = bw.AttemptAbortContext()
    watchdog = bw.BrowserWatchdog(
        root_pid=proc.pid,
        expected_endpoint=endpoint,
        expected_profile=prof,
        deadline_seconds=0.4,
        abort_context=abort_ctx,
    )
    # Wait for process to exit
    proc.wait()

    # Tamper with the root identity to simulate a recycled PID with a different starttime
    original_ident = watchdog.root_ident
    tampered_ident = bw.ProcessIdentity(pid=original_ident.pid, starttime=original_ident.starttime + 999999)
    watchdog.root_ident = tampered_ident

    # Let timeout fire
    watchdog.start()
    time.sleep(0.7)
    watchdog.stop()

    assert watchdog.is_timed_out is True
    # Trees searched with tampered identity must return empty, so no rogue signal was sent
    tree = bw.find_owned_process_tree(tampered_ident)
    assert tree == []


def test_watchdog_completion_race_preserves_confirmed_phase(monkeypatch):
    job = {"url": "https://indeed.com/job/race_test"}
    monkeypatch.setattr(ia, "get_job_phase", lambda url: S.PHASE_CONFIRMED)
    res = ia._classify_timeout_result(job, "late watchdog fired")
    assert res.state == S.SUBMITTED
    assert "submission confirmed" in (res.evidence or "")


def test_watchdog_submit_risk_phase_persists_unconfirmed(monkeypatch):
    job = {"url": "https://indeed.com/job/risk_test"}
    monkeypatch.setattr(ia, "get_job_phase", lambda url: S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED)
    res = ia._classify_timeout_result(job, "deadline exceeded during submit")
    assert res.state == S.SUBMISSION_UNCONFIRMED
    assert "SUBMIT_MAY_HAVE_DISPATCHED" in res.detail


def test_watchdog_pre_submit_phase_persists_timeout(monkeypatch):
    job = {"url": "https://indeed.com/job/presubmit_test"}
    monkeypatch.setattr(ia, "get_job_phase", lambda url: S.PHASE_PRE_SUBMIT)
    res = ia._classify_timeout_result(job, "deadline exceeded at form step 2")
    assert res.state == S.TIMEOUT
    assert "pre-submit timeout" in res.detail
