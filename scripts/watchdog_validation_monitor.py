#!/usr/bin/env python3
"""
watchdog_validation_monitor.py — Production-Validation Monitoring Subsystem

Read-only, zero-mutation observability monitor for the Hermes Indeed Timeout Containment
subsystem. Continuously evaluates application database, process tree, filesystem profiles,
and execution logs to detect and record:
- Watchdog timeouts and phase attribution (TIMEOUT vs. SUBMISSION_UNCONFIRMED)
- Stuck APPLYING jobs exceeding the 6-minute budget
- Crash recovery actions and state transitions
- Duplicate submissions across all jobs
- Orphan Chrome browser processes and adopted init processes
- Orphan profile directories and stale Singleton locks
- Browser ownership verification failures and endpoint collisions

Never modifies any database record or process. Operates in strict read-only mode.

CLI:
  python scripts/watchdog_validation_monitor.py [--once] [--interval 15] [--db db/applications.db]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "applications.db"
DEFAULT_EVENTS_FILE = ROOT / "output" / "watchdog_validation_events.jsonl"
DEFAULT_LOG_FILE = ROOT / "output" / "hermes_cron.log"
DEFAULT_PROFILES_DIR = ROOT / "output" / "indeed_profiles"

STUCK_APPLYING_SECONDS = 7 * 60  # 7 minutes (> 6 min MAX_APPLY_SECONDS)
ORPHAN_PROFILE_AGE_SECONDS = 15 * 60  # 15 minutes


class ValidationMonitor:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB,
        events_file: Path = DEFAULT_EVENTS_FILE,
        log_file: Path = DEFAULT_LOG_FILE,
        profiles_dir: Path = DEFAULT_PROFILES_DIR,
    ) -> None:
        self.db_path = db_path
        self.events_file = events_file
        self.log_file = log_file
        self.profiles_dir = profiles_dir

        self.events_file.parent.mkdir(parents=True, exist_ok=True)

        # In-memory tracking of observed states to emit only edge-triggered transitions
        self._last_job_states: dict[str, dict[str, Any]] = {}
        self._emitted_event_keys: set[str] = set()
        self._last_log_offset: int = 0
        self._init_log_offset()

    def _init_log_offset(self) -> None:
        """Initialize log file offset to current end if not tracking, or 0 if small."""
        if self.log_file.exists():
            size = self.log_file.stat().st_size
            # Read from last 64KB on startup if file is large
            self._last_log_offset = max(0, size - 65536)

    def _get_ro_conn(self) -> sqlite3.Connection | None:
        """Open a guaranteed read-only connection to the SQLite database."""
        if not self.db_path.exists():
            return None
        try:
            uri = f"file:{self.db_path.resolve()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=3.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            return conn
        except sqlite3.Error as exc:
            self._emit_event(
                event_type="DB_READ_ERROR",
                details={"error": str(exc)},
            )
            return None

    def _emit_event(
        self,
        event_type: str,
        job_url: str | None = None,
        attempt: int | None = None,
        phase: str | None = None,
        status: str | None = None,
        pid: int | None = None,
        browser_identity: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        """Append a structured JSONL event to the validation log."""
        if dedupe_key and dedupe_key in self._emitted_event_keys:
            return
        if dedupe_key:
            self._emitted_event_keys.add(dedupe_key)

        now = datetime.now(timezone.utc).astimezone().isoformat()
        payload = {
            "timestamp": now,
            "event_type": event_type,
            "job_url": job_url,
            "attempt": attempt,
            "phase": phase,
            "status": status,
            "pid": pid,
            "browser_identity": browser_identity,
            "details": details or {},
        }
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def poll_database(self) -> None:
        """Inspect jobs table for transitions, timeouts, stuck rows, and duplicate submissions."""
        conn = self._get_ro_conn()
        if not conn:
            return

        try:
            # 1. Fetch relevant job records
            query = """
                SELECT url, company, title, status, phase, attempts, status_reason,
                       last_attempt_at, applied_at, submission_evidence
                FROM jobs
            """
            rows = conn.execute(query).fetchall()

            now_ts = time.time()
            seen_submitted_keys: dict[str, list[dict]] = {}

            for r in rows:
                url = r["url"]
                status = r["status"]
                phase = r["phase"]
                attempts = r["attempts"] or 0
                reason = r["status_reason"] or ""
                last_attempt_at = r["last_attempt_at"]
                company = r["company"] or ""
                title = r["title"] or ""

                prev = self._last_job_states.get(url)

                # Track submitted roles for duplicate detection
                if status == "submitted":
                    dk = f"{company.strip().lower()}||{title.strip().lower()}"
                    seen_submitted_keys.setdefault(dk, []).append({
                        "url": url,
                        "applied_at": r["applied_at"],
                        "phase": phase,
                    })

                # Check state changes against previous observation
                if prev is not None:
                    prev_status = prev.get("status")
                    prev_phase = prev.get("phase")
                    prev_attempts = prev.get("attempts", 0)

                    # A. State transition
                    if prev_status != status or prev_phase != phase or prev_attempts != attempts:
                        self._emit_event(
                            event_type="PHASE_TRANSITION",
                            job_url=url,
                            attempt=attempts,
                            phase=phase,
                            status=status,
                            details={
                                "from_status": prev_status,
                                "to_status": status,
                                "from_phase": prev_phase,
                                "to_phase": phase,
                                "from_attempts": prev_attempts,
                                "to_attempts": attempts,
                                "status_reason": reason,
                            },
                        )

                        # B. Detect invalid phase transitions
                        self._validate_transition_invariants(url, prev_status, status, prev_phase, phase, attempts, reason)

                else:
                    # First observation of this job: record if in an interesting terminal/active state
                    if status in ("timeout", "submission_unconfirmed"):
                        self._emit_event(
                            event_type="INITIAL_STATE_OBSERVED",
                            job_url=url,
                            attempt=attempts,
                            phase=phase,
                            status=status,
                            details={"status_reason": reason},
                            dedupe_key=f"init_{url}_{status}_{phase}_{attempts}",
                        )

                # C. Detect TIMEOUT status outcome
                if status == "timeout" and (not prev or prev.get("status") != "timeout"):
                    self._emit_event(
                        event_type="WATCHDOG_TIMEOUT_RECORDED",
                        job_url=url,
                        attempt=attempts,
                        phase=phase,
                        status=status,
                        details={
                            "status_reason": reason,
                            "classification": "TIMEOUT",
                            "retryable": attempts < 3,
                        },
                        dedupe_key=f"timeout_{url}_{attempts}",
                    )

                # D. Detect SUBMISSION_UNCONFIRMED status outcome
                if status == "submission_unconfirmed" and (not prev or prev.get("status") != "submission_unconfirmed"):
                    self._emit_event(
                        event_type="SUBMISSION_UNCONFIRMED_RECORDED",
                        job_url=url,
                        attempt=attempts,
                        phase=phase,
                        status=status,
                        details={
                            "status_reason": reason,
                            "classification": "SUBMISSION_UNCONFIRMED",
                            "protected_from_retry": True,
                        },
                        dedupe_key=f"unconfirmed_{url}_{attempts}",
                    )

                # E. Detect Crash Recovery Actions
                if reason and ("crash" in reason.lower() or "reset_after_crash" in reason.lower()):
                    event_key = f"recovery_{url}_{attempts}_{status}_{reason}"
                    self._emit_event(
                        event_type="RECOVERY_ACTION_DETECTED",
                        job_url=url,
                        attempt=attempts,
                        phase=phase,
                        status=status,
                        details={"status_reason": reason},
                        dedupe_key=event_key,
                    )

                # F. Detect Stuck APPLYING Jobs
                if status == "applying":
                    age_seconds = self._calculate_age_seconds(last_attempt_at, now_ts)
                    if age_seconds > STUCK_APPLYING_SECONDS:
                        self._emit_event(
                            event_type="STUCK_APPLYING_DETECTED",
                            job_url=url,
                            attempt=attempts,
                            phase=phase,
                            status=status,
                            details={
                                "last_attempt_at": last_attempt_at,
                                "duration_seconds": round(age_seconds, 1),
                                "stuck_threshold_seconds": STUCK_APPLYING_SECONDS,
                            },
                            dedupe_key=f"stuck_{url}_{attempts}_{int(age_seconds // 300)}",
                        )

                # Save current state for next poll
                self._last_job_states[url] = {
                    "status": status,
                    "phase": phase,
                    "attempts": attempts,
                    "status_reason": reason,
                }

            # G. Check for duplicate submissions
            for dk, sub_list in seen_submitted_keys.items():
                if len(sub_list) > 1:
                    company_title = dk.replace("||", " — ")
                    self._emit_event(
                        event_type="DUPLICATE_SUBMISSION_DETECTED",
                        details={
                            "role": company_title,
                            "occurrences": len(sub_list),
                            "entries": sub_list,
                        },
                        dedupe_key=f"duplicate_{dk}_{len(sub_list)}",
                    )

        except sqlite3.Error as exc:
            self._emit_event(
                event_type="DB_QUERY_ERROR",
                details={"error": str(exc)},
            )
        finally:
            conn.close()

    def _validate_transition_invariants(
        self,
        url: str,
        prev_status: str | None,
        new_status: str,
        prev_phase: str | None,
        new_phase: str | None,
        attempts: int,
        reason: str,
    ) -> None:
        """Assert correctness of state transitions and emit alerts on invariant breaches."""
        # Invariant 1: submitted row must NEVER be downgraded
        if prev_status == "submitted" and new_status != "submitted":
            self._emit_event(
                event_type="CRITICAL_INVARIANT_VIOLATION",
                job_url=url,
                attempt=attempts,
                phase=new_phase,
                status=new_status,
                details={
                    "violation": "SUBMITTED_DOWNGRADED",
                    "from_status": prev_status,
                    "to_status": new_status,
                },
            )

        # Invariant 2: submission_unconfirmed must NEVER be requeued to tailored or applying
        if prev_status == "submission_unconfirmed" and new_status in ("tailored", "applying"):
            self._emit_event(
                event_type="CRITICAL_INVARIANT_VIOLATION",
                job_url=url,
                attempt=attempts,
                phase=new_phase,
                status=new_status,
                details={
                    "violation": "UNCONFIRMED_REQUEUED",
                    "from_status": prev_status,
                    "to_status": new_status,
                },
            )

        # Invariant 3: submit-risk phases must never transition back to tailored
        if prev_phase in ("SUBMIT_MAY_HAVE_DISPATCHED", "CONFIRMATION_PENDING") and new_status == "tailored":
            self._emit_event(
                event_type="CRITICAL_INVARIANT_VIOLATION",
                job_url=url,
                attempt=attempts,
                phase=new_phase,
                status=new_status,
                details={
                    "violation": "SUBMIT_RISK_REQUEUED_TO_TAILORED",
                    "prev_phase": prev_phase,
                    "new_status": new_status,
                },
            )

        # Invariant 4: submitted status requires CONFIRMED phase
        if new_status == "submitted" and new_phase != "CONFIRMED":
            self._emit_event(
                event_type="INVALID_TRANSITION_DETECTED",
                job_url=url,
                attempt=attempts,
                phase=new_phase,
                status=new_status,
                details={
                    "violation": "SUBMITTED_WITHOUT_CONFIRMED_PHASE",
                    "phase": new_phase,
                },
            )

    def _calculate_age_seconds(self, iso_ts: str | None, now_ts: float) -> float:
        """Parse SQLite datetime string into age seconds."""
        if not iso_ts:
            return 0.0
        try:
            dt = datetime.fromisoformat(iso_ts)
            # If timestamp is naive, assume local time
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return max(0.0, now_ts - dt.timestamp())
        except Exception:
            return 0.0

    def poll_processes(self) -> None:
        """Inspect process tree for active Hermes workers, owned browsers, and orphan Chromes."""
        hermes_procs: list[dict[str, Any]] = []
        chrome_procs: list[dict[str, Any]] = []

        for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "create_time", "status"]):
            try:
                cmdline = p.info.get("cmdline") or []
                cmd_str = " ".join(cmdline).lower()
                name = (p.info.get("name") or "").lower()
                pid = p.info["pid"]
                ppid = p.info["ppid"]
                status = p.info.get("status")

                # Detect active Hermes execution processes
                if any(x in cmd_str for x in ("apply.py", "pipeline.py", "run_hermes.sh")):
                    hermes_procs.append({
                        "pid": pid,
                        "cmdline": cmd_str[:200],
                        "create_time": p.info["create_time"],
                    })

                # Detect Chrome processes
                if "chrome" in name or "chrome" in cmd_str:
                    is_hermes_chrome = any(x in cmd_str for x in ("indeed_profiles", "chrome-indeed-profile", "remote-debugging-port"))
                    chrome_procs.append({
                        "pid": pid,
                        "ppid": ppid,
                        "cmdline": cmd_str,
                        "is_hermes_chrome": is_hermes_chrome,
                        "is_zombie": status == psutil.STATUS_ZOMBIE,
                        "create_time": p.info["create_time"],
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        is_hermes_running = len(hermes_procs) > 0

        # Detect orphan Chrome processes
        for cp in chrome_procs:
            pid = cp["pid"]
            ppid = cp["ppid"]
            is_hermes_chrome = cp["is_hermes_chrome"]

            # Orphan Condition 1: Hermes-related Chrome running while no Hermes worker is alive
            if is_hermes_chrome and not is_hermes_running:
                # Give a 20-second grace window after start
                age = time.time() - cp["create_time"]
                if age > 20:
                    self._emit_event(
                        event_type="ORPHAN_PROCESS_DETECTED",
                        pid=pid,
                        details={
                            "reason": "hermes_chrome_running_without_hermes_worker",
                            "cmdline": cp["cmdline"][:300],
                            "ppid": ppid,
                            "age_seconds": round(age, 1),
                        },
                        dedupe_key=f"orphan_chrome_{pid}",
                    )

            # Orphan Condition 2: Adopted by init (PPID == 1)
            if is_hermes_chrome and ppid == 1:
                self._emit_event(
                    event_type="ORPHAN_PROCESS_DETECTED",
                    pid=pid,
                    details={
                        "reason": "chrome_reparented_to_init",
                        "cmdline": cp["cmdline"][:300],
                        "ppid": ppid,
                    },
                    dedupe_key=f"init_adopted_{pid}",
                )

    def poll_filesystem(self) -> None:
        """Inspect ephemeral profile directories and stale Singleton locks."""
        # 1. Inspect output/indeed_profiles/
        target_dirs = []
        if self.profiles_dir.exists():
            for p in self.profiles_dir.iterdir():
                if p.is_dir() and p.name.startswith("indeed-att-"):
                    target_dirs.append(p)

        # Also check /tmp/hermes-indeed-profile-*
        tmp_dir = Path("/tmp")
        try:
            for p in tmp_dir.iterdir():
                if p.is_dir() and p.name.startswith("hermes-indeed-profile-"):
                    target_dirs.append(p)
        except OSError:
            pass

        now_ts = time.time()

        for pdir in target_dirs:
            try:
                mtime = pdir.stat().st_mtime
                age_seconds = now_ts - mtime

                # Check if any live process is currently referencing this directory
                pdir_str = str(pdir)
                is_active = False
                for proc in psutil.process_iter(["cmdline"]):
                    try:
                        cmd = " ".join(proc.info.get("cmdline") or [])
                        if pdir_str in cmd:
                            is_active = True
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # If directory is old and has no owning process -> Orphan profile directory
                if not is_active and age_seconds > ORPHAN_PROFILE_AGE_SECONDS:
                    self._emit_event(
                        event_type="ORPHAN_PROFILE_DETECTED",
                        details={
                            "profile_path": pdir_str,
                            "age_minutes": round(age_seconds / 60.0, 1),
                        },
                        dedupe_key=f"orphan_profile_{pdir.name}",
                    )

                # Check for stale Singleton locks inside the directory
                singleton_lock = pdir / "SingletonLock"
                if singleton_lock.exists() and not is_active:
                    self._emit_event(
                        event_type="STALE_SINGLETON_DETECTED",
                        details={
                            "lock_file": str(singleton_lock),
                            "profile_path": pdir_str,
                        },
                        dedupe_key=f"singleton_{pdir.name}",
                    )

            except OSError:
                continue

    def poll_logs(self) -> None:
        """Scan application execution logs for ownership errors, watchdog actions, or disconnects."""
        if not self.log_file.exists():
            return

        try:
            size = self.log_file.stat().st_size
            if size < self._last_log_offset:
                # File was truncated or rotated
                self._last_log_offset = 0

            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._last_log_offset)
                new_lines = f.readlines()
                self._last_log_offset = f.tell()

            for line in new_lines:
                clean_line = line.strip()
                if not clean_line:
                    continue

                # Ownership verification failure
                if "BrowserOwnershipError" in clean_line or "allocated endpoint" in clean_line and "already occupied" in clean_line:
                    self._emit_event(
                        event_type="OWNERSHIP_VERIFICATION_FAILURE",
                        details={"log_line": clean_line[:400]},
                    )

                # Watchdog termination escalation signal
                if "[browser_watchdog]" in clean_line or "HardTimeoutError" in clean_line:
                    self._emit_event(
                        event_type="WATCHDOG_LOG_DETECTED",
                        details={"log_line": clean_line[:400]},
                    )

                # Profile cleanup failure log
                if "cleanup_profile" in clean_line and "failed" in clean_line.lower():
                    self._emit_event(
                        event_type="CLEANUP_FAILURE_DETECTED",
                        details={"log_line": clean_line[:400]},
                    )

        except Exception as exc:
            self._emit_event(
                event_type="LOG_PARSE_ERROR",
                details={"error": str(exc)},
            )

    def run_once(self) -> None:
        """Execute a single polling cycle across all subsystems."""
        self.poll_database()
        self.poll_processes()
        self.poll_filesystem()
        self.poll_logs()

    def run_loop(self, interval_seconds: float = 15.0) -> None:
        """Run continuous polling loop until interrupted."""
        self._emit_event(
            event_type="MONITOR_STARTED",
            details={
                "interval_seconds": interval_seconds,
                "db_path": str(self.db_path),
                "events_file": str(self.events_file),
            },
        )
        print(f"[{datetime.now().isoformat()}] Validation monitor running (interval: {interval_seconds}s, read-only)...")
        try:
            while True:
                self.run_once()
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            self._emit_event(event_type="MONITOR_STOPPED", details={"reason": "keyboard_interrupt"})
            print(f"\n[{datetime.now().isoformat()}] Validation monitor stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes Indeed Timeout Production Validation Monitor")
    parser.add_argument("--once", action="store_true", help="Run a single evaluation cycle and exit")
    parser.add_argument("--interval", type=float, default=15.0, help="Polling interval in seconds (default: 15)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to applications.db")
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS_FILE, help="Path to events.jsonl output")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_FILE, help="Path to hermes_cron.log")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_DIR, help="Path to indeed_profiles directory")
    args = parser.parse_args()

    monitor = ValidationMonitor(
        db_path=args.db,
        events_file=args.events,
        log_file=args.log,
        profiles_dir=args.profiles,
    )

    if args.once:
        monitor.run_once()
        print(f"Validation monitor cycle completed. Events recorded in {args.events}")
    else:
        monitor.run_loop(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
