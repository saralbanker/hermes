🤖 Applying knowledge of @[system-investigator]...
  ──────
   REPOSITORY STATE 
  ### Modified Files (16 tracked files)
  1. ats_candidates.txt: Added 42 remote-first and globally distributed company names (e.g., Netflix, Spotify, Asana,
  GitLab) to seed Lever board discovery.
  2. ats_companies.yaml: Expanded target company rosters across Ashby, Greenhouse, and Lever.
  3. answers.py: Added deterministic answer mappings for ATS screening fields (work authorization, notice period, location
  preference, compensation expectations, experience).
  4. apply.py: Added routing for direct forms (CH_DIRECT), integration with direct_form.py, BLOCKED_ANTIBOT channel-
  breaker threshold handling (pauses channel after 2 hits), and crash reclaim age checking.
  5. ats_apply.py: Added server-side anti-bot banner detection, Greenhouse email OTP polling and auto-fill loop via Gmail,
  and multi-pass re-filling for fields cleared by resume-parse autofill.
  6. ats_extract.js: Updated DOM query script for field extraction and labelling across custom ATS variations.
  7. filters.py: Added title exclusion patterns for non-engineering teaching/tutoring/bootcamp academy roles.
  8. indeed_apply.py: Added stall detection (checking for identical page signature across consecutive steps), anti-bot
  classification, checkbox DOM resolution, and forwarding of external "Apply on company site" links.
  9. otp_resolver.py: Added Greenhouse security code extraction from Gmail IMAP over TLS and App Password fallback file
  loading.
  10. redirect_resolver.py: Added resolve_indeed_external method to navigate and resolve employer destination URLs from
  Indeed external apply redirects.
  11. states.py: Added state constants BLOCKED_ANTIBOT and CH_DIRECT.
  12. tailor.py: Added PROJECT_NUMBERS dictionary and _misattributed_number() validator to prevent truth-sheet metric
  cross-contamination between projects.
  13. test_apply_engine.py: Updated tests covering apply lifecycle and queue ordering.
  14. test_ats.py: Expanded test coverage for field extraction, form filling, and Greenhouse schema merging.
  15. test_filters.py: Added test cases for teaching role title filtering.
  16. test_truthfulness.py: Added tests verifying rejection of misattributed project metrics and unverified claims.

  ### Untracked Files

  • src/direct_form.py: (343 LOC) Generic Playwright-based form-filling engine for hand-rolled career sites.
  • tests/test_direct_form.py: Unit tests for direct_form.py.
  • tests/test_apply_routing.py: Tests for channel resolution and aggregator redirection.
  • tests/test_indeed_checkbox_fill.py: Unit tests for Indeed custom checkbox interactions.
  • tests/test_indeed_session_checks.py: Unit tests for session validation.
  • tests/test_indeed_stall_detection.py: Tests for repeated page signature detection.
  • tests/test_otp_resolver.py: Tests for regex and OTP message extraction.
  • tests/test_redirect_resolver_indeed_external.py: Tests for external redirect resolution.
  • db/backups/: Database snapshot backups from previous test and reconciliation sessions.
  • .claude/: Claude Code IDE configuration (settings.json).
  • files.txt: 960KB file index artifact from prior analysis.
  • full.diff: 112KB git diff patch file.
  • status.txt: 1KB git status capture.
  ### Experimental Files

  • src/direct_form.py: Working standalone implementation, but untracked and tested in production only once (failed with
  form_changed).
  • screenshots/direct_form_dryrun/: Ad-hoc test screenshots from developer dry runs on SmartRecruiters, Workable,
  Recruitee, and Runware.
  ### Production-Critical Files

  • Orchestration: pipeline.py, run_hermes.sh, preflight.py, display.py, cap_enforcer.py
  • Database & State: db.py, states.py, applications.db, schema.sql
  • Discovery & Filtering: discover.py, sources_ats.py, filters.py, geo.py, keywords.py
  • Scoring & Tailoring: score.py, tailor.py, llm.py, facts.md, config.yaml, 
  • Application Execution: apply.py, indeed_apply.py, ats_apply.py, ats_extract.js, answers.py, otp_resolver.py,
  redirect_resolver.py
  • Monitoring & Email: response_watcher.py, notify.py
  • Systemd Units: hermes.service, hermes.timer, hermes-watch.service, hermes-watch.timer
  ### Generated, Temporary, Test Artifact, Stale, and Dead Code Files

  • Generated: output/metrics.jsonl, output/hermes_cron.log, output/hermes.lock, output/tailored/, screenshots/*.png.
  • Temporary: files.txt, full.diff, status.txt, db/backups/*.bak.
  • Test Artifacts: output/reports/crash_recovery.md, output/reports/indeed_reconciliation.md,
  screenshots/direct_form_dryrun/, screenshots/investigation/, screenshots/livetest-*.
  • Stale/Dead/Suspicious Files:
      • tracker.py: 278 lines of dead code. Standalone CLI tool never imported by the pipeline or referenced by systemd
      units.
      • agent-build-plan.md, AUTONOMOUS_AI_WORKER_ARCHITECTURE_TRIBUNAL.md, job-automation-roadmap.md, CLAUDE.md: Outdated
      design documents and obsolete plans from previous agents.
      • output/pipeline_run.log, output/ollama.log, output/monitor.log, output/usage_session.json: Stale logs and state
      from June/July 2026.
      • .playwright-mcp/, .mcp.json: Unused MCP server configuration artifacts.

  ──────
   RUNTIME MANIFEST 
  ### 1. Scheduler Subsystem
  • Entrypoint: systemd --user triggers scripts/hermes.service via scripts/hermes.timer (08:00, 13:00, 19:00 IST) →
  executes run_hermes.sh → pipeline.py.
  • Imported Modules: fcntl, psutil, argparse, json, time, threading, db, cap_enforcer, display.
  • Downstream Dependencies: Linux flock (fd 9), timeout, scripts/preflight.py, Xvfb display (:100), Google Chrome.
  • Database Interactions: Reads daily_limits via cap_enforcer.remaining_today(); reads and aggregates status_counts() and
  tier_counts_today(); invokes db.collapse_duplicates().

  ### 2. Discovery Subsystem
  • Entrypoint: discover.py (invoked by pipeline.py::run_stage("discover")).
  • Imported Modules: db, filters, geo, sources_ats, requests, bs4, yaml.
  • Downstream Dependencies: Network HTTP requests to Indeed job search, ATS public board feeds (Greenhouse, Lever, Ashby
  via sources_ats.py), and aggregators (Himalayas, Remotive, RemoteOK).
  • Database Interactions:
      • db.get_all_urls(): queries existing URLs to skip duplicates.
      • db.save_job(): writes discovered rows to jobs table with statuses discovered, filtered, skipped, or expired.


  ### 3. Scoring Subsystem
  • Entrypoint: score.py (invoked by pipeline.py::run_stage("score")).
  • Imported Modules: db, llm, filters, yaml, requests.
  • Downstream Dependencies: Local Ollama instance (localhost:11434) running nomic-embed-text (embedding pre-rank) and
  qwen3:4b (LLM scoring).
  • Database Interactions:
      • db.get_jobs_by_status("discovered").
      • db.update_job(): updates jobs table with status = 'scored', score = <float>, score_reason = <text>, tier = 'core'|
      'stretch'.
  ### 4. Tailoring Subsystem

  • Entrypoint: tailor.py (invoked by pipeline.py::run_stage("tailor")).
  • Imported Modules: db, llm, filters, yaml, re, pathlib.
  • Downstream Dependencies: Local Ollama (qwen3:4b), facts.md, resumes.
  • Database Interactions:
      • db.get_jobs_above_score(min_score=6.5).
      • db.update_job(): sets status = 'tailored', cover_letter_path = 'output/tailored/...', resume_variant = 
      'fullstack'|'backend'. Writes cover letter text files to disk in output/tailored/.

  ### 5. Apply Subsystem

  • Entrypoint: apply.py (invoked by pipeline.py::run_stage("apply")).
  • Imported Modules: db, states, answers, display, cap_enforcer, indeed_apply, ats_apply, direct_form, redirect_resolver,
  notify.
  • Downstream Dependencies: Virtual Xvfb display (:100), Google Chrome binaries, Playwright, DrissionPage.
  • Database Interactions:
      • reset_stuck_applying(): updates stale status = 'applying' rows to status = 'tailored', status_reason =
      'reset_after_crash'.
      • db.claim_job(): atomic SQL update moving status = 'tailored' → 'applying' with attempts = attempts + 1.
      • db.already_applied_key(): checks dedupe_key to avoid re-applying to duplicate roles.
      • db.update_job(): writes terminal states (submitted, failed, form_changed, blocked_antibot, submission_unconfirmed,
      unsupported_channel).
      • db.increment_daily(): records counts in daily_limits.


  ### 6. ATS Engine (Greenhouse / Lever / Ashby)
  • Entrypoint: ats_apply.py (called by apply.py::route()).
  • Imported Modules: states, answers, display, otp_resolver, Playwright sync API.
  • Downstream Dependencies: Playwright persistent profile (output/chrome-ats-profile), ats_extract.js, Gmail IMAP via TLS
  for Greenhouse OTP.
  • Database Interactions: Returns states.ApplyResult, which apply.py writes into jobs table (including
  submission_evidence and screenshot_path).
  ### 7. Direct Form Engine
  • Entrypoint: direct_form.py (called by apply.py::route() when apply_channel == 'direct').
  • Imported Modules: states, ats_apply (_extract_fields, _fill_all, _submit, etc.), display, Playwright sync API.
  • Downstream Dependencies: Playwright persistent profile (output/chrome-direct-profile), Xvfb (:100).
  • Database Interactions: Returns states.ApplyResult recorded by apply.py.

  ### 8. Gmail Watcher Subsystem
  • Entrypoint: response_watcher.py (invoked via systemd --user timer hermes-watch.timer every 10 minutes).
  • Imported Modules: db, notify, otp_resolver (_connect, _get_app_password), email, imaplib, sqlite3.
  • Downstream Dependencies: Gmail IMAP over TLS (imap.gmail.com:993) using credentials from output/gmail_app_password.txt.
  • Database Interactions:
      • responses table: stores raw parsed email headers (message_id, from_addr, subject, received_at, classification,
      job_url).
      • jobs table: updates response_status, response_subject, response_at for matching job URLs.
  ### 9. Crash Recovery Subsystem
  • Entrypoints:
      • apply.py:246
      • db.py:110
      • pipeline.py:138 / run_hermes.sh:23
  • Imported Modules: sqlite3, fcntl, os.
  • Downstream Dependencies: Linux kernel file locking (output/hermes.lock).
  • Database Interactions: Atomic SQL queries resetting abandoned 'applying' rows and deduplicating cross-board listings.
  ──────
   SYSTEM STATUS 
   Subsystem     | Status            | Evidence Rank & Details
  ---------------|-------------------|------------------------------------------------------------------------------------
   Scheduler     | Working           | Rank 4 (Runtime) & Rank 8 (Logs): systemctl --user status hermes.timer active
                 |                   | since Sep 11. journalctl shows runs at 08:01, 13:01, 19:01 daily. Lock collision
                 |                   | confirmed caught on Sep 23 21:14:50 (another Hermes run holds hermes.lock —
                 |                     | exiting).
                 |                                     | exiting).
   Gmail Watcher | Working                             | Rank 4 (Runtime), Rank 5 (DB), Rank 8 (Logs): hermes-
                 |                                     | watch.service ran at 13:05:13 IST, successfully scanned 80
                 |                                     | emails. responses table has 120+ rows, accurately categorized
                 |                                     | ack from no-reply@cloudflare.com and rejection from Indeed
                 |                                     | employers.
   Indeed        | Partially Working                      | Rank 1 (Platform), Rank 2 (Email), Rank 4 (Runtime): 37
                 |                                        | successful submissions in DB. 14 recent submissions (Sep
                 |                                        | 23–24) have verified confirmation emails from
                 |                                        | indeedapply@indeed.com and reflect in candidate's Applied
                 |                                        | History (68 applied total). However, current run live-failed
                 |                                        | on MyProFunnels (id 2147) due to a 6-minute timeout on an
                 |                                        | unhandled form step.
   Greenhouse    | Working                                | Rank 1 (Platform), Rank 2 (Email), Rank 5 (DB), Rank 7
                 |                                        | (Screenshot): Cloudflare Software Engineer (job id 4410)
                 |                                        | submitted on 2026-09-25 04:02:06 IST. Real OTP received from
                 |                                        | no-reply@us.greenhouse-mail.io at 22:31:51 UTC, entered via
                 |                                        | _resolve_greenhouse_otp, confirmed by receipt email from no-
                 |                                        | reply@cloudflare.com at 22:33:06 UTC. Screenshot:
                 |                                        | screenshots/livetest-real-cloudflare-software-engineer.png.
   Lever         | Unverified                             | Rank 5 (DB): Zero production submissions in database history
   Lever            | Unverified                             | Rank 5 (DB): Zero production submissions in database
                    |                                        | history (117 filtered, 14 expired, 3 scored below
                  |                                        | (screenshots/livetest-dry-neon-staff-machine-learning-
                  |                                        | engineer.png). No live submission ever verified.
   Ashby          | Broken                                 | Rank 4 (Runtime), Rank 5 (DB), Rank 7 (Screenshot): Zero
                  |                                        | successful submissions. Real test attempts resulted in
                  |                                        | blocked_antibot (job 7922 Notion: Ashby anti-bot flagged
                  |                                        | submission as spam), form_changed (validation error after
                  |                                        | submit), or submission_unconfirmed.
   Direct Forms   | Partially Working / Unverified in Prod | Rank 5 (DB), Rank 9 (Code): Engine exists
                  |                                        | (src/direct_form.py) and is routed from apply.py. Only 1
                  |                                        | real job reached it in production (job 8069 Leader IT) and
                  |                                        | failed with form_changed (no Next/Submit control found).
                  |                                        | Manual dry-run scripts passed on external sites, but 0
                  |                                        | production submissions exist.
   Scoring        | Working                                | Rank 4 (Runtime), Rank 5 (DB), Rank 8 (Logs): Ollama
                  |                                        | integration active (nomic-embed-text + qwen3:4b). Scored 8
                  |                                        | jobs in 105.6s during today's 13:02 IST run with grounded
                  |                                        | reasoning strings written to jobs.score_reason.
   Tailoring      | Working                                | Rank 4 (Runtime), Rank 5 (DB), Rank 9 (Code): Generated
                  |                                        | cover letter for job 8453 at 13:06 IST
                  |                                        | (output/tailored/unknown-front-end-developer-intern-8453-
                  |                                        | cover.txt). Passed strict truthfulness assertions against
                  |                                        | facts.md.
   Crash Recovery | Partially Working                      | Rank 4 (Runtime), Rank 5 (DB): reset_stuck_applying(0)
                  |                                        | verified live: job 2147 reclaimed from applying to tailored
                  |                                        | upon startup; attempts limit (3) correctly enforced to
                  |                                        | transition it to failed. However, orphan Chrome process
                  |                                        | cleanup on SIGKILL is completely missing.
  ──────
   VERIFIED CAPABILITIES 

  1. Live Systemd Scheduling & Overlap Prevention: Kernel-level flock on output/hermes.lock prevents overlapping scheduled
  and manual runs.
  2. Gmail Employer Response Ingestion: Automated TLS IMAP polling via response_watcher.py every 10 minutes extracts,
  classifies, and writes applicant correspondence to responses table.
  3. End-to-End Greenhouse Form Submission with Email OTP: Successfully completed automated submission on Greenhouse
  boards including multi-step forms and automated Gmail-based security code extraction and insertion.
  4. Candidate-Authenticated Indeed Easy Apply: Automated form-filling through headful Chrome in Xvfb with verified
  employer confirmation emails and synchronization with Indeed Applied account history.
  5. Idempotent Job Reclaim & Attempt Limit: Stale jobs left in applying from aborted runs are automatically reset to
  tailored upon startup, and hard limits (MAX_ATTEMPTS = 3) are strictly enforced.
  6. Local LLM Scoring & Factual Tailoring: Fast pre-filtering via embeddings and factual candidate letter generation
  without hallucinations or mismatched project figures.
  ──────
   BROKEN CAPABILITIES 
  1. Ashby Submissions: Ashby's server-side bot-risk scoring detects headless/automation signals and terminates
  submissions with spam flags (blocked_antibot: couldn't submit...).
  2. Orphan Browser Cleanup on Hard Crash: If Python receives SIGKILL or crashes abruptly, Chrome processes and Xvfb
  instances are left orphaned and hold profile locks, requiring manual termination.
  3. Indeed Complex Form Navigation: Unrecognized custom select elements or dynamically nested question blocks stall form
  advancement, causing the 6-minute budget to expire (e.g., job 2147 MyProFunnels).
  ──────
   UNVERIFIED CAPABILITIES 
  1. Lever Live Application Submission: Never tested in real production (no candidate jobs have passed the scoring
  threshold to trigger an actual submission).
  2. Direct Form Production Submissions: Hand-rolled career page engine has only processed 1 production job, which failed
  to advance. Zero production submissions exist.
  ──────
   LOAD-BEARING FILES 

  • pipeline.py
  • run_hermes.sh
  • discover.py
  • score.py
  • tailor.py
  • apply.py
  • indeed_apply.py
  • ats_apply.py
  • ats_extract.js
  • direct_form.py
  • answers.py
  • otp_resolver.py
  • redirect_resolver.py
  • response_watcher.py
  • db.py
  • states.py
  • filters.py
  • geo.py
  • llm.py
  • display.py
  • cap_enforcer.py
  • facts.md
  • config.yaml
  ──────
   DEAD OR SUSPICIOUS FILES 
  • tracker.py: Abandoned legacy CLI dashboard.
  • agent-build-plan.md, AUTONOMOUS_AI_WORKER_ARCHITECTURE_TRIBUNAL.md, job-automation-roadmap.md, CLAUDE.md: Obsolete
  multi-agent planning and prompt documents.
  • output/usage_session.json: Stale runtime artifact from June 2026.
  • output/pipeline_run.log, output/ollama.log, output/monitor.log: Stale legacy logs.
  • files.txt, full.diff, status.txt: Temporary scratch text dumps in the repository root.
  ──────
   RELEASE BLOCKERS 
  1. Untracked Core Engine Files: direct_form.py and 7 companion test files in tests/ are untracked in git. A clean git
  checkout will break apply.py import of direct_form.
  2. Missing Automated Orphan Browser Cleanup: Abrupt process terminations leave zombie Chrome processes holding Singleton
  locks in output/chrome-*-profile/, blocking subsequent unattended runs.
  3. Ashby Anti-Bot Wall: Ashby cannot be used as an automated channel until bot-detection resistance is introduced;
  attempting Ashby applications currently burns run time and triggers spam flags.
  4. Indeed Custom Control Form Stalls: Unrecognized custom form inputs can stall Indeed applications until the 6-minute
  timeout threshold is reached.
  ──────
   KNOWN-GOOD BASELINE CANDIDATE 
  The following components are safe to commit and lock as the reproducible operational baseline:
  • Git Commit Target: Commit the 16 modified tracked files + untracked direct_form.py + 7 test files in tests/.
  • Exclude / Remove: Delete scratch files (files.txt, full.diff, status.txt), archive or remove src/tracker.py and root .
  md plan files.
  • Verified Core Pipeline: Scheduler (systemd), Discovery (Indeed + Greenhouse + Aggregators), Scoring (nomic-embed-text +
  qwen3:4b), Tailoring (facts.md), Apply (Indeed Easy Apply + Greenhouse with Gmail OTP), Gmail Response Watcher
  (response_watcher.py).
  ──────
   CONFIDENCE SCORE 

   Conclusion Area                | Confidence Level | Rationale
  --------------------------------|------------------|--------------------------------------------------------------------
   Repository File State          | HIGH             | Verified directly via git status, file system enumeration, and
                                  |                  | line-by-line inspection.
   Scheduler & Overlap Prevention | HIGH             | Verified via live systemd timers, active unit processes, and
                                  |                  | journalctl history.
   Greenhouse Verification        | HIGH             | Verified via Rank 1/2 evidence: live submission, real OTP email in
                                  |                  | Gmail, and real employer acknowledgement.
   Indeed Submissions             | HIGH             | Verified via Rank 1/2/3 evidence: 14 recent confirmation emails
                                  |                  | from indeedapply@indeed.com, live process execution.
   Ashby Blockers                 | HIGH             | Verified via Rank 4/5/7 evidence: database status blocked_antibot,
                                  |                  | runtime logs, and browser screenshots.
   Lever Inactivity               | HIGH             | Verified via database inspection: 0 applications have ever passed
                                  |                  | the scoring threshold in production.
   Direct Form Operational State  | HIGH             | Verified via codebase inspection, import verification, and single
                                  |                  | failed production DB record.
   Crash Recovery Mechanics       | HIGH             | Verified via live runtime demonstration of atomic status reclaim
                                  |                  | and attempt-limit enforcement.
