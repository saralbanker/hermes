# Report 5: Production Freeze & Baseline Capture

**Document ID:** HERMES-FREEZE-05
**Date/Time of Capture:** 2026-10-02, ~15:46–16:05 IST
**Investigation Type:** State capture and freeze only. No code, config, database, or filesystem modifications were made during this investigation. All findings below were obtained by direct, live inspection (`ps`, `systemctl`, `sqlite3`, `git`, `grep`, `pdftotext`) of the running host and the repository at commit `f7dedc8a3f196ac95d43342e3c1e6a17768c64b8` on branch `overhaul-2026-09-23`, not by trusting prior documents.

**Evidence Hierarchy used:** (1) live process/systemd state, (2) `db/applications.db` production tables, (3) current repo files, (4) existing reports 1–4 in `docs/reports/` (treated as unverified claims, re-checked independently wherever cited below), (5) `output/` cached artifacts, (6) `architect-redesign-docs/` planning docs (lowest priority, design intent only).

---

## EXECUTIVE SUMMARY

Hermes is **not stopped**. It is a live, enabled, scheduled system that submitted a real application to a real employer **2.5 hours before this investigation began**, and is scheduled to run again automatically in **~3 hours** unless someone intervenes. Independent re-measurement (not just citing prior reports) confirms that the production database and on-disk cache currently contain verified, employer-facing corruption: 22 of 74 historically submitted applications carry a transposed phone number, 20 carry literal unrendered template placeholders (e.g. `[Your Name]`), and 14 were addressed to a company recorded only as `"Unknown"`. Three already-tailored, not-yet-submitted jobs sit on disk right now with cached cover letters and will be retried by the next scheduled run using those same cached files, unless the pipeline state changes before 19:01:34 IST today. No pre-submission validation gate exists in code — the gate described in `docs/reports/report_4_*.md` is a specification only, never implemented. A newer v2 "engine" architecture (722 queued work-queue rows, 1,177 opportunities marked READY) exists in the database but is structurally disconnected from the live cron path and cannot reach employers in its current state. One of the four pre-existing audit reports (`report_4`) itself contains a fabricated ground-truth claim (LinkedIn/GitHub URLs) that contradicts every other source in the repository — flagged below so it is not propagated.

---

## SYSTEM FREEZE STATUS — Hermes is NOT frozen; it is live and scheduled

Verified directly via `systemctl --user status` / `is-enabled` / `list-timers` at time of capture:

| Unit | Enabled? | Current state | Last run | Next run |
|---|---|---|---|---|
| `hermes.timer` (discover→score→tailor→apply, 08:00/13:00/19:00) | **enabled** | active (waiting) | `hermes.service` ran **today 13:00:20–13:35:56 IST**, exit 0/SUCCESS | **today 19:01:34 IST — 3h10m away at capture time** |
| `hermes-watch.timer` (Gmail reply poll, every 10 min) | **enabled** | active (waiting) | ran 15:49:25–15:50:12 IST, exit 0 | ~15:59:25 IST |
| `hermes-summary.timer` (daily summary, 21:00) | **enabled** | active (waiting) | ran 2026-10-01 21:00:20 | today 21:00:00 |
| `hermes-continuous.service` (24/7 worker variant) | **disabled** | inactive (dead) | — | not scheduled |

No crontab, no `at` queue, no other scheduler found. No `hermes`-related Python process (`pipeline.py`, `apply.py`, `response_watcher.py`) was running at capture time; the run lock `output/hermes.lock` is present but unheld (0 bytes, no holder on `fuser`). No Chromium/Playwright process tied to Hermes's own profile directories (`output/chrome-*-profile/`) is running — the only browser automation process present belongs to this investigation's own tooling (`--user-data-dir /home/virus/.config/hermes-browser`, a Playwright MCP session unrelated to Hermes's apply flow) and the user's ordinary desktop Chrome.

**Conclusion: the system is mid-cycle, not running at this instant, but fully armed. The next automatic execution is a scheduled fact, not a hypothetical.**

---

## ACTIVE EXECUTION PATHS — every path that can reach an employer

All three scheduled units invoke `scripts/run_hermes.sh`, which (confirmed by reading the script) acquires `output/hermes.lock` via `flock`, runs `scripts/preflight.py`, then executes `python3 src/pipeline.py` (oneshot runs) or `src/pipeline.py --continuous` (only for the disabled continuous unit).

`src/pipeline.py` runs stages in order **discover → score → tailor → apply** (confirmed in `run_stages()`), importing `apply.main` from `src/apply.py` for the final stage. `src/apply.py` routes each tailored job to a channel-specific submitter:

- `src/indeed_apply.py` — Indeed's native apply flow (Playwright/DrissionPage browser automation). **This is the channel both of today's submissions went through.**
- `src/ats_apply.py` — Greenhouse / Lever / Ashby public job-board forms.
- `src/direct_form.py` — generic direct-form filler for everything else.
- `src/answers.py` — supplies field values (name, phone, email, links, screening answers) to all three fillers above, reading from `config.yaml`'s `profile:` / `screening_answers:` blocks.

`src/apply.py:270` reads the cover letter for submission with `read_cover_letter(job.get("cover_letter_path"))` — **it reuses the cached `.txt` file written by the tailor stage; it does not regenerate or re-validate the letter at submission time.** This is the mechanism by which a corrupted letter generated hours or days ago can still be submitted today.

**A second, inert path exists:** `src/engine_apply.py` and the `src/engine/` package (Phase 3/4 of `architect-redesign-docs/`) implement an alternate claim/lease-based submission path against the v2 schema (`opportunities`, `work_queue`, `application_attempts`). I confirmed by grep that **neither `src/pipeline.py` nor `src/apply.py` imports anything from `src/engine/` or `engine_apply.py`** — the only "engine" string matches in `apply.py` are docstring prose about a "generic direct-form engine," unrelated code. `config.yaml`'s own comment on the `engine:` block confirms this explicitly: `engine.enabled: false` is not even read by the cron path; flipping it would only unlock a manual, explicitly-invoked call to `engine_apply.py`. **This path cannot reach an employer today without a human manually invoking it.**

`src/response_watcher.py` (via `hermes-watch.timer`) only reads Gmail (`scanned=100 new=0` in its last run) and writes to `responses`/`responses_v2` tables plus desktop notifications — it has no outbound submission capability.

---

## QUEUE INVENTORY

**Legacy `jobs` table** (the table the live cron path actually uses), by status (74,805 total rows):

| Status | Count | Meaning |
|---|---|---|
| `filtered` | 6,171 | excluded pre-scoring, inert |
| `expired` | 1,458 | too old, inert |
| `scored` | **1,202** | **scored and eligible — this is the real pending-application queue; these will be tailored and applied to in future scheduled runs** |
| `skipped` | 728 | inert |
| `unsupported_channel` | 85 | terminal, inert |
| `submitted` | 74 | **already sent to real employers — irreversible** |
| `form_changed` | 50 | terminal failure, inert unless code is fixed |
| `failed` | 15 | terminal |
| `submission_unconfirmed` | 9 | sent, outcome unverified (see below) |
| `blocked_antibot` | 7 | terminal |
| **`tailored`** | **3** | **cached cover letter already written to disk; next apply run will attempt to submit these using the cached file, unchanged** |
| `captcha_required` | 1 | terminal |
| `network_error` | 1 | terminal |

The 3 `tailored` (unsent-but-ready) rows, with their cached cover letter paths on disk right now:

| Job ID | Company | Title | Why it didn't submit today | Cached letter |
|---|---|---|---|---|
| 9677 | `Unknown` | AI Product Builder Intern / Junior Developer | exceeded 6-minute apply budget at step 3/12 | `output/tailored/unknown-ai-product-builder-intern-junior-developer-ai-softwa-9677-cover.txt` |
| 9765 | ICT Digital Solutions | Fullstack Entwickler (m/w/d) | code bug: `KeyError: 'ats'` in the applier | `output/tailored/ict-digital-solutions-fullstack-entwickler-m-w-d-9765-cover.txt` |
| 9777 | CONROO GmbH | Web Developer | code bug: `KeyError: 'ats'` in the applier | `output/tailored/conroo-gmbh-web-developer-full-time-m-w-d-9777-cover.txt` |

Job 9677's cached letter is for a job whose own `company` field is the literal string `"Unknown"` — if a future run successfully applies to it, it will do so addressing an unidentified employer, with whatever letter content is cached.

**Retry mechanism:** confirmed in today's cron log (`output/hermes_cron.log`) — the apply stage re-selects `status='tailored'` jobs each run and attempts submission using the already-cached letter; it does not re-tailor on retry. These three jobs will be retried at the 19:01:34 run today exactly as cached, unless their status changes first.

**v2 engine tables** (structurally present, not reachable by cron — see above): `work_queue` has 722 rows, all `ready_state='READY'`. `opportunities` has 9,569 rows: 1,177 `READY`, 47 `AWAITING_RECONCILIATION`, 68 `COMPLETED`, 21 `MANUAL_REVIEW`, 1,408 `EXPIRED`, 6,848 `OBSERVED`. `application_attempts` has 267 rows, **all `attempt_state='FINISHED'`** — no open leases, no in-flight attempt, no stale claim. `opportunities.application_state='APPLYING'` (mid-flight marker) has **zero rows**. These numbers represent a large amount of *potential* future work encoded in a schema the live system does not yet execute against, not an active risk today.

**Unsent cover letters beyond the 3 above:** the on-disk cache `output/tailored/` currently holds **1,482 generated `.txt` cover letter files total**, most tied to historical (`submitted`, `expired`, `filtered`) jobs rather than pending ones. Independently re-counted (not copied from prior reports):

- **0 of 1,482** contain the correct phone number `9106990136`.
- **167 of 1,482** contain the transposed wrong number `9016990136`.
- **220 of 1,482** contain an unrendered bracket placeholder (`[Your Name]`, `[Company Name]`, `[Hiring Manager]`, `[Phone Number]`, `[Date]`, `[Your Address]`).
- **20 of 1,482** address the employer as the literal word `Unknown`.

These numbers are historical cache contamination, not active risk by themselves — they only become active risk if a currently-`tailored`/`scored` job happens to reuse one of these cached files, or if a human or future process resubmits from this cache.

---

## SOURCE OF TRUTH INVENTORY — every candidate-profile source currently present

| File | Role (as declared or used) | Phone on file | Name/Email/Links |
|---|---|---|---|
| `profile/facts.md` | Declared by `config.yaml`'s own header comment as *"the only source LLMs may use"* for scoring/cover-letters/screening answers | `+91 9106990136` | Saral Banker · saralbanker1@gmail.com · linkedin.com/in/saralbanker · github.com/saralbanker |
| `profile/resume.yaml` | Feeds `scripts/build_resumes.py` → `resumes/resume-{fullstack,backend,ai}.pdf`. Its own header comment: *"Every claim must also appear in profile/facts.md"* | `+91 9106990136` | identical to facts.md |
| `config.yaml` (`profile:` block) | Read by `src/answers.py` to fill live application forms (name/phone/email/links/screening answers) | `+91 9106990136` | identical to facts.md |
| `resumes/resume-{fullstack,backend,ai}.pdf` | Compiled artifacts attached to actual applications; treated by `report_1`–`report_4` as "Tier 1 authoritative" | `+91 9106990136` (verified by `pdftotext` just now — **built Sep 29–30, already correct**) | identical to facts.md |
| `tests/test_truthfulness.py` | Asserts expected answer values, including GitHub URL `https://github.com/saralbanker` | `9106990136` (line 84) | matches facts.md |
| `docs/reports/report_3_*.md`, `report_4_*.md` | Pre-existing audit documents, **not live config** | cite `9016990136` as a historical corrupted variant (correctly, not as their own ground truth) | — |

**All four currently-live config/data sources (`facts.md`, `resume.yaml`, `config.yaml`, built PDFs) agree with each other today** on name, phone, email, LinkedIn, and GitHub. There is **no currently-live divergence between these four files** — the divergence that exists is historical, baked into `output/tailored/` cache artifacts from before `config.yaml` was corrected (confirmed via `git log -p -- config.yaml`: an earlier commit literally hardcoded `phone: "+91 9016990136"`; it was later corrected to `9106990136`, which is what's live now).

**No competing/duplicate profile file was found elsewhere in the repository.** A repo-wide search for alternate phone numbers, "profile"/"facts"/"candidate" files, and old `config*.yaml` copies found only the files above, plus unrelated test fixture phone numbers in `tests/test_ats.py` (dummy employer-ATS test data, not candidate data) and `data/ats_candidates.txt` (a list of target companies, not candidate identity).

**Contradiction found in the audit-report corpus itself (flagged, not trusted):** `docs/reports/report_4_pre_submission_validation_gate.md`, rules `VAL-LK-01`/`VAL-LK-02`, assert the "authoritative" LinkedIn URL is `https://www.linkedin.com/in/saral-banker-46543725b` and GitHub is `https://github.com/saral-banker`. **This matches no other source in the repository.** Every other file — `config.yaml`, `profile/facts.md`, `profile/resume.yaml`, `tests/test_truthfulness.py`, and `report_2`'s own field registry — consistently gives `linkedin.com/in/saralbanker` and `github.com/saralbanker` (no hyphen, no numeric suffix). `report_4` appears to have fabricated these two specific values. **Do not adopt `VAL-LK-01`/`VAL-LK-02` as written** in any future remediation; they would introduce a new corruption, not fix one. This is reported per the instruction to verify every claim and not assume prior audit reports are correct — this is the one place where blind trust would have propagated an error.

---

## AUTHORITATIVE CANDIDATE PROFILE DETERMINATION

Based strictly on current, cross-verified evidence (not on any single report's framing):

**`profile/facts.md` is the correct candidate for sole future canonical source.** Reasoning:
1. It is the only file in the repository whose own text declares itself the constraint boundary for generated content ("The LLM may ONLY state facts written here... If it is not here, the candidate cannot claim it."), including an explicit "Things the candidate does NOT have" negative-claims list that the other files lack.
2. `profile/resume.yaml` already defers to it by its own header comment ("every claim must also appear in profile/facts.md").
3. `config.yaml`'s `profile:`/`screening_answers:` blocks and the built PDFs are currently consistent with it, so naming it canonical requires no immediate reconciliation — it only requires that future edits to `config.yaml`, `resume.yaml`, and `tests/test_truthfulness.py` be driven from `facts.md` rather than edited independently (which is how the historical `9016990136` divergence was introduced: `config.yaml` was hand-edited with a transposed digit at some point in its history, independent of `facts.md`).
4. The PDFs (treated as "Tier 1" by reports 1–4) are *generated output* of `resume.yaml`, not an independent source — treating a build artifact as higher authority than the file that generates it inverts the actual dependency and is why `report_4` could drift (see LinkedIn/GitHub contradiction above) without anyone noticing, since nothing currently diffs the PDF against `facts.md` programmatically.

No change to any file was made to reflect this determination; it is reported as a finding only, per this task's scope.

---

## DEPENDENCY MAP

```
Candidate Identity
├─ profile/facts.md  ───────────────┐  (declared sole LLM-fact source)
├─ profile/resume.yaml  ────────────┤→ scripts/build_resumes.py → resumes/*.pdf (attached to applications)
└─ config.yaml: profile / screening_answers ┐
                                             │
                                             ▼
                              Generation Systems
                  ┌─ src/tailor.py  (cover letters; LLM body via Ollama, fallback
                  │   template_letter() — reads job['company'] directly, no guard
                  │   against "Unknown"; writes output/tailored/*.txt, CACHED)
                  └─ src/answers.py (screening-question / form-field values;
                      regex rules keyed on field label, e.g. line ~76 phone,
                      ~77 linkedin, ~78 github)
                                             │
                                             ▼
                               Validation Systems
                  src/tailor.py: validate_letter() checks —
                    • numbers against allowed_numbers() (facts sheet)
                    • misattributed project numbers
                    • banned skill/domain claims (regex)
                    • overstated years-of-experience (regex)
                    • hype/percentage claims
                    • word count ≤170
                  Does NOT check: bracket placeholders ([...]), curly format
                  strings ({...}), or company name validity.
                  No equivalent gate exists for src/answers.py output.
                  report_4's "Pre-Submission Validation Gate" (7 categories,
                  VAL-ID/TR/PL/CO/SA/LK/CO rules) is a MARKDOWN SPEC ONLY —
                  confirmed absent from all .py source (grep for "PSVG",
                  "validation_failed", "VAL-ID-01" returns zero code matches).
                                             │
                                             ▼
                               Submission Systems
                  src/apply.py — orchestrator; reuses cached cover_letter_path
                    verbatim (line 270), routes by channel to:
                    ├─ src/indeed_apply.py   (used for both of today's submissions)
                    ├─ src/ats_apply.py      (Greenhouse/Lever/Ashby; currently
                    │                         throwing KeyError: 'ats' — active bug)
                    └─ src/direct_form.py
                  [ISOLATED, NOT CONNECTED]: src/engine_apply.py + src/engine/*
                    — v2 claim/lease path against opportunities/work_queue;
                    not imported by pipeline.py or apply.py; config.yaml
                    engine.enabled flag is not even read by the cron path.
                                             │
                                             ▼
                              External Employers
                  Indeed (smartapply.indeed.com), Greenhouse, Lever, Ashby,
                  generic employer ATS/direct-apply forms, plus recruiter
                  phone/email contact derived from the submitted identity data.
```

---

## RESTORATION CHECKPOINT

**Code/config (git):** current `HEAD` is `f7dedc8a3f196ac95d43342e3c1e6a17768c64b8` on branch `overhaul-2026-09-23`. The working tree has **70 changed paths** (per `git status --porcelain`), none of which were touched by this investigation. To restore the exact pre-investigation code/config state at any point: `git stash` (if a rollback of uncommitted edits is ever wanted) or simply note that nothing here needs restoring, since nothing was written. `git diff --stat` shows the 24 previously-tracked modified files (`config.yaml`, `profile/facts.md`, `profile/resume.yaml`, `src/ats_apply.py`, `src/direct_form.py`, `src/discover.py`, `src/indeed_apply.py`, test files, docs) plus numerous new untracked files (the Phase 1–6 `src/engine/` tree, new tests, `scripts/hermes_engine_worker.py`, `scripts/hermes_gmail_watcher.py`, `scripts/migrate_phase1.py`, `architect-redesign-docs/` additions) — this is pre-existing, in-progress work from before this investigation, not something this task should disturb.

**Database:** four pre-existing on-disk backups were found, none created by this investigation:
- `db/backups/applications.db.20261001T152113_pre_phase1.bak` — most recent, taken immediately before the v2 schema migration (`0001_opportunity_model`, applied 2026-10-01 11:05:06).
- `db/backups/applications.db.20260925T040531_pre_crashtest.bak`
- `db/backups/applications.db.20260924T225542.bak`
- `db/backups/applications.db.20260924T160255.bak`
- Plus three older copies under `output/applications.backup-*.db`.

**Important caveat for any future rollback decision:** the most recent backup (`..._pre_phase1.bak`, 2026-10-01 15:21 IST) **predates today's two live submissions** (job 9675 at 08:32 IST and job 9843/Sourcedear at 13:34 IST today) and the Gmail-confirmation responses already recorded for them. Restoring that backup would silently erase Hermes's own record of two applications that were *actually sent to real employers and cannot be unsent* — it would make the database inconsistent with reality, not safer. Any DB rollback must be weighed against that fact; this report takes no position on whether to roll back, only states what each checkpoint actually contains.

**Live system:** the two active-and-armed timers (`hermes.timer`, `hermes-watch.timer`) were left exactly as found — enabled, waiting, next fire 19:01:34 IST and ~15:59 IST respectively. Stopping or disabling them is a system modification and was intentionally not performed under this freeze-only task; it is noted below as a time-sensitive fact for the Go/No-Go decision, not acted on.

---

## RISK REGISTER (discovered during this investigation only)

1. **Live scheduled automation will fire in ~3 hours (19:01:34 IST today) and will attempt to submit the 3 cached `tailored` jobs** (including one addressed to a company recorded as `Unknown`) using their already-generated, unreviewed cover letters, plus proceed through 1,202 `scored` jobs toward further tailor/apply cycles. This is a scheduling fact, not a recommendation to act on it.
2. **Verified historical employer exposure:** of 74 submitted applications, 22 (29.7%) carry a transposed phone number, 20 (27%) carry unrendered template placeholders, 14 (18.9%) were addressed to `"Unknown"` — independently re-counted against the database and cache, matching the figures in `report_1`/`report_3`.
3. **No code-level pre-submission validation exists for company-name or placeholder content.** `src/tailor.py`'s `validate_letter()` only guards against fact-sheet violations, misattributed numbers, banned claims, overstated years, and hype language — confirmed by direct code read, not by trusting `report_3`'s root-cause claim.
4. **Active code bug:** `src/ats_apply.py` currently throws `KeyError: 'ats'` on every attempt for two queued jobs (9765, 9777) as of today's run log — a functional defect independent of the identity-corruption issue, sitting in a file that is currently modified-but-uncommitted (`git status`).
5. **Audit-report self-contradiction:** `report_4`'s VAL-LK-01/VAL-LK-02 rules assert LinkedIn/GitHub "ground truth" values that match no other source in the repository and appear fabricated (detailed above). If adopted uncritically, this would introduce a new validation rule that *rejects the correct URLs and accepts none* — a self-inflicted corruption risk from within the remediation-planning documents.
6. **Retry re-uses cached, unvalidated letters.** `src/apply.py:270` resubmits from `cover_letter_path` without regenerating or re-validating on retry, so any future run touching the 3 pending `tailored` jobs (or any job accidentally reset to `tailored`) will reuse exactly whatever is cached on disk.
7. **`application_attempts.retry_eligible` is `0` for every row, including 50 rows with `outcome='RETRYABLE_FAILURE'`** — a data-quality anomaly in the v2 schema (either the column is never populated, or the retry-eligibility logic never ran). Noted as observed; not investigated further, since the v2 path is not live.
8. **The v2 engine (`work_queue`, `opportunities`, `application_attempts`) holds a large amount of real production data (722 ready queue rows, 1,177 ready opportunities) in a schema not currently exercised by any live code path** — a future `engine.enabled: true` flip or direct manual invocation of `engine_apply.py` would activate a submission path that has not been exercised against the live system and has had no real-world verification, per `config.yaml`'s own comment.

---

## GO / NO-GO ASSESSMENT

**Investigation-only task: COMPLETE.** All items requested — process/scheduler state, queue inventory, active execution paths, cached artifacts, source-of-truth inventory, dependency map, restoration checkpoint — have been captured and independently verified against live evidence rather than assumed from prior documents.

**Remediation readiness: NO-GO as of this capture, for one reason that is purely time-based, not technical** — `hermes.timer` is live and will fire at 19:01:34 IST today. Any remediation plan should account for that fact explicitly (either by completing before then, or by someone outside this task's scope deciding whether to pause the timer). This report does not recommend which; per task constraints, no fix, pause, or configuration change has been proposed or performed.

Once timing is accounted for, the underlying evidence is otherwise internally consistent and well-understood: the four live source-of-truth files agree with each other, the execution paths are fully mapped, the v2 engine path is confirmed inert/isolated, and the specific defect mechanisms (template fallback with no company guard, `validate_letter()` missing placeholder/bracket checks, cached-letter reuse on retry, one fabricated claim inside `report_4`) are each pinned to exact file/line evidence rather than inferred. That is the extent of what this freeze-only task was scoped to produce.
