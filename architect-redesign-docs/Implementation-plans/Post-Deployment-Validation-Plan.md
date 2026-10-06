# Hermes Post-Deployment Validation Plan: Indeed Timeout Containment Monitoring

> **Status:** Approved for 8–24h Post-Deployment Observation  
> **Deployment Target:** Hermes Production Application Engine & Legacy Indeed Applier  
> **Date:** October 2026  
> **Mode:** Read-Only Observability (Zero Application Mutation)  

---

## 1. Purpose

This document establishes the production validation, observability, and forensic evidence collection protocol for the **Hermes Indeed Timeout Containment Subsystem** during its initial **8 to 24-hour production runtime window**.

The timeout containment implementation resolves five critical blockers:
1. Exclusive browser ownership and isolated DevTools endpoints.
2. Bounded helper unwind (< 5.0 seconds).
3. Durable submission phase markers (`PRE_SUBMIT` -> `SUBMIT_MAY_HAVE_DISPATCHED` -> `CONFIRMATION_PENDING` -> `CONFIRMED`).
4. Authoritative timeout attribution (`TIMEOUT` vs. `SUBMISSION_UNCONFIRMED`).
5. Duplicate-safe crash recovery (phase-before-attempt-count ordering).

The purpose of this validation monitoring system is to continuously collect empirical evidence from the live production environment to verify that these invariants hold under real network latency, Cloudflare challenges, and OS process lifecycle conditions without modifying application behavior or competing for database locks.

---

## 2. Monitoring Scope

The monitoring system runs as an independent, strictly read-only sidecar process (`scripts/watchdog_validation_monitor.py`) and generates forensic audit reports (`scripts/watchdog_validation_report.py`).

### Monitored Layers:
1. **Application Database (`db/applications.db`):**
   - Read-only SQLite URI (`mode=ro`, `PRAGMA query_only=ON`).
   - Row transitions in `jobs` (`status`, `phase`, `attempts`, `status_reason`, `last_attempt_at`).
   - Detection of duplicate applications, illegal phase rollbacks, and recovery actions.
2. **Operating System Process Tree (`/proc`, `psutil`):**
   - Active Chrome, Xvfb, and Python processes.
   - Parent-child process trees, PID generations (`starttime`), and PPID adoption by init (`PID 1`).
   - Detection of orphan browser processes lingering after job completion.
3. **Local Filesystem & Profiles (`output/`, `/tmp/`):**
   - Ephemeral profile directories (`output/indeed_profiles/indeed-att-*`, `/tmp/hermes-indeed-profile-*`).
   - Stale Chrome lock artifacts (`SingletonLock`, `SingletonCookie`, `SingletonSocket`).
   - Run lock integrity (`output/hermes.lock`).
4. **Execution Logs (`output/hermes_cron.log`):**
   - Application console output, watchdog arm/kill events, ownership verification results, and network disconnect events.

---

## 3. Validation Objectives & Key Questions

The monitor must definitively answer the following 15 forensic questions over the 8–24 hour post-deploy window:

| ID | Validation Question | Target State / Expected Behavior |
|:---|:---|:---|
| **Q01** | Did any watchdog fire? | Recorded with exact timestamp and reason; 0 unexpected kills. |
| **Q02** | Which job triggered it? | Identified by `job_url`, company, and title in event log. |
| **Q03** | Which browser PID was terminated? | Root PID recorded and verified against PID generation. |
| **Q04** | Which process tree was terminated? | All child processes (renderers, GPU, zygote) reaped; decoys untouched. |
| **Q05** | What phase was active when timeout occurred? | Durable phase read from DB (`PRE_SUBMIT`, `SUBMIT_MAY_HAVE_DISPATCHED`, `CONFIRMATION_PENDING`, or `CONFIRMED`). |
| **Q06** | Was the outcome `TIMEOUT` or `SUBMISSION_UNCONFIRMED`? | `PRE_SUBMIT` -> `TIMEOUT`; submit-risk -> `SUBMISSION_UNCONFIRMED`. Never generic `FAILED` or `FORM_CHANGED`. |
| **Q07** | Did recovery later touch that job? | If `PRE_SUBMIT` & `attempts < MAX`: requeued to `tailored`. If submit-risk/unknown: transitioned to `submission_unconfirmed`, never retried. |
| **Q08** | Did any duplicate submission occur? | Zero duplicate submissions for the same role across all boards. |
| **Q09** | Did browser ownership verification ever fail? | Zero ownership verification mismatches or endpoint collisions. |
| **Q10** | Did profile cleanup succeed? | Attempt profiles deleted after process tree termination; zero leakages. |
| **Q11** | Were any orphan Chrome processes left behind? | Zero Chrome processes running without an active owning Hermes job. |
| **Q12** | Were any orphan profiles left behind? | Zero unmanaged profile directories older than 15 minutes. |
| **Q13** | Were any stale Singleton files left behind? | Zero orphaned `SingletonLock` symlinks blocking future launches. |
| **Q14** | Did phase transitions occur in expected order? | Monotonic order: `PRE_SUBMIT` -> `SUBMIT_MAY_HAVE_DISPATCHED` -> `CONFIRMATION_PENDING` -> `CONFIRMED`. |
| **Q15** | Did any impossible state transition occur? | Zero illegal transitions (e.g. `submission_unconfirmed` -> `tailored`, or `submitted` downgrade). |

---

## 4. Metrics Collected

The validation monitor polls and records the following metrics continuously:

```
hermes_watchdog_activations_total           # Counter: Total watchdog timeout events fired
hermes_timeout_presubmit_total              # Counter: Jobs classified as TIMEOUT (retryable)
hermes_timeout_submit_risk_total            # Counter: Jobs classified as SUBMISSION_UNCONFIRMED
hermes_recovered_jobs_total                 # Counter: Stale applying jobs touched by crash recovery
hermes_recovery_requeued_total              # Counter: Stale PRE_SUBMIT jobs returned to tailored
hermes_recovery_unconfirmed_total           # Counter: Stale submit-risk jobs sealed as unconfirmed
hermes_duplicate_submissions_detected       # Gauge/Counter: Duplicate applications detected (must be 0)
hermes_orphan_browser_processes             # Gauge: Unowned Chrome processes currently living
hermes_orphan_profile_directories           # Gauge: Ephemeral profile directories uncleaned > 15m
hermes_stale_singleton_locks                # Gauge: Unowned SingletonLock files detected
hermes_stuck_applying_jobs                  # Gauge: Jobs in 'applying' status > 7 minutes
hermes_invalid_phase_transitions            # Counter: Out-of-order or illegal phase mutations (must be 0)
hermes_ownership_failures                   # Counter: Mismatched browser PIDs or occupied ports (must be 0)
```

---

## 5. Alert Conditions

The validation monitor evaluates alerts at each polling cycle. Alerts are categorized by severity:

### Priority 0: Critical (Immediate Intervention)
* **`CRIT-01: DUPLICATE_SUBMISSION_DETECTED`**
  * *Trigger:* More than 1 job record with status `submitted` exists for the same `(company, title)` dedupe key or same URL.
  * *Meaning:* System may have re-submitted an unconfirmed application.
* **`CRIT-02: SUBMIT_RISK_REQUEUED_TO_TAILORED`**
  * *Trigger:* A job with `phase IN ('SUBMIT_MAY_HAVE_DISPATCHED', 'CONFIRMATION_PENDING')` was moved to `tailored`.
  * *Meaning:* Crash recovery violated the submit-risk invariant.
* **`CRIT-03: CONFIRMED_SUBMISSION_DOWNGRADED`**
  * *Trigger:* A job with `phase = 'CONFIRMED'` or `status = 'submitted'` mutated to any non-submitted state.
  * *Meaning:* Data corruption or late watchdog race condition.

### Priority 1: High (Action Required within 1 Hour)
* **`WARN-01: STUCK_APPLYING_JOB`**
  * *Trigger:* A job remains in `status = 'applying'` for longer than 7.0 minutes (420 seconds).
  * *Meaning:* A browser run may have hung without the watchdog escalating, or worker crashed without releasing lock.
* **`WARN-02: ORPHAN_BROWSER_PROCESSES`**
  * *Trigger:* Chrome processes exist while no active Hermes pipeline/apply process is executing.
  * *Meaning:* Process tree escalation or cleanup failed to reap descendant renderers or GPU processes.
* **`WARN-03: OWNERSHIP_VERIFICATION_MISMATCH`**
  * *Trigger:* `BrowserOwnershipError` or occupied endpoint detected in logs.
  * *Meaning:* Endpoint port allocation collision or PID recycling conflict.

### Priority 2: Medium (Investigation at Summary)
* **`INFO-01: ORPHAN_PROFILE_DIRECTORY`**
  * *Trigger:* Profile directory in `output/indeed_profiles/` older than 15 minutes with no active process owner.
  * *Meaning:* Post-run disk cleanup failed due to permissions or delayed OS handle release.
* **`INFO-02: STALE_SINGLETON_LOCK`**
  * *Trigger:* Lingering `SingletonLock` symlink in profile directory without active process.

---

## 6. Evidence Retention & Log Locations

All validation artifacts are retained in dedicated, append-only logs for post-run forensic analysis:

| Artifact Path | Format | Purpose | Retention |
|:---|:---|:---|:---|
| `output/watchdog_validation_events.jsonl` | Structured JSONL | High-resolution audit log of every detected transition, timeout, orphan, or anomaly. | 30 days |
| `output/watchdog_validation_report.md` | Markdown Report | Human-readable comprehensive audit report generated by `watchdog_validation_report.py`. | 30 days |
| `output/hermes_cron.log` | Text Log | Standard execution output from cron and systemd timer runs. | Standard rotation |
| `output/indeed_profiles/` | Directories | Ephemeral Chrome browser profiles (auto-cleaned; retained only if process hangs). | Transient |
| `db/backups/applications.db.*` | SQLite DB | Cold backups created prior to remediation and major migrations. | Permanent |

---

## 7. Success Criteria (Go / No-Go Decision after 24h)

The post-deployment validation is deemed a **COMPLETE SUCCESS** if, after 24 hours (or at least 3 scheduled production runs):

1. **Zero Duplicate Submissions:** `hermes_duplicate_submissions_detected == 0`.
2. **Zero Submit-Risk Requeues:** Every submit-risk timeout (`SUBMIT_MAY_HAVE_DISPATCHED` or `CONFIRMATION_PENDING`) transitioned strictly to `submission_unconfirmed` and was never requeued or re-applied.
3. **Zero Orphan Browser Processes:** No lingering Chrome processes remain after scheduled runs finish.
4. **Clean Phase Monotonicity:** 100% of recorded phase transitions followed the valid state machine progression.
5. **Accurate Timeout Attribution:** Any timeout that occurred during pre-submit was attributed as `TIMEOUT` (retryable up to 3 attempts), while submit-risk timeouts were attributed as `SUBMISSION_UNCONFIRMED`.
6. **Zero Stale Locks:** No persistent `SingletonLock` files blocked subsequent browser launches.

---

## 8. Failure Criteria

Validation fails if any of the following occur during the observation period:

1. **Duplicate Dispatch:** A second application is dispatched to an employer for an already dispatched job.
2. **State Downgrade:** A successful application is downgraded from `submitted` to any failure state.
3. **Zombie Accumulation:** More than 3 orphan Chrome processes accumulate across cron runs.
4. **Hang Past Bound:** Any application run exceeds 7 minutes without watchdog escalation or termination.
5. **Database Lock Contention:** The monitor or applier encounters `sqlite3.OperationalError: database is locked`.

---

## 9. Rollback Criteria & Emergency Procedure

If any **Critical Failure (P0)** occurs during the 8–24 hour validation window:

### Trigger for Rollback:
- Occurrence of `CRIT-01` (Duplicate Submission) or `CRIT-02` (Submit-Risk Requeued).

### Emergency Rollback Procedure:
1. **Stop Automation Timers:**
   ```bash
   systemctl --user stop hermes.timer hermes-watch.timer hermes.service
   ```
2. **Seal Any In-Flight Applying Rows (Fail Closed):**
   ```bash
   python -c "
   import sqlite3
   conn = sqlite3.connect('db/applications.db')
   conn.execute(\"UPDATE jobs SET status = 'submission_unconfirmed', status_reason = 'emergency_freeze' WHERE status = 'applying'\")
   conn.commit()
   conn.close()
   "
   ```
3. **Terminate Lingering Browsers:**
   ```bash
   pkill -f "chrome-indeed-profile|indeed_profiles" || true
   ```
4. **Preserve Validation Evidence:**
   ```bash
   tar -czf "output/rollback_evidence_$(date +%Y%m%d_%H%M%S).tar.gz" output/watchdog_validation_events.jsonl output/hermes_cron.log db/applications.db
   ```
5. **Revert Application Code:**
   Revert code changes while strictly preserving the schema `phase` column and ensuring no unconfirmed jobs are exposed to blind retry.
