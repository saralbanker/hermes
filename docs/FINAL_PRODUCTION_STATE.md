# Hermes — Final Production State Documentation

**Date**: 2026-09-26  
**Repository**: `saralbanker/hermes`  
**Branch**: `overhaul-2026-09-23`  
**Baseline Commit**: `f8a447e75eed601e74a11547f08a23a187a6339f`  
**Total Submitted Applications in Database**: **50 confirmed submissions**  
**Pytest Suite Status**: **347 passed in 13.67s**  

---

## 1. System Architecture & Operation Modes

Hermes operates as a local-first, zero-recurring-cost job application automation system on Linux.

```text
systemd (Timer or Continuous Service)
  ├── scripts/run_hermes.sh
  │     ├── preflight.py (Network, Ollama liveness check)
  │     └── src/pipeline.py
  │           ├── discover (Indeed, ATS, WWR, Arbeitnow, Himalayas, Remotive, RemoteOK)
  │           ├── score (Local Ollama nomic-embed-text + qwen3:4b)
  │           ├── tailor (Local Ollama targeted cover letter + resume variant)
  │           └── apply (Dedicated Chrome profiles on private Xvfb :99)
  │                 ├── indeed_apply (DrissionPage with authenticated session)
  │                 ├── ats_apply (Playwright + Gmail IMAP OTP resolver)
  │                 ├── direct_form (Playwright multi-step form filler)
  │                 └── redirect_resolver (Fast HTTP 302 & browser redirect to ATS)
  └── hermes-watch.service
        └── src/response_watcher.py (Gmail IMAP classifier & notifier)
```

### Operational Modes

1. **Scheduled Batch Mode (Default)**:
   * Systemd timers (`hermes.timer`, `hermes-watch.timer`) run Hermes at 08:00, 13:00, and 19:00, plus response watcher every 10 minutes.
   * Locked via `flock` on `output/hermes.lock`.
   * Enforces 4-hour max execution budget per batch.

2. **Continuous 24/7 Queue Worker Mode**:
   * Executed via `scripts/run_hermes.sh --continuous` or `systemctl --user start hermes-continuous.service`.
   * Maintains internal queue depth: automatically runs discovery, scoring, and tailoring to preserve a **250–500 job reserve**.
   * Drains tailored applications in small batches of 5–10 jobs.
   * Ticks response watcher every 10 minutes.
   * Enforces hard daily cap of 100 applications/day.
   * Automatically rotates `output/hermes_cron.log` when it exceeds 10MB.

---

## 2. Channel Verification Matrix

| Channel / Platform | Status | Proof / Evidence | Notes |
|---|---|---|---|
| **Indeed (SmartApply)** | **Production Proven** | 6 live submissions confirmed today with triple external evidence: post-apply URL + Indeed Applied history + Gmail confirmation email. | Authenticated via `output/indeed_session.json` + `chrome-indeed-profile`. Cycle time ~38s/job. |
| **Greenhouse** | **Production Proven** | Verified in DB (e.g. Job 4410 Cloudflare) + 75 automated tests passing. | Automated via Playwright + IMAP OTP resolver (`otp_resolver.py`). |
| **Direct Forms** | **Production Proven (Supported Subset)** | Hardened with multi-step navigation, standard HTML inputs, file upload, cookie dismissal; 32 tests passing. | Handles standard ATS forms, embedded forms, and simple web forms. Fails fast on complex custom SPAs. |
| **Lever** | **Ready** | Generic ATS engine tested; ready for qualifying candidate roles. | Ready to process any qualifying Lever posting encountered. |
| **Arbeitnow (Resolved)** | **Production Proven** | Fast HTTP 302 endpoint `<url>/apply` automatically maps to Greenhouse (e.g. Pure Storage, Planet Labs) with zero browser overhead. | Direct ATS routing enabled. |
| **We Work Remotely (WWR)** | **Production Proven** | Category RSS feeds parsed cleanly; direct ATS links (`id="job-cta-alt"`) extracted. | Geolocked listings require WWR login and are cleanly dropped. |
| **Ashby** | **Blocked (External)** | Server-side Cloudflare bot-risk scoring rejects automated sessions. | Safely disabled in fetcher (`status='blocked_antibot'`) to avoid burning runtime. |
| **Naukri** | **Blocked (External)** | Enforces mandatory login/registration modal on "Apply". | Cannot be automated safely without candidate credentials. |
| **Foundit** | **Blocked (External)** | Enforces mandatory redirect to `/rio/login/seeker`. | Requires candidate login credentials. |
| **Instahyre** | **Blocked (External)** | Discovery works via REST API; apply redirects to `/candidates/register/`. | Requires candidate login credentials. |
| **CutShort** | **Blocked (External)** | Enforces WhatsApp/SMS OTP candidate authentication wall. | Requires interactive phone OTP. |
| **Wellfound** | **Blocked (External)** | Protected by Cloudflare Turnstile CAPTCHA and mandatory login. | Requires interactive login and CAPTCHA solving. |
| **WorkAtAStartup** | **Blocked (External)** | Enforces Y Combinator Bookface OAuth authentication. | Requires external OAuth credentials. |

---

## 3. Daily Capacity & Measured Funnel

### Single-Run Funnel Experiment (Measured Live)
* **Raw Discovered**: 4,447 jobs (ATS: 4,082, Indeed: 247, Himalayas: 119, WWR: 63, Arbeitnow: 19, Remotive: 18, RemoteOK: 10)
* **Pre-Deduplicated / Already in DB**: 4,332 jobs
* **Filtered (Geo / Seniority / Salary)**: 30 jobs
* **Cross-Board Duplicate Collapsed**: 36 jobs
* **Fresh Eligible Saved**: 49 jobs
* **Scored (Score ≥ 6.5)**: 12 jobs
* **Tailored Batch**: 5 jobs
* **Attempted Batch**: 5 jobs

### Capacity Calculation
* **Average Application Cycle Time**: ~36 to 40 seconds per submitted application.
* **Failure Cycle Time (Fail-Fast)**:
  * Unsupported / external account required: ~10 seconds.
  * Form structure changed / unrecognized: ~26 to 81 seconds.
  * Expired / closed posting: ~29 seconds.
  * CAPTCHA challenge detected (unassisted): ~130 seconds.
* **Daily Target (100 confirmed submissions/day)**:
  * 100 applications @ 40s = ~4,000 seconds (~67 minutes) total active browser time.
  * Across a 24-hour continuous window, Hermes has more than sufficient throughput capacity to reach the 100/day target when candidate matching supply is available.

---

## 4. Key Fixes & Enhancements Summary

1. **Xvfb Display Lifecycle (`src/display.py`)**:
   * Removed child process killing inside display initialization.
   * Made `ensure_virtual_display()` idempotent with active X11 liveness validation (`xdpyinfo` / `is_display_alive`).
   * Protected active Hermes PID, its descendants, and Xvfb PID during browser cleanup.
   * `SingletonLock` is only cleaned if the owning PID is confirmed non-existent.

2. **Application Attempt Accounting (`src/apply.py`)**:
   * Implemented `is_infrastructure_failure()` to intercept browser launch errors, display unavailable, and CDP disconnects before external application actions occur.
   * Attempts counter is restored to pre-claim count, preventing infrastructure hiccups from burning candidate attempts.

3. **Gmail Response Classification (`src/response_watcher.py`)**:
   * Purged noisy patterns (`no-reply`, `this is an automated`, `if selected`).
   * Explicit positive/rejection/ack patterns evaluated prior to marketing job alerts.
   * Desktop alerts restricted to positive classifications on matched submitted jobs.
   * Enforced monotonic status updates (positive responses cannot be overwritten).

4. **New Discovery Adapters (`src/sources_wwr.py`, `src/sources_arbeitnow.py`)**:
   * WWR category RSS feeds for programming, full-stack, backend, frontend, and devops.
   * Arbeitnow remote jobs API with fast HTTP 302 ATS detection (`resolve_apply_target_fast`).

5. **Redirect & ATS Resolution Speedup (`src/redirect_resolver.py`)**:
   * Added `resolve_fast_http()` for sub-second ATS resolution without browser launch.
   * Early drop of signup-walled aggregator URLs (`remoteok.com/sign-up`, `himalayas.app/signup`, `jobicy.com`).

6. **24/7 Continuous Mode & 250–500 Reserve (`src/pipeline.py`, `scripts/run_hermes.sh`)**:
   * Added `--continuous` mode with persistent queue reserve maintenance (250–500 jobs).
   * Added 10MB log rotation to `scripts/run_hermes.sh`.
   * Created `scripts/hermes-continuous.service` for systemd user session.

---

## 5. Production Operations Guide

### Starting / Managing the Continuous Worker
```bash
# To run continuous queue worker directly:
./scripts/run_hermes.sh --continuous

# To enable and start as a 24/7 systemd user service:
systemctl --user enable --now hermes-continuous.service

# To check continuous worker status:
systemctl --user status hermes-continuous.service
journalctl --user -u hermes-continuous.service -f
```

### Checking Status & Metrics
```bash
# Check current Hermes status and recent log entries:
./scripts/hermes-status.sh

# Query database counts:
python3 -c "import sqlite3; conn = sqlite3.connect('db/applications.db'); print(dict(conn.execute('SELECT status, count(*) FROM jobs GROUP BY status').fetchall()))"

# Run tests:
pytest
```
