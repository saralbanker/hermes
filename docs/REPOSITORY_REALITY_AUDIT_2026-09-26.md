# Hermes Repository Reality Audit (2026-09-26)

**Audit Date:** 2026-09-26  
**Auditor Persona:** System Investigator (`@[system-investigator]`)  
**Target Repository:** `saralbanker/hermes`  
**Branch:** `overhaul-2026-09-23`  
**HEAD Commit:** `f8a447e baseline: verified scheduler, gmail, indeed, greenhouse and direct-form routing`  
**Evidence Hierarchy Applied:**  
1. Runtime execution evidence  
2. Database evidence (`db/applications.db`)  
3. Application history evidence  
4. Employer email evidence (Gmail IMAP receipts)  
5. Git-tracked source code  
6. Automated tests (pytest suite)  
7. Logs (`output/hermes_cron.log`, `journalctl`)  
8. Existing documentation  
9. Historical agent reports  

---

## 1. Executive Summary

An exhaustive, evidence-based audit of the Hermes repository was conducted to determine the actual operating state of the system versus historical agent claims and documentation. 

The audit reveals a stark divergence between theoretical code presence / passing unit tests (337 passing tests) and production runtime reality:
1. **Core Offline Pipeline (Discovery, Scoring, Tailoring, IMAP Reply Polling) is Fully Operational:** Discovery consistently scrapes thousands of listings (~6,026 raw jobs per cycle across Indeed, ATS APIs, Himalayas, Remotive, and RemoteOK), scoring accurately computes local embeddings via `nomic-embed-text` and local LLM evaluations via `qwen3:4b-instruct-2507-q4_K_M` on Ollama, and tailoring successfully generates grounded cover letters validated against `profile/facts.md`.
2. **Apply Stage is Experiencing a 100% Runtime Blocker Due to an In-Process Process Murder Bug:** In automated execution (`run_hermes.sh` via systemd `hermes.service`), **100% of browser-based application attempts in the current run failed with `network_error`**. Specifically, `src/display.py:cleanup_orphan_browsers()` terminates any process named `xvfb` without excluding its own child PID. The moment `ensure_virtual_display()` is invoked inside an applier or redirect resolver, it kills its own virtual X11 server and unlinks `/tmp/.X11-unix/X99`. Consequently, subsequent headful Chrome launches cannot connect to the display, crash immediately, and DrissionPage fails to connect to port 9222/9377 with `BrowserConnectError`. This bug burned through job retry limits during today's scheduled 13:01 run, permanently marking 5 jobs with terminal `network_error` after 3 failed attempts.
3. **Channel Verification Reality:**
   - **Greenhouse:** **Production Proven.** Exactly 1 real-world submission is verified in the database (Job ID 4410, Cloudflare), confirmed by an employer acknowledgment email (`Cloudflare Recruiting | Application Received - Software Engineer`, 2026-09-24T22:33:06Z) and preceded by an automated OTP security code resolution via Gmail (`Security code for your application to Cloudflare`, 2026-09-24T22:31:51Z).
   - **Indeed:** **Production Proven in Previous Sessions, Currently Blocked.** Exactly 1 job is verified in the database with status `submitted` (Job ID 8453, Front End Developer Intern, applied 2026-09-25T13:18:48), backed by an employer notification email (`Indeed Application: Front End Developer Intern`, 2026-09-25T07:48:39Z). However, all current Indeed attempts fail due to the `display.py` Xvfb self-kill bug.
   - **Lever:** **Completely Unverified (0 Submissions, 0 Attempts).** In the database, only 3 Lever jobs ever reached `scored`, all scoring ≤ 6.0 (below the 6.5 apply threshold). Zero Lever applications have ever been queued or attempted. Furthermore, `src/ats_apply.py` contains no Lever-specific form logic; it relies solely on generic heuristic field extraction.
   - **Ashby:** **Blocked by Anti-Bot Detection (0 Submissions).** Real-world submissions were rejected by Ashby's server-side bot-risk checks (Job ID 7922 Notion: `blocked_antibot: bot-risk check rejected the submission: couldn't submit your application`). No automated submissions have succeeded.
   - **Direct Forms:** **Unverified / Broken (0 Submissions).** Only 1 job ever reached direct application (Job ID 8069, Leader IT), which failed immediately with `form_changed: no Next/Submit control found on this step`.
4. **Gmail Watcher Drift:** `src/response_watcher.py` runs successfully on schedule, but its rule-based classifier has severe false positive and false negative bugs: it misclassified BookMyShow concert ticket newsletters as positive `ack` because of `no-reply` in the header, and misclassified all 15 genuine `Indeed Application:` confirmation emails as `other` because their footers contain the phrase `recommended jobs`.
5. **Throughput Target Failure:** The documented target of 100 applications/day has never been approached. The all-time single-day maximum was 20 applications (2026-06-25), with 10 on 2026-09-24, 2 on 2026-09-25, and 0 on 2026-09-26.

---

## 2. Repository Snapshot

- **Current Branch:** `overhaul-2026-09-23`
- **Tracking Branch:** `origin/overhaul-2026-09-23` (up to date)
- **Latest Git Commit:** `f8a447e baseline: verified scheduler, gmail, indeed, greenhouse and direct-form routing`
- **Git Tags:** `baseline-2026-09-25`
- **Working Tree State:**
  - *Deleted (uncommitted):* `docs/CURRENT_TRUTH_STATE_HERMES_v1_2026-09-25.md`
  - *Untracked files:*
    - `.claude/`
    - `db/backups/`
    - `docs/CURRENT_TRUTH_STATE(2026-09-26).MD`
    - `docs/ROADMAP.md`
    - `docs/SYSTEM_ARCHITECTURE.md`
    - `files.txt`
    - `full.diff`
    - `status.txt`
- **Test Suite Status:**
  - Command: `pytest --tb=short`
  - Result: **337 passed in 13.58s** (100% test pass rate across all 13 test suites).
  - *Critical Note:* Passing unit tests mock external browsers, network I/O, and Xvfb; they do not catch the runtime process termination bug in `display.py` or ATS platform anti-bot blocks.

---

## 3. Runtime Architecture Verified

The verified execution topology on the host machine (`archlinux`, Linux 6.x, AMD Ryzen 7 7730U) is mapped below:

```
systemd --user timers
 ├── hermes.timer (08:00, 13:00, 19:00) ──────► scripts/run_hermes.sh
 │                                                    │ (flock output/hermes.lock)
 │                                                    ▼
 │                                              src/pipeline.py
 │                                                    │
 │                     ┌──────────────────────────────┼──────────────────────────────┐
 │                     ▼                              ▼                              ▼
 │              src/discover.py                 src/score.py                   src/tailor.py
 │              (JobSpy + ATS APIs)             (Ollama Qwen3 4B + Nomic)     (Facts Validation)
 │                     │                              │                              │
 │                     └──────────────────────┬───────┴──────────────────────────────┘
 │                                            ▼
 │                                      src/apply.py
 │                                            │
 │                                            ├──► display.ensure_virtual_display() [Xvfb :99]
 │                                            │      ▲ (CRITICAL BUG: cleans up its own Xvfb)
 │                                            ▼      │
 │                     ┌──────────────────────┬──────┴───────────────────────────────┐
 │                     ▼                      ▼                                      ▼
 │               indeed_apply.py        ats_apply.py                           direct_form.py
 │               (DrissionPage CDP)     (Playwright)                           (Playwright)
 │               [FAILED: Port 9222]    [Greenhouse: OK | Ashby: BLOCKED]      [0 Submissions]
 │
 ├── hermes-watch.timer (Every 10 min) ────────► src/response_watcher.py ──► Gmail IMAP SSL (993)
 │                                                                                    │
 └── hermes-summary.timer (21:00) ─────────────► Daily Summary / Notification        ▼
                                                                               db/applications.db
```

---

## 4. Subsystem Audit

| Subsystem | Implementation File(s) | Implementation Status | Runtime Reachability | Evidence | Confidence Level |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Scheduler** | `scripts/run_hermes.sh`, `scripts/*.timer`, `scripts/*.service` | **Complete** | **Active & Executing** | `systemctl --user list-timers` confirms active triggers. `journalctl --user -u hermes.service` records runs on Sep 24, 25, 26. Flock on `output/hermes.lock` verified. | **High (Verified)** |
| **Discovery** | `src/discover.py`, `src/sources_ats.py` | **Complete** | **Active & Executing** | Scrapes 14 Indeed queries, 161 ATS companies (`data/ats_companies.yaml`), Himalayas, Remotive, RemoteOK. 2026-09-26 13:01 log: `Found 6026 raw jobs total; 5964 already in DB, skipping; Saved 4 eligible jobs`. DB has 8,588 rows. | **High (Verified)** |
| **Scoring** | `src/score.py`, `src/llm.py`, `src/keywords.py` | **Complete** | **Active & Executing** | Nomic-embed pre-rank (cosine floor 0.55) + Qwen3 4B scoring on Ollama (localhost:11434). Log: `[score] Done — scored: 4, avg: 6.25`. DB has 702 scored rows. Keyword TF-IDF fallback exists. | **High (Verified)** |
| **Tailoring** | `src/tailor.py`, `profile/facts.md` | **Complete** | **Active & Executing** | Core ≥6.5, Stretch ≥7.5. Fact validator checks constraints (no exaggerated years of experience, valid projects). Generates files in `output/tailored/`. Log: `[tailor] Done. {'tailored/llm': 2}`. | **High (Verified)** |
| **Apply Pipeline** | `src/apply.py` | **Complete (Logic)** | **BROKEN AT RUNTIME** | State transitions, queue tiering (70/30), and channel routing are structured, but browser invocation crashes due to Xvfb killing. 2026-09-26 log: `[apply] Done — {'network_error': 10}`. | **High (Defect Verified)** |
| **Indeed Channel** | `src/indeed_apply.py` | **Complete** | **Blocked by Runtime Bug** | DrissionPage CDP on headful Chrome. 1 past submission confirmed (Job 8453). Currently failing on browser launch due to `display.py`. | **High (Verified)** |
| **Greenhouse Channel**| `src/ats_apply.py` | **Complete** | **Fully Operational** | Playwright form filling + OTP resolution. 1 production submission confirmed (Job 4410 Cloudflare, 2026-09-24T22:33:06Z). | **High (Verified)** |
| **Lever Channel** | `src/ats_apply.py` | **Incomplete / Generic** | **Unreachable in Practice** | Generic DOM scraper only. Zero jobs have ever passed score cutoff to be queued. 0 applications attempted. | **High (Verified)** |
| **Ashby Channel** | `src/ats_apply.py` | **Blocked by Platform** | **Fails at Submission** | Playwright fills form, but Ashby server detects automation. Job 7922: `blocked_antibot: bot-risk check rejected the submission`. 0 successful submissions. | **High (Verified)** |
| **Direct Forms** | `src/direct_form.py` | **Partial / Fragile** | **Fails at Submission** | Generic multi-step engine. 1 attempt recorded (Job 8069 Leader IT: `form_changed: no Next/Submit control found`). 0 successful submissions. | **High (Verified)** |
| **Redirect Resolver**| `src/redirect_resolver.py`| **Complete** | **Fails at Browser Launch** | DrissionPage on port 9377. Fails in automated runs with `BrowserConnectError: Address 127.0.0.1:9377` due to Xvfb bug. Most resolved destinations require accounts (Himalayas). | **High (Verified)** |
| **OTP Resolver** | `src/otp_resolver.py` | **Complete** | **Verified in Production** | Connects to Gmail IMAP SSL. Resolves Greenhouse 6-digit codes. Successfully handled Cloudflare OTP on 2026-09-24T22:31:51Z. | **High (Verified)** |
| **Gmail Watcher** | `src/response_watcher.py` | **Complete (Buggy Rules)**| **Active & Executing** | Runs via `hermes-watch.service` every 10 min. 206 responses logged in DB. Severe rule drift: BookMyShow tickets marked `ack`, Indeed confirmations marked `other`. | **High (Verified)** |
| **State Machine** | `src/states.py`, `src/db.py` | **Complete** | **Active & Enforced** | Full state progression (`discovered` → `scored` → `tailored` → `applying` → terminal states) reflected accurately across all 8,588 jobs in SQLite. | **High (Verified)** |
| **Daily / Attempt Caps**| `src/cap_enforcer.py`, `db.py` | **Complete** | **Active & Enforced** | Enforces max 3 attempts per job and 100/day. Job attempts are correctly incremented in SQLite. Daily limits tracked in `daily_limits` table. | **High (Verified)** |
| **Crash Recovery** | `src/apply.py` (`reset_stuck_applying`)| **Complete** | **Active & Enforced** | Resets abandoned `applying` jobs back to `tailored`. Verified during pipeline startup. | **High (Verified)** |
| **Browser Cleanup** | `src/display.py` | **FATALLY DEFECTIVE** | **Active (Self-Destructive)** | `cleanup_orphan_browsers()` kills its own parent's Xvfb process, breaking all headless/virtual browser operations. | **High (Verified)** |
| **Notification System**| `src/notify.py` | **Complete** | **Operational** | Uses `notify-send` and audio chimes (`complete.oga`). Executed by `run_hermes.sh` and `response_watcher.py`. | **High (Verified)** |

---

## 5. Application Channel Audit

### Channel: Indeed
- **Underlying Driver:** `DrissionPage` (Chromium CDP, port 9222 default, headful inside Xvfb).
- **Persistent Profile:** `output/chrome-indeed-profile`.
- **Session Credentials:** `output/indeed_session.json` (seeded if profile is unauthenticated).
- **Database Evidence:**
  - 242 total Indeed jobs in DB:
    - `filtered`: 125
    - `scored`: 98
    - `form_changed`: 7
    - `tailored`: 5
    - `network_error`: 2 (now 5 after today's 13:01 run)
    - `submitted`: 1 (Job ID 8453, Front End Developer Intern, applied 2026-09-25T13:18:48)
    - `submission_unconfirmed`: 1
    - `unsupported_channel`: 1
    - `expired`: 1
- **Employer Email Evidence:**
  - Confirmed receipt from `indeedapply@indeed.com` with subject `Indeed Application: Front End Developer Intern` on 2026-09-25T07:48:39+00:00.
  - 14 prior application confirmations received on Sep 23 and Sep 24.
- **Current Runtime Status:** **BLOCKED.** Browser launch fails on every automated run due to Xvfb destruction in `display.py`.

### Channel: Greenhouse
- **Underlying Driver:** `playwright.sync_api` (Chromium, headful inside Xvfb).
- **Persistent Profile:** `output/chrome-ats-profile`.
- **Database Evidence:**
  - 4,142 total Greenhouse jobs:
    - `filtered`: 3,898
    - `expired`: 225
    - `scored`: 17
    - `form_changed`: 1
    - `submitted`: 1 (Job ID 4410, Cloudflare, Software Engineer, applied 2026-09-25T04:02:06)
- **Employer Email Evidence:**
  - Gmail message ID from `no-reply@cloudflare.com`: `Cloudflare Recruiting | Application Received - Software Engineer` (received 2026-09-24T22:33:06Z).
  - Preceding OTP from `Greenhouse <no-reply@us.greenhouse-mail.io>`: `Security code for your application to Cloudflare` (received 2026-09-24T22:31:51Z).
- **Current Runtime Status:** **PROVEN PRODUCTION READY.** This is the only ATS channel with end-to-end verified autonomous submission and OTP resolution.

### Channel: Lever
- **Underlying Driver:** `playwright.sync_api` (shared `ats_apply.py` generic extractor).
- **Database Evidence:**
  - 137 total Lever jobs:
    - `filtered`: 120
    - `expired`: 14
    - `scored`: 3 (Job 6450 score 3.0, Job 6451 score 5.0, Job 8410 score 6.0)
    - `submitted`: 0
- **Attempt History:** 0 attempts. Zero Lever jobs have ever achieved the required score threshold (≥6.5) to reach `tailored` or `applying`.
- **Current Runtime Status:** **UNPROVEN.** Code contains no Lever-specific selectors or handling; production submission is unverified.

### Channel: Ashby
- **Underlying Driver:** `playwright.sync_api` (shared `ats_apply.py` generic extractor).
- **Database Evidence:**
  - 1,672 total Ashby jobs:
    - `filtered`: 1,176
    - `expired`: 407
    - `scored`: 80
    - `form_changed`: 6 (e.g. unanswerable fields: Pronouns, Legal Name, Location checkboxes)
    - `submission_unconfirmed`: 2 (Notion, Baseten)
    - `blocked_antibot`: 1 (Job ID 7922, Notion: `blocked_antibot: bot-risk check rejected the submission: couldn't submit your application`)
    - `submitted`: 0
- **Current Runtime Status:** **BLOCKED BY PLATFORM.** Ashby's anti-bot system detects automation and rejects submissions. No successful submissions exist.

### Channel: Direct Forms
- **Underlying Driver:** `src/direct_form.py` (Playwright, persistent profile `output/chrome-direct-profile`).
- **Database Evidence:**
  - 1 job routed to direct form:
    - Job ID 8069 (`Leader IT`, `Fullstack Golang Developer`): `form_changed: no Next/Submit control found on this step`.
    - `submitted`: 0
- **Current Runtime Status:** **UNPROVEN / FRAGILE.** No confirmed submissions; coverage is limited to basic multi-page forms that strictly match standard button labels.

---

## 6. Dead Code Audit

1. **`src/tracker.py` Status Mismatch and Hardcoded Constants:**
   - File: `src/tracker.py#L32-L40` defines `STATUS_ORDER = ["discovered", "scored", "tailored", "applying", "submitted", "confirmed", "error"]`.
   - Neither `confirmed` nor `error` are valid states in `src/states.py`.
   - Omits canonical states: `filtered`, `expired`, `skipped`, `unsupported_channel`, `form_changed`, `network_error`, `blocked_antibot`, `submission_unconfirmed`, `already_applied`.
   - File: `src/tracker.py#L130-L131` hardcodes:
     ```python
     t2.add_row("LinkedIn used / limit", f"{linkedin_used} / 15")
     t2.add_row("Other used / limit", f"{other_used} / 30")
     ```
     The actual daily limits configured in `config.yaml` are `0` for LinkedIn and `100` for other.
2. **`scripts/cleanup_backlog.py`:**
   - Dedicated migration script written on 2026-09-23 for a one-time backlog re-filtering pass. Not referenced by any active service or pipeline routine.
3. **Stale Cache / Artifacts:**
   - `src/__pycache__/usage_guard.cpython-314.pyc` and `output/usage_session.json` exist on disk, but `src/usage_guard.py` has been deleted from git.

---

## 7. Incomplete Implementation Audit

1. **Self-Killing Virtual Display (`src/display.py`):**
   - In `src/display.py:cleanup_orphan_browsers()`:
     ```python
     elif "xvfb" in name:
         if "1366x900x24" in cmd_str and any(f":{n}" in cmd_str for n in range(99, 140)):
             proc.terminate()
     ```
   - When `pipeline.py` starts, `ensure_virtual_display()` spawns Xvfb on display `:99` as a subprocess.
   - When `indeed_apply.py` or `redirect_resolver.py` subsequently calls `ensure_virtual_display()`, `cleanup_orphan_browsers()` executes again.
   - Because `proc.pid != my_pid` (Xvfb is a child process, not the Python process itself), it identifies its own active Xvfb server as an "orphan", terminates it, and deletes `/tmp/.X99-lock` and `/tmp/.X11-unix/X99`.
   - `ensure_virtual_display()` sees `os.environ["HERMES_XVFB"] == "1"` and returns `:99` without restarting Xvfb.
   - Chrome immediately crashes because display `:99` no longer exists, causing 100% of browser launch attempts to fail.
2. **Gmail Classifier Keyword Pollution (`src/response_watcher.py`):**
   - `_ACK_PATTERNS` in `src/response_watcher.py#L138` contains `r"no-?reply"`. This causes completely unrelated emails (e.g. BookMyShow event tickets) to be classified as job application acknowledgments.
   - `_JOB_ALERT_TEXT_PATTERNS` in `src/response_watcher.py#L81` contains `r"\brecommended jobs\b"` and `r"\bjobs for you\b"`. Because genuine Indeed application confirmation emails contain promotional "Recommended jobs for you" sections in their footers, they match this filter and are classified as `other` instead of `ack`.
3. **Missing Lever Support (`src/ats_apply.py`):**
   - Despite documentation claiming Lever support, `src/ats_apply.py` contains zero Lever-specific DOM selectors or multi-step logic.
4. **Ashby Anti-Bot Vulnerability:**
   - No stealth scripts, CDP evasion, or bot-detection mitigation exist for Ashby GraphQL endpoints.

---

## 8. Documentation Drift Audit

| Document | Stated Claim | Repository & Runtime Reality | Evidence |
| :--- | :--- | :--- | :--- |
| `docs/CURRENT_TRUTH_STATE(2026-09-26).MD` | "Working Indeed submissions" (L462) | **Failing in production runs.** Chrome cannot launch due to Xvfb termination bug. | `output/hermes_cron.log` shows 10 consecutive `network_error` failures on 2026-09-26. |
| `docs/CURRENT_TRUTH_STATE(2026-09-26).MD` | "Lever: Implemented... Verified: Discovery, Routing, Form support" (L220-229) | **Unverified & Untested.** No Lever-specific form logic in `ats_apply.py`. 0 applications attempted. | SQLite query: 3 Lever jobs scored, 0 tailored, 0 attempted, 0 submitted. |
| `docs/CURRENT_TRUTH_STATE(2026-09-26).MD` | "Gmail Watcher Verified: acknowledgement detection, rejection detection" (L84-95) | **Severely flawed.** Misclassifies BookMyShow tickets as `ack` and ignores all real Indeed `ack` emails. | SQLite `responses` table shows BookMyShow as `ack` and 15 Indeed application receipts as `other`. |
| `docs/HERMES_SYSTEM_REPORT.md` | Target: "100 applications per day" (L13) | **Current yield is 0 to 2 applications/day.** All-time peak was 20. | SQLite `daily_limits` table: 2026-09-24: 10, 2026-09-25: 2, 2026-09-26: 0. |
| `docs/SYSTEM_ARCHITECTURE.md` | "Lever ATS Channel fully routed and active" | **Unreachable.** Lever jobs fail score thresholds or are filtered out. | 120 of 137 Lever jobs filtered; 14 expired; 3 scored below 6.5. |

---

## 9. Merge Readiness Assessment

**Status: NOT READY FOR MERGE**

The branch `overhaul-2026-09-23` contains solid architectural foundations (state machine, SQLite schema, Ollama scoring, facts tailoring, and Greenhouse OTP automation), but it has fatal production blockers that prevent successful unattended operation:
- Automated scheduled runs are currently unable to submit applications via Indeed or Redirect channels.
- Retry limits are being permanently consumed by software-induced browser connection failures.
- Email monitoring metrics are poisoned by false positive and false negative classification patterns.

---

## 10. Blocking Issues Before Merge

1. **[CRITICAL] Self-Killing Xvfb in `src/display.py`:**
   - `cleanup_orphan_browsers()` must never kill an Xvfb process that is a child of the current process (`proc.ppid == my_pid` or `proc.pid == _proc.pid`).
2. **[CRITICAL] Runaway Burn of Retry Attempts:**
   - Retries should not be penalized or counted against `MAX_ATTEMPTS` when the failure reason is an internal browser launch failure / Xvfb initialization failure.
3. **[HIGH] Reply Watcher Classification Failure:**
   - `r"no-?reply"` must be removed from `_ACK_PATTERNS` in `src/response_watcher.py`.
   - `indeedapply@indeed.com` must be explicitly classified as `ack` before job-alert footer regexes are evaluated.
4. **[HIGH] Outdated `src/tracker.py` CLI:**
   - Must be updated to read actual limits from `config.yaml` and support modern canonical states from `src/states.py`.

---

## 11. Highest Priority Fixes

1. **Fix `src/display.py`:**
   Track the active Xvfb PID in `_proc`. In `cleanup_orphan_browsers()`, explicitly skip terminating any Xvfb whose PID matches `_proc.pid` or whose parent PID matches `os.getpid()`.
2. **Fix `src/response_watcher.py`:**
   - Remove generic `no-reply` string from `_ACK_PATTERNS`.
   - Add dedicated rule for `indeedapply@indeed.com` with subject matching `^Indeed Application:` to ensure all Indeed application confirmations are captured as `ack`.
3. **Reset Inadvertently Exhausted Job Attempts:**
   - Reset the 5 jobs burned during today's runs (Job IDs 8468, 8469, 8483, 8491, 8496) from `network_error` back to `tailored` with `attempts = 0`.
4. **Reconcile `src/tracker.py`:**
   - Synchronize status list with `src/states.py` and dynamic limits from `cap_enforcer.py`.

---

## 12. Final Verdict

**Branch State:** Architecturally mature, partially verified, but currently in a broken runtime state for Indeed and Redirect applications due to an internal process lifecycle bug in `src/display.py`.

- **Offline Pipeline:** Operational (Discovery, Filtering, Ollama Scoring, Tailoring).
- **Greenhouse ATS:** Production Proven (Verified with real submission & OTP).
- **Indeed Apply:** Previously proven, currently broken by `display.py`.
- **Ashby ATS:** Defeated by anti-bot detection (0 submissions).
- **Lever ATS:** Completely untested in production (0 submissions).
- **Direct Forms:** Experimental and unverified in production (0 submissions).
- **Gmail Watcher:** Active, but classification rules require immediate remediation.

*Report compiled strictly from verifiable runtime traces, database records, email receipts, and source code inspection on 2026-09-26.*
