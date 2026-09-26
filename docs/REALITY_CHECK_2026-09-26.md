# Hermes Reality Check & Truth State Verification Report

**Date:** 2026-09-26  
**Auditor:** System Investigator (`@[system-investigator]`)  
**Repository:** `saralbanker/hermes`  
**Branch:** `overhaul-2026-09-23`  
**Git Baseline:** Commit `f8a447e baseline: verified scheduler, gmail, indeed, greenhouse and direct-form routing`  
**Deliverable Path:** `docs/REALITY_CHECK_2026-09-26.md`  

---

## 1. Executive Summary

A comprehensive, evidence-hierarchy audit was conducted across the Hermes codebase, SQLite database (`db/applications.db`), Gmail confirmation receipts, browser process tree, systemd services, and test suite. Every major capability and implementation claim was investigated against verifiable runtime and database proof.

### Summary of Classification Results

- **PROVEN (13 claims):**
  1. We Work Remotely (WWR) adapter existence and execution (`src/sources_wwr.py`).
  2. Arbeitnow adapter existence and fast 302 ATS resolution execution (`src/sources_arbeitnow.py`).
  3. Indeed capability for confirmed submissions (49 confirmed submissions in DB, 11 submitted today, triple verified with post-apply URLs, Indeed Applied history, and Gmail receipts).
  4. Greenhouse capability for confirmed submissions (1 real confirmed submission in DB: Cloudflare Job 4410, verified with screenshot, DB row, and Cloudflare confirmation email).
  5. Ashby handling behavior matches reality (safely disabled/short-circuited with `blocked_antibot` due to Cloudflare anti-bot bot-risk checks).
  6. Gmail watcher classification accuracy (repaired classifier eliminated BookMyShow spam, accurately detects Indeed receipts, runs on schedule every 10 min scanning 118 emails with 0 errors).
  7. Browser infrastructure stability (Xvfb process-killing bug resolved; runs headless on display `:99`).
  8. Xvfb lifecycle stability (`ensure_virtual_display()` is strictly idempotent and validates X11 socket liveness).
  9. Chrome cleanup correctness (`cleanup_orphan_browsers()` protects active Hermes PID, its descendants, and Xvfb PID; SingletonLock removed only when owning PID is dead).
  10. Attempt cap enforcement (`attempts < 3` max retry cap enforced; retryable vs terminal states distinguished).
  11. Recovery logic correctness (crashes/interruptions leave SQLite state intact; resumes from `tailored` or `scored`).
  12. Duplicate prevention correctness (URL uniqueness + `dedupe_key` cross-board collapsing + pre-apply checks).
  13. Daily cap enforcement (`daily_limits` table increments and halts application when `total_count >= 100`).

- **PARTIALLY PROVEN (4 claims):**
  1. Continuous queue existence and automatic function (Code exists in `src/pipeline.py` and service file exists in `scripts/hermes-continuous.service`, but the service is **inactive/disabled**; the live system runs 3x daily batch timers via `hermes.timer`).
  2. 250–500 reserve logic existence and automatic function (Code block exists in `pipeline.py`, but has a logical defect: counts 756 dead jobs that scored < 6.5 as active reserve, so `total_reserve` permanently evaluates to ~800, never triggering automatic reserve replenishment).
  3. Fast ATS URL resolution (Fast HTTP 302 probe exists for Arbeitnow and WWR RSS parsing, but does NOT resolve general third-party redirect aggregator walls like RemoteOK, Himalayas, or Jobicy).
  4. Full test suite claims (347 / 347 tests pass in 13.87s, but 100% of these tests use mocks for external websites, networks, and browsers; they do not prove external portal compatibility).

- **UNPROVEN / FALSE (3 claims):**
  1. **Direct Forms real confirmed submission:** **FALSE / UNPROVEN.** Exactly 0 submissions have ever been made via Direct Forms in the history of the repository (3 attempts ever made: 2 `form_changed`, 1 `expired`).
  2. **Lever real confirmed submission:** **FALSE / UNPROVEN.** Exactly 0 submissions have ever been made to Lever in the history of the repository (1 attempt ever made: failed with `captcha_required`).
  3. **100 applications per day production-ready path:** **FALSE.** Hermes has never achieved more than 23 submissions in a single day (peak was 23 on 2026-06-24; today peak was 11). The system is throttled by severe qualified candidate job supply starvation (~10–15 qualifying roles/day in India across all working channels combined).

---

## 2. Evidence Hierarchy Applied

In resolving all claims, the following strict hierarchy was enforced (higher rank overrides lower rank):
1. **Live runtime behavior** (process inspection, live execution, systemd status)
2. **SQLite database state** (`db/applications.db` tables `jobs`, `responses`, `daily_limits`)
3. **Real submission evidence** (live post-apply confirmation URLs, screenshots)
4. **Gmail confirmations** (IMAP confirmation receipts from employers and platforms)
5. **Application history** (platform-native applied dashboards)
6. **Current source code** (uncommitted and tracked code in `src/`)
7. **Automated tests** (pytest test runs and assertions)
8. **Logs** (`output/hermes_cron.log`, `journalctl`)
9. **Documentation** (`docs/*.md`)
10. **Previous AI reports** (unverified agent summaries)

---

## 3. Detailed Claims Verification

### Claim 1: WWR Adapter Existence and Successful Execution
- **Claim:** Hermes includes an operational We Work Remotely (WWR) discovery adapter that parses RSS feeds and extracts direct ATS links.
- **Status:** **PROVEN**
- **Evidence:** 
  - Code exists in `src/sources_wwr.py` (132 lines).
  - Integrated into `src/discover.py` via `_scrape_wwr` in `SCRAPERS` map (line 395).
  - Enabled in `config.yaml` (`search.boards: - wwr`).
  - Unit tests in `tests/test_sources_new.py::test_parse_wwr_rss` pass.
- **Files:** `src/sources_wwr.py`, `src/discover.py`, `config.yaml`, `tests/test_sources_new.py`.
- **Runtime Proof:** Direct live execution of `fetch_wwr_jobs(cfg)` returned 63 fresh remote engineering jobs in 4.2 seconds. Database inspection reveals **61 WWR jobs** recorded in `db/applications.db` (status: 36 scored, 20 filtered, 2 blocked_antibot, 2 unsupported_channel, 1 tailored).
- **Reasoning:** Meets all criteria: tracked code, working live execution, and verified rows in SQLite.

---

### Claim 2: Arbeitnow Adapter Existence and Successful Execution
- **Claim:** Hermes includes an Arbeitnow adapter that queries the public REST API and performs fast HTTP 302 ATS detection.
- **Status:** **PROVEN**
- **Evidence:**
  - Code exists in `src/sources_arbeitnow.py` (118 lines).
  - Integrated into `src/discover.py` via `_scrape_arbeitnow` in `SCRAPERS` map (line 396).
  - Enabled in `config.yaml` (`search.boards: - arbeitnow`).
  - Unit tests in `tests/test_sources_new.py::test_arbeitnow_engineering_keyword_filter` and `test_arbeitnow_fast_resolve` pass.
- **Files:** `src/sources_arbeitnow.py`, `src/discover.py`, `config.yaml`, `tests/test_sources_new.py`.
- **Runtime Proof:** Live invocation of `fetch_arbeitnow_jobs(cfg)` executed in 3.6 seconds, fetching 11 remote engineering postings and resolving employers (e.g. Planet Labs, Pure Storage) directly to Greenhouse ATS. Database contains **15 Arbeitnow jobs** in `db/applications.db` (9 filtered, 6 scored).
- **Reasoning:** Meets all criteria: clean code, fast pre-flight resolution without launching Chrome, and active rows in SQLite.

---

### Claim 3: Continuous Queue Existence and Automatic Function
- **Claim:** Hermes operates a continuous 24/7 background worker queue that automatically processes discovery, scoring, tailoring, and applications in a continuous loop.
- **Status:** **PARTIALLY PROVEN**
- **Evidence:**
  - Implementation exists in `src/pipeline.py:run_continuous()` (lines 155–243).
  - CLI flag `--continuous` handled in `pipeline.py` and `scripts/run_hermes.sh`.
  - Systemd unit exists in `scripts/hermes-continuous.service` and is installed in `/home/virus/.config/systemd/user/hermes-continuous.service`.
- **Files:** `src/pipeline.py`, `scripts/run_hermes.sh`, `scripts/hermes-continuous.service`.
- **Runtime Proof:** Live systemd user status check reveals:
  `hermes-continuous.service: inactive (dead); disabled`.
  The active production service running on the host is `hermes.timer`, which triggers `hermes.service` (`scripts/run_hermes.sh` without `--continuous`) in **scheduled batch mode** at 08:00, 13:00, and 19:00 IST.
- **Reasoning:** The continuous queue code is written, but it does **not** function automatically in the live production environment. The host is actively running scheduled batch timers, not the continuous service.

---

### Claim 4: 250–500 Reserve Logic Existence and Automatic Function
- **Claim:** The system maintains an automatic, persistent reserve pool of 250–500 eligible jobs across discovered, scored, and tailored stages.
- **Status:** **PARTIALLY PROVEN / FUNCTIONALLY FLAWED**
- **Evidence:**
  - Code block exists in `src/pipeline.py:run_continuous` (lines 184–193).
- **Files:** `src/pipeline.py`.
- **Runtime Proof:**
  - Code inspection shows a fixed target `RESERVE_TARGET = 300` (not a 250–500 range).
  - Calculation flaw: `total_reserve = len(discovered_jobs) + len(scored_jobs) + len(tailored_jobs)`.
  - In `db/applications.db`, there are **795 jobs** with `status='scored'`. However, **756 of those 795 jobs scored < 6.5** (failed the apply threshold).
  - Because Hermes leaves rejected scored jobs with `status='scored'`, `len(scored_jobs)` always returns ~795.
  - Thus, `total_reserve < RESERVE_TARGET` (`795 < 300`) evaluates to `False` permanently. Automatic reserve-triggered discovery will **never** fire; discovery in continuous mode only triggers via the 2-hour elapsed time fallback (`now - last_discover_time > DISCOVER_INTERVAL`).
- **Reasoning:** While the code exists, it contains a critical counting bug that breaks the intended automatic replenishment logic. Furthermore, it is only invoked inside `run_continuous()`, which is currently disabled.

---

### Claim 5: Indeed Capability for Confirmed Submissions
- **Claim:** Indeed SmartApply automation is fully production-ready and executes verified end-to-end applications.
- **Status:** **PROVEN**
- **Evidence:**
  - Submissions tracked in `db/applications.db`: **49 confirmed submissions** out of 50 total in the database.
  - Submissions today (2026-09-26): **11 confirmed submissions** (Job IDs 8469, 8483, 8491, 8496, 8639, 8640, 8643, 8644, 8645, 8646, 8653).
  - External proof: Triple verified via:
    1. Post-apply confirmation text in DB: `'''Your application has been submitted''' @ https://smartapply.indeed.com/...`
    2. Real confirmation emails received in Gmail from `indeedapply@indeed.com` (26 emails present in `responses` table with classification `ack`).
    3. Live execution log from today's 19:02 run confirming 5 submissions in 261 seconds.
- **Files:** `src/indeed_apply.py`, `output/indeed_session.json`, `output/chrome-indeed-profile/`.
- **Runtime Proof:** Real-time log from 2026-09-26 19:15:08: `[apply] Done — {'form_changed': 1, '_seconds': 261, 'submitted': 5}`.
- **Reasoning:** Indeed is the primary, robustly working channel in the entire repository.

---

### Claim 6: Greenhouse Capability for Confirmed Submissions
- **Claim:** Greenhouse ATS automation is fully production-ready and executes verified end-to-end applications.
- **Status:** **PROVEN**
- **Evidence:**
  - Submissions tracked in `db/applications.db`: Exactly **1 confirmed submission** (Job ID 4410, Cloudflare, `applied_at: 2026-09-25T04:02:06`).
  - Evidence string in DB: `Thank you for applying`.
  - Screenshot verification: File `screenshots/livetest-real-cloudflare-software-engineer.png` (32,517 bytes) exists on disk.
  - Employer confirmation receipt: Email in `responses` table: `Cloudflare Recruiting | Application Received - Software Engineer` from `no-reply@cloudflare.com` at `2026-09-24T22:33:06+00:00`.
  - OTP resolution: Gmail IMAP fetched security code at `2026-09-24T22:31:51+00:00`.
  - Automated tests: 75 unit/integration tests passing in `tests/test_ats.py`.
- **Files:** `src/ats_apply.py`, `src/otp_resolver.py`, `tests/test_ats.py`, `screenshots/livetest-real-cloudflare-software-engineer.png`.
- **Runtime Proof:** Verified by screenshot, database record, and Gmail confirmation email.
- **Reasoning:** Meets all requirements for proven capability. Note however that submission volume is low (1 submission total) due to candidate geographic filtering discarding most US/EU Greenhouse postings.

---

### Claim 7: Direct Forms Real Confirmed Submission
- **Claim:** Direct Forms automation has achieved confirmed production submissions.
- **Status:** **FALSE / UNPROVEN**
- **Evidence:**
  - Query: `SELECT count(*) FROM jobs WHERE (apply_channel='direct' OR apply_channel='direct_form') AND status='submitted';` returns **0**.
  - Exactly 3 jobs have ever reached `apply_channel='direct'`:
    - Job 2115 (Ahead): `form_changed: application form structure not recognized`
    - Job 8069 (Leader IT): `form_changed: no Next/Submit control found on this step`
    - Job 8468 (Avalara): `expired: posting closed or not found`
- **Files:** `src/direct_form.py`, `tests/test_direct_form.py`.
- **Runtime Proof:** Zero rows in `db/applications.db` have `status='submitted'` for direct forms. Zero confirmation emails or screenshots exist for direct forms.
- **Reasoning:** While `src/direct_form.py` is implemented and unit tested (32 passing tests), it has **never** achieved a confirmed real-world application submission.

---

### Claim 8: Lever Real Confirmed Submission
- **Claim:** Lever ATS automation has achieved confirmed production submissions.
- **Status:** **FALSE / UNPROVEN**
- **Evidence:**
  - Query: `SELECT count(*) FROM jobs WHERE (apply_channel='lever' OR ats_meta LIKE '%lever%' OR url LIKE '%lever.co%') AND status='submitted';` returns **0**.
  - Total Lever jobs in DB: 138 (120 filtered, 14 expired, 3 scored, 1 captcha_required).
  - Only 1 Lever job has ever been attempted: Job 8581 (HighLevel, `Senior SDE - Platform`), which failed with `captcha_required: captcha challenge visible`.
- **Files:** `src/ats_apply.py`, `tests/test_ats.py`.
- **Runtime Proof:** Zero Lever submissions exist in the database or Gmail.
- **Reasoning:** Lever automation is unproven in production. The single real-world attempt was blocked by a CAPTCHA challenge.

---

### Claim 9: Ashby Handling Behavior vs Documentation
- **Claim:** Ashby automation is safely contained and disabled due to Cloudflare bot-risk checks.
- **Status:** **PROVEN**
- **Evidence:**
  - Documentation in `FINAL_PRODUCTION_STATE.md` and `EXECUTION_STATUS.md` states Ashby is disabled/contained with `blocked_antibot`.
  - Code in `src/apply.py` (lines 175–176):
    ```python
    if channel == S.CH_ASHBY:
        return S.ApplyResult(S.BLOCKED_ANTIBOT, "ashby disabled: platform anti-bot blocks automated submissions")
    ```
  - Code in `src/redirect_resolver.py` (lines 271–273): Drops Ashby URLs immediately with `blocked_antibot:ashby anti-bot prevents automated submission`.
  - Database verification: 3 Ashby jobs marked `blocked_antibot` (e.g. Job 7922 Notion).
- **Files:** `src/apply.py`, `src/redirect_resolver.py`.
- **Runtime Proof:** Verified in funnel log: `Sticker Mule (WWR): ashby disabled (platform anti-bot, contained in 0.1s)`.
- **Reasoning:** Reality strictly matches the documented containment behavior.

---

### Claim 10: Gmail Watcher Classification Accuracy
- **Claim:** The Gmail response watcher accurately classifies employer responses, rejects non-job notifications, and extracts interviews.
- **Status:** **PROVEN**
- **Evidence:**
  - Classification logic updated in `src/response_watcher.py`: generic strings like `no-reply` removed from `_ACK_PATTERNS`; marketing emails (BookMyShow) classified as `other`; Indeed application receipts classified as `ack`.
  - Unit tests in `tests/test_response_watcher.py` (11 tests) pass completely.
  - SQLite database state: `responses` table contains 204 `other`, 27 `ack`, 2 `rejection`, 0 false positive alerts.
  - Live systemd service `hermes-watch.service` ran at 22:31:43 IST: scanned 118 emails with 0 errors.
- **Files:** `src/response_watcher.py`, `tests/test_response_watcher.py`.
- **Runtime Proof:** Systemd journal: `python3[602900]: [response_watcher] scanned=118 new=0 acks=0 rejections=0 positive=0 errors=0`.
- **Reasoning:** The classification rules and database state confirm accurate, clean operation without noisy false alerts.

---

### Claim 11: Browser Infrastructure Stability
- **Claim:** Browser automation runs stably in the background without crashing displays or leaking ports.
- **Status:** **PROVEN**
- **Evidence:**
  - Virtual display `:99` created and verified via `is_display_alive(':99') -> True`.
  - Real run at 19:02 executed 6 browser application attempts sequentially without a single `BrowserConnectError` or `DisplayUnavailable` crash.
- **Files:** `src/display.py`, `src/indeed_apply.py`, `src/ats_apply.py`.
- **Runtime Proof:** All 5 submitted jobs today succeeded via live Chrome on `:99`.
- **Reasoning:** The previous browser launch failure mode has been eliminated.

---

### Claim 12: Xvfb Lifecycle Stability
- **Claim:** `ensure_virtual_display()` is idempotent and no longer kills its own Xvfb instance.
- **Status:** **PROVEN**
- **Evidence:**
  - In `src/display.py`, `ensure_virtual_display()` checks `_proc.poll() is None` and validates `is_display_alive(current_disp)`.
  - Running `ensure_virtual_display()` repeatedly returns `:99` immediately without calling cleanup.
- **Files:** `src/display.py`, `tests/test_apply_engine.py`, `tests/test_resilience.py`.
- **Runtime Proof:** Verified via live interactive Python test: display remained active (`alive: True`) across repeated invocations and cleanup calls.
- **Reasoning:** Idempotent lifecycle verified at runtime and by unit tests.

---

### Claim 13: Chrome Cleanup Correctness
- **Claim:** Orphan browser cleanup safely terminates zombie Chrome processes without killing Hermes itself or its child processes.
- **Status:** **PROVEN**
- **Evidence:**
  - In `src/display.py:cleanup_orphan_browsers()`, `active_hermes_pids = {my_pid} | my_descendants | {_proc.pid}` is explicitly excluded from termination.
  - `SingletonLock` is only deleted if the owning PID is confirmed non-existent via `psutil.pid_exists(owning_pid)`.
- **Files:** `src/display.py`, `tests/test_resilience.py`.
- **Runtime Proof:** Interactive test of `cleanup_orphan_browsers()` executed while Xvfb `:99` was running resulted in `{'chrome_killed': 0, 'locks_removed': 0, 'xvfb_killed': 0}` and display remained fully operational.
- **Reasoning:** Verified by code inspection and live runtime execution.

---

### Claim 14: Attempt Cap Enforcement
- **Claim:** Applications are limited to a maximum of 3 attempts before being marked terminally failed.
- **Status:** **PROVEN**
- **Evidence:**
  - Code in `src/apply.py`: `retry = result.state in S.RETRYABLE and attempts < S.MAX_ATTEMPTS`.
  - `S.MAX_ATTEMPTS = 3` defined in `src/states.py`.
  - Database inspection shows jobs with `attempts = 3` are transitioned to terminal states (`failed`, `captcha_required`, `unsupported_channel`, `form_changed`).
- **Files:** `src/apply.py`, `src/states.py`, `tests/test_apply_engine.py`.
- **Runtime Proof:** Database query confirms zero recent jobs exceeded 3 attempts.
- **Reasoning:** Attempt capping is actively enforced by both application engine and SQLite state machine.

---

### Claim 15: Recovery Logic Correctness
- **Claim:** System crashes or interruptions preserve pipeline progress in SQLite and resume cleanly on the next run.
- **Status:** **PROVEN**
- **Evidence:**
  - All status updates in `src/discover.py`, `src/score.py`, `src/tailor.py`, and `src/apply.py` are committed immediately to `db/applications.db`.
  - Next run selects unprocessed jobs (`status IN ('discovered', 'scored', 'tailored')`).
  - Unit tests in `tests/test_resilience.py` pass.
- **Files:** `src/db.py`, `src/pipeline.py`, `tests/test_resilience.py`.
- **Runtime Proof:** Pipeline runs resumed seamlessly across multiple scheduled executions today without duplicate work.
- **Reasoning:** Atomic row-level database updates provide reliable crash recovery.

---

### Claim 16: Duplicate Prevention Correctness
- **Claim:** The system prevents duplicate applications to the same role across different job boards.
- **Status:** **PROVEN**
- **Evidence:**
  - URL uniqueness enforced by `CREATE TABLE jobs (url TEXT UNIQUE NOT NULL ...)`.
  - Normalized deduplication key `dedupe_key = make_dedupe_key(company, title)` indexed via `idx_jobs_dedupe`.
  - Discovery skips cross-board duplicates before LLM scoring: `seen_keys = get_all_dedupe_keys()`.
  - In the 19:02 run, **28 duplicate listings were skipped** before scoring.
  - Application checks `already_applied_key(key)` before launching the browser.
- **Files:** `src/db.py`, `src/discover.py`, `src/apply.py`.
- **Runtime Proof:** Verified in run logs: `[discover] Saved 12 eligible jobs... 28 skipped (cross-board duplicate)`.
- **Reasoning:** Three-tier deduplication (URL, discovery cross-board, and pre-apply DB query) operates correctly.

---

### Claim 17: Daily Cap Enforcement
- **Claim:** Applications are strictly capped at 100 per day.
- **Status:** **PROVEN**
- **Evidence:**
  - `daily_limits` table tracks `date`, `linkedin_count`, `other_count`, `total_count`.
  - `src/apply.py` checks `remaining_today()` and halts when `total_remaining <= 0`.
  - Unit test `tests/test_apply_engine.py::test_daily_cap_blocks_run` passes.
- **Files:** `src/db.py`, `src/apply.py`, `tests/test_apply_engine.py`.
- **Runtime Proof:** Database query confirms `daily_limits` contains rows for all active days (e.g. 2026-09-26: `total_count = 11`).
- **Reasoning:** Daily limit enforcement is fully implemented, tested, and operational.

---

### Claim 18: Existence of All Claimed Files
- **Claim:** All claimed adapters, test suites, scripts, and documentation files exist.
- **Status:** **PROVEN (with Working Tree Discrepancy)**
- **Evidence:**
  - Every claimed file exists on the local filesystem:
    - `src/sources_wwr.py` (exists)
    - `src/sources_arbeitnow.py` (exists)
    - `scripts/hermes-continuous.service` (exists)
    - `tests/test_sources_new.py` (exists)
    - `docs/CURRENT_TRUTH_STATE(2026-09-26).MD` (exists)
    - `docs/EXECUTION_STATUS.md` (exists)
    - `docs/FINAL_PRODUCTION_STATE.md` (exists)
    - `docs/REPOSITORY_REALITY_AUDIT_2026-09-26.md` (exists)
    - `docs/ROADMAP.md` (exists)
    - `docs/SUPPLY_FAN_IN_DESIGN.md` (exists)
    - `docs/SYSTEM_ARCHITECTURE.md` (exists)
    - `docs/imp/PHASE1_PLAN.md` (exists)
    - `passive-100-daily-plan.md` (exists)
- **Critical Caveat:** While all files exist, **18 tracked files are modified uncommitted** and **14 files/directories are untracked** in Git. None of the recent adapter or architecture work has been committed to branch `overhaul-2026-09-23`.
- **Reasoning:** Files physically exist on disk, but the working copy is dirty and uncommitted.

---

### Claim 19: Existence of All Claimed Tests
- **Claim:** Repository contains 347 passing automated tests covering all modules.
- **Status:** **PROVEN**
- **Evidence:**
  - Running `pytest` executes exactly **347 collected tests** across 17 test files in **13.87 seconds** with **100% pass rate (347 passed, 0 failed)**.
- **Files:** `tests/test_*.py`.
- **Runtime Proof:** Full pytest invocation output:
  `collected 347 items ... ================= 347 passed in 13.87s =================`
- **Reasoning:** The test suite count and execution claims are completely factual and verified.

---

### Claim 20: Existence of All Claimed Documentation
- **Claim:** Documentation files matching previous reports exist in `docs/`.
- **Status:** **PROVEN**
- **Evidence:**
  - All requested documentation files exist in `docs/` and root:
    - `docs/CURRENT_TRUTH_STATE(2026-09-26).MD`
    - `docs/EXECUTION_STATUS.md`
    - `docs/FINAL_PRODUCTION_STATE.md`
    - `docs/REPOSITORY_REALITY_AUDIT_2026-09-26.md`
    - `docs/ROADMAP.md`
    - `docs/SUPPLY_FAN_IN_DESIGN.md`
    - `docs/SYSTEM_ARCHITECTURE.md`
    - `docs/imp/PHASE1_PLAN.md`
    - `passive-100-daily-plan.md`
- **Reasoning:** All documentation exists as claimed.

---

## 4. Runtime Findings

1. **Active Execution Mode:**
   - The host system runs Hermes via **systemd user timers** (`hermes.timer` at 08:00, 13:00, 19:00 IST), NOT continuous mode.
   - Response monitoring runs via `hermes-watch.timer` every 10 minutes.
   - `hermes-continuous.service` is present in systemd config but is currently `inactive (dead)` and `disabled`.

2. **Last Scheduled Run (19:02 IST, 2026-09-26):**
   - Execution duration: 12 minutes 48 seconds.
   - Discovery: Scraped 4,368 raw jobs; 4,319 were already in DB; 12 eligible saved; 28 duplicates skipped.
   - Scoring: 12 jobs evaluated by local Ollama (`qwen3:4b` + `nomic-embed-text`); 6 passed threshold (≥ 6.5).
   - Tailoring: 6 targeted cover letters generated from verified facts.
   - Application: 5 submitted via Indeed on virtual display `:99`; 1 encountered `form_changed`.
   - Result: Clean exit code 0 (`run finished OK`).

3. **Memory & CPU Profile:**
   - Memory peak during application: ~2.8 GB (headful Chrome on Xvfb).
   - CPU utilization: ~38 seconds CPU time over 767 seconds wall clock time.

---

## 5. Database Findings (`db/applications.db`)

### Status Breakdown (Total 8,690 jobs in DB)
| Status | Job Count | Percentage | Description |
|---|---|---|---|
| `filtered` | 5,571 | 64.1% | Discarded by location, seniority, or salary filters |
| `expired` | 1,436 | 16.5% | Job listing closed or 404 |
| `scored` | 795 | 9.1% | Scored by LLM (756 scored < 6.5; 39 scored ≥ 6.5) |
| `skipped` | 728 | 8.4% | Cross-board duplicate collapsed |
| `submitted` | **50** | **0.6%** | **Confirmed submitted applications** |
| `unsupported_channel` | 48 | 0.6% | External account required or unsupported portal |
| `form_changed` | 42 | 0.5% | Complex SPA layout or missing Next/Submit control |
| `submission_unconfirmed` | 9 | 0.1% | Post-apply confirmation text not matched |
| `failed` | 4 | <0.1% | Max retries exceeded |
| `blocked_antibot` | 3 | <0.1% | Cloudflare Turnstile / anti-bot block (Ashby) |
| `captcha_required` | 1 | <0.1% | CAPTCHA challenge displayed (Lever) |
| `tailored` | 1 | <0.1% | Tailored cover letter ready in queue |

### Historical Submissions by Date
| Date | Submitted Applications | Notes |
|---|---|---|
| 2026-06-24 | 23 | Legacy initial batch (Indeed) |
| 2026-09-23 | 4 | Overhaul branch baseline (Indeed) |
| 2026-09-24 | 10 | Includes 1 Greenhouse (Cloudflare) + 9 Indeed |
| 2026-09-25 | 2 | Indeed |
| 2026-09-26 (Today) | **11** | **Indeed (6 at 18:04–18:10; 5 at 19:10–19:15)** |
| **Total** | **50** | **49 Indeed, 1 Greenhouse, 0 Lever, 0 Direct** |

---

## 6. Submission Evidence Audit

| Channel | Confirmed DB Rows | External Verification Evidence |
|---|---|---|
| **Indeed** | **49** | - Post-apply URL: `https://smartapply.indeed.com/...`<br>- Native Indeed "Applied" dashboard history<br>- 26 confirmation emails from `indeedapply@indeed.com` in Gmail IMAP |
| **Greenhouse** | **1** | - Job 4410 (Cloudflare, `Software Engineer`)<br>- Screenshot: `screenshots/livetest-real-cloudflare-software-engineer.png`<br>- Gmail OTP retrieval + confirmation email from `no-reply@cloudflare.com` |
| **Lever** | **0** | **None.** 0 submitted rows in DB. 1 attempt failed with `captcha_required`. |
| **Direct Forms** | **0** | **None.** 0 submitted rows in DB. 3 attempts failed with `form_changed` or `expired`. |
| **Ashby** | **0** | **None.** 3 jobs blocked by Cloudflare bot-risk detection (`blocked_antibot`). |

---

## 7. Browser Infrastructure Findings

1. **Virtual Display Stability:**
   - Previous fatal bug (`display.py` killing its own Xvfb process) has been completely resolved.
   - `ensure_virtual_display()` checks PID liveness and reuse without teardown.
   - Tested under consecutive headful Chrome launches with zero disconnects.

2. **Process Cleanup & Locks:**
   - `cleanup_orphan_browsers()` protects active process tree and Xvfb PID.
   - Stale lock unlinking verified: only unlinks when target PID is dead in `psutil`.

---

## 8. Queue Findings

1. **Queue Composition:**
   - Active tailored queue: 1 job (`status='tailored'`).
   - Qualified scored reserve (`score >= 6.5`): **39 jobs**.
   - Dead scored reserve (`score < 6.5`): **756 jobs**.
   - Discovered queue: 0 jobs.

2. **Continuous Queue Status:**
   - Implementation exists in `pipeline.py` but is **not active in production**.
   - Counting defect in reserve logic treats the 756 dead jobs as eligible reserve, preventing automatic discovery triggering.

---

## 9. Channel Health Matrix

| Channel | Status | Working? | Evidence | Major Blockers |
|---|---|---|---|---|
| **Indeed** | Production Proven | **YES** | 49 submissions (11 today) | Daily new job volume in target roles (~20–40/day) |
| **Greenhouse** | Production Proven | **YES** | 1 submission + 75 tests passing | Strict candidate geo-filtering eliminates >90% of US/EU roles |
| **Arbeitnow** | Production Proven (Discovery) | **YES** | 15 discovered, resolves to Greenhouse | Modest daily job volume (~10–20 engineering roles/day) |
| **We Work Remotely** | Production Proven (Discovery) | **YES** | 61 discovered in DB | Geolocked postings enforce account wall; high senior ratio |
| **Lever** | Ready (Unproven) | **NO** (0 submissions) | 0 submitted rows; 1 attempt hit CAPTCHA | Cloudflare Turnstile / CAPTCHA walls; low India volume |
| **Direct Forms** | Supported Subset (Unproven) | **NO** (0 submissions) | 0 submitted rows; 2 `form_changed` | Custom SPA employer portals; missing standard submit buttons |
| **Ashby** | Blocked / Contained | **NO** | 3 `blocked_antibot` | Cloudflare bot-risk scoring blocks automated sessions |
| **Aggregator Portals** | Blocked | **NO** | 48 `unsupported_channel` | Mandatory user login walls (Naukri, Foundit, Himalayas, etc.) |

---

## 10. Current Bottlenecks

Why is Hermes not submitting more applications?

1. **Candidate Match Supply Starvation (Primary Bottleneck):**
   - The candidate profile is an early-career engineer based in India (Remote Worldwide or Ahmedabad).
   - ATS platforms (Greenhouse, Lever, Ashby) predominantly list US/EU-only roles. Over 90% of scraped ATS listings are discarded immediately by `location_filter`.
   - After location filtering, seniority filters discard roles requiring > 2 years of experience.
   - After scoring, only ~20% of eligible jobs pass the `score >= 6.5` threshold.
   - Net yield: Out of 4,400+ scraped jobs per run, **fewer than 15 fresh jobs** are eligible and qualified.

2. **Single High-Yield Channel Reliance (Indeed):**
   - 98% of all confirmed submissions in Hermes history (49/50) come from Indeed SmartApply.
   - When Indeed runs out of new postings for the target search queries, the pipeline starves.

3. **Aggregator Sign-Up / Login Walls:**
   - 3rd-party aggregators (RemoteOK, Himalayas, Jobicy, WWR) increasingly place application redirect links behind applicant registration walls (`/sign-up` or `/login`).
   - Fast resolution drops these cleanly, but they cannot be converted into applications.

4. **Continuous Service is Disabled:**
   - The system only runs 3 times per day for ~12 minutes each. Even at 100% success on queued jobs, 3 runs × 5 jobs = 15 applications/day.

---

## 11. Current Realistic Daily Capacity

- **Current Live Reality (Batch Timers @ 08:00, 13:00, 19:00):**
  - Average yield per run: 3–5 applications (constrained by fresh supply).
  - **Realistic Daily Output:** **10 to 15 confirmed applications per day.**
  - **Proven Today (2026-09-26):** **11 confirmed applications.**

- **Theoretical Capacity (Engine Throughput without Supply Bottleneck):**
  - Submission cycle time per application: ~38 seconds.
  - 100 applications = 3,800 seconds (~63 minutes) total browser execution time.
  - The automation engine can easily execute 100 applications/day if 100 qualified, non-walled jobs exist.

---

## 12. Remaining Work Before 100 Confirmed Applications Per Day

To realistically reach and sustain **100 confirmed applications per day**, the following specific technical items must be completed:

1. **Commit the Working Tree (P0):**
   - Commit the uncommitted fixes (`sources_wwr.py`, `sources_arbeitnow.py`, `display.py`, `apply.py`, `response_watcher.py`, `tests/test_sources_new.py`) to Git.

2. **Fix the Reserve Counting Bug in `src/pipeline.py` (P0):**
   - Change `scored_jobs = get_jobs_by_status("scored")` in the reserve calculation to count only jobs that meet the threshold:
     ```python
     qualifying_scored = [j for j in get_jobs_by_status("scored") if (j.get("score") or 0) >= 6.5]
     ```
   - Transition rejected scored jobs (`score < 6.5`) to a terminal state (`rejected_low_score`) so they do not pollute active queue counts.

3. **Expand Candidate Matching Job Supply (P0 - The Critical Blocker):**
   - To yield 100 applications at a 20% score-pass rate and 50% location-pass rate, Hermes needs **~1,000 fresh raw jobs per day matching India/Remote**.
   - Add additional open job boards without registration walls:
     - Remote.co RSS feeds
     - Jobspresso RSS
     - Working Nomads API
     - Expand Indeed search queries from 14 to 30 roles (add Python Developer, Django, Flask, FastAPI, Next.js, Frontend React, Cloud Engineer, Automation Engineer).

4. **Activate Continuous Queue Mode in Production (P1):**
   - Switch systemd from `hermes.timer` (batch) to `hermes-continuous.service` (24/7 worker).
   - Ensure continuous worker drains tailored jobs in steady batches of 5–10 every 30 minutes throughout the 24-hour cycle.

5. **Prove Direct Forms on Simple Careers Pages (P1):**
   - Identify company career sites with standard single-page forms (non-SPA) that don't enforce login walls, and run live verification to prove the first real Direct Form submission.

6. **Implement CAPTCHA Alerting / Solver Strategy for Lever (P2):**
   - Since Lever frequently serves CAPTCHAs, evaluate headless-friendly solving hooks or desktop interactive solve prompts (`notify-send`) when a high-value (score ≥ 8.5) role encounters a challenge.
