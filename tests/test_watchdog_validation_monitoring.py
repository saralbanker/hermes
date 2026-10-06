"""
Tests for the watchdog validation monitoring subsystem:
- watchdog_validation_monitor.py
- watchdog_validation_report.py
"""

import json
import sqlite3
import time
from pathlib import Path
import sys
import pytest

SRC_DIR = Path(__file__).parent.parent / "src"
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
for d in (SRC_DIR, SCRIPTS_DIR):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

from watchdog_validation_monitor import ValidationMonitor
import watchdog_validation_report as wr
import states as S


@pytest.fixture
def monitor_env(tmp_path):
    db_file = tmp_path / "test_monitor.db"
    events_file = tmp_path / "events.jsonl"
    log_file = tmp_path / "test_cron.log"
    profiles_dir = tmp_path / "test_profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            company TEXT,
            title TEXT,
            location TEXT,
            job_board TEXT,
            apply_channel TEXT,
            status TEXT NOT NULL,
            phase TEXT,
            attempts INTEGER DEFAULT 0,
            status_reason TEXT,
            last_attempt_at TEXT,
            applied_at TEXT,
            submission_evidence TEXT
        )
    """)
    conn.commit()
    conn.close()

    monitor = ValidationMonitor(
        db_path=db_file,
        events_file=events_file,
        log_file=log_file,
        profiles_dir=profiles_dir,
    )

    return {
        "db_file": db_file,
        "events_file": events_file,
        "log_file": log_file,
        "profiles_dir": profiles_dir,
        "monitor": monitor,
    }


def _read_events(events_file: Path) -> list[dict]:
    if not events_file.exists():
        return []
    with open(events_file, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_monitor_read_only_mode_prevents_writes(monitor_env):
    monitor = monitor_env["monitor"]
    conn = monitor._get_ro_conn()
    assert conn is not None
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE jobs SET status = 'failed'")
    conn.close()


def test_monitor_detects_timeout_and_unconfirmed(monitor_env):
    db_file = monitor_env["db_file"]
    monitor = monitor_env["monitor"]
    events_file = monitor_env["events_file"]

    # Insert a TIMEOUT and SUBMISSION_UNCONFIRMED row
    conn = sqlite3.connect(db_file)
    conn.execute("""
        INSERT INTO jobs (url, company, title, status, phase, attempts, status_reason)
        VALUES ('https://indeed.com/j1', 'Acme', 'Dev', 'timeout', 'PRE_SUBMIT', 1, 'watchdog timeout at form fill')
    """)
    conn.execute("""
        INSERT INTO jobs (url, company, title, status, phase, attempts, status_reason)
        VALUES ('https://indeed.com/j2', 'Beta', 'Lead', 'submission_unconfirmed', 'SUBMIT_MAY_HAVE_DISPATCHED', 1, 'timeout during submit')
    """)
    conn.commit()
    conn.close()

    monitor.poll_database()

    events = _read_events(events_file)
    types = [e["event_type"] for e in events]
    assert "WATCHDOG_TIMEOUT_RECORDED" in types
    assert "SUBMISSION_UNCONFIRMED_RECORDED" in types

    timeout_ev = next(e for e in events if e["event_type"] == "WATCHDOG_TIMEOUT_RECORDED")
    assert timeout_ev["job_url"] == "https://indeed.com/j1"
    assert timeout_ev["phase"] == "PRE_SUBMIT"
    assert timeout_ev["details"]["retryable"] is True

    unconf_ev = next(e for e in events if e["event_type"] == "SUBMISSION_UNCONFIRMED_RECORDED")
    assert unconf_ev["job_url"] == "https://indeed.com/j2"
    assert unconf_ev["phase"] == "SUBMIT_MAY_HAVE_DISPATCHED"
    assert unconf_ev["details"]["protected_from_retry"] is True


def test_monitor_detects_stuck_applying_job(monitor_env):
    db_file = monitor_env["db_file"]
    monitor = monitor_env["monitor"]
    events_file = monitor_env["events_file"]

    # Insert an applying row with last_attempt_at 15 minutes ago
    conn = sqlite3.connect(db_file)
    stuck_time = "2026-10-06T14:00:00"  # Well in past
    conn.execute("""
        INSERT INTO jobs (url, company, title, status, phase, attempts, last_attempt_at)
        VALUES ('https://indeed.com/stuck', 'StuckCo', 'Eng', 'applying', 'PRE_SUBMIT', 1, ?)
    """, (stuck_time,))
    conn.commit()
    conn.close()

    monitor.poll_database()

    events = _read_events(events_file)
    types = [e["event_type"] for e in events]
    assert "STUCK_APPLYING_DETECTED" in types

    stuck_ev = next(e for e in events if e["event_type"] == "STUCK_APPLYING_DETECTED")
    assert stuck_ev["job_url"] == "https://indeed.com/stuck"
    assert stuck_ev["details"]["duration_seconds"] > 420


def test_monitor_detects_critical_invariant_violations(monitor_env):
    db_file = monitor_env["db_file"]
    monitor = monitor_env["monitor"]
    events_file = monitor_env["events_file"]

    conn = sqlite3.connect(db_file)
    # Start with a submitted job
    conn.execute("""
        INSERT INTO jobs (url, company, title, status, phase, attempts)
        VALUES ('https://indeed.com/inv1', 'Gamma', 'Role', 'submitted', 'CONFIRMED', 1)
    """)
    # Start with an unconfirmed job
    conn.execute("""
        INSERT INTO jobs (url, company, title, status, phase, attempts)
        VALUES ('https://indeed.com/inv2', 'Delta', 'Role', 'submission_unconfirmed', 'SUBMIT_MAY_HAVE_DISPATCHED', 1)
    """)
    conn.commit()
    conn.close()

    # Initial poll
    monitor.poll_database()

    # Now mutate: downgrade submitted to failed, and requeue unconfirmed to tailored!
    conn = sqlite3.connect(db_file)
    conn.execute("UPDATE jobs SET status = 'failed' WHERE url = 'https://indeed.com/inv1'")
    conn.execute("UPDATE jobs SET status = 'tailored' WHERE url = 'https://indeed.com/inv2'")
    conn.commit()
    conn.close()

    # Second poll should catch the illegal transitions
    monitor.poll_database()

    events = _read_events(events_file)
    violations = [e for e in events if e["event_type"] == "CRITICAL_INVARIANT_VIOLATION"]
    assert len(violations) >= 2

    reasons = [v["details"].get("violation") for v in violations]
    assert "SUBMITTED_DOWNGRADED" in reasons
    assert "UNCONFIRMED_REQUEUED" in reasons


def test_monitor_detects_duplicate_submissions(monitor_env):
    db_file = monitor_env["db_file"]
    monitor = monitor_env["monitor"]
    events_file = monitor_env["events_file"]

    conn = sqlite3.connect(db_file)
    conn.execute("""
        INSERT INTO jobs (url, company, title, status, phase, applied_at)
        VALUES ('https://indeed.com/dupe1', 'Dupe Corp', 'Software Engineer', 'submitted', 'CONFIRMED', '2026-10-06T10:00:00')
    """)
    conn.execute("""
        INSERT INTO jobs (url, company, title, status, phase, applied_at)
        VALUES ('https://indeed.com/dupe2', 'Dupe Corp', 'Software Engineer', 'submitted', 'CONFIRMED', '2026-10-06T11:00:00')
    """)
    conn.commit()
    conn.close()

    monitor.poll_database()

    events = _read_events(events_file)
    types = [e["event_type"] for e in events]
    assert "DUPLICATE_SUBMISSION_DETECTED" in types

    dupe_ev = next(e for e in events if e["event_type"] == "DUPLICATE_SUBMISSION_DETECTED")
    assert dupe_ev["details"]["occurrences"] == 2


def test_monitor_detects_log_ownership_failure(monitor_env):
    log_file = monitor_env["log_file"]
    monitor = monitor_env["monitor"]
    events_file = monitor_env["events_file"]

    with open(log_file, "a", encoding="utf-8") as f:
        f.write("ERROR: BrowserOwnershipError: allocated endpoint 127.0.0.1:45321 was already occupied\n")

    monitor.poll_logs()

    events = _read_events(events_file)
    types = [e["event_type"] for e in events]
    assert "OWNERSHIP_VERIFICATION_FAILURE" in types


def test_report_generator_produces_scorecard(monitor_env, tmp_path):
    events_file = monitor_env["events_file"]
    db_file = monitor_env["db_file"]
    report_file = tmp_path / "test_report.md"

    # Add sample events
    events = [
        {
            "timestamp": "2026-10-06T14:00:00+05:30",
            "event_type": "WATCHDOG_TIMEOUT_RECORDED",
            "job_url": "https://indeed.com/job1",
            "attempt": 1,
            "phase": "PRE_SUBMIT",
            "status": "timeout",
            "pid": 4321,
            "browser_identity": {"pid": 4321, "starttime": 1000},
            "details": {"classification": "TIMEOUT", "retryable": True},
        },
        {
            "timestamp": "2026-10-06T14:15:00+05:30",
            "event_type": "SUBMISSION_UNCONFIRMED_RECORDED",
            "job_url": "https://indeed.com/job2",
            "attempt": 1,
            "phase": "SUBMIT_MAY_HAVE_DISPATCHED",
            "status": "submission_unconfirmed",
            "pid": 5432,
            "details": {"classification": "SUBMISSION_UNCONFIRMED", "protected_from_retry": True},
        },
    ]

    with open(events_file, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    db_data = wr.query_db_summary(db_file)
    loaded_events = wr.load_events(events_file)
    report_text = wr.generate_report(loaded_events, db_data, report_file)

    assert report_file.exists()
    assert "Q01" in report_text
    assert "Did any watchdog fire?" in report_text
    assert "Yes (1 times)" in report_text
    assert "Q06" in report_text
    assert "TIMEOUT: 1, SUBMISSION_UNCONFIRMED: 1" in report_text
    assert "Q08" in report_text
    assert "Did any duplicate submission occur?" in report_text
    assert "PASS" in report_text
