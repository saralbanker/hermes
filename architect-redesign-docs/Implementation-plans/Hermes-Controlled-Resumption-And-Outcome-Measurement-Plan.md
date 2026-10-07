# Hermes: Controlled Resumption and Outcome Measurement Plan

**Date:** 2026-10-07
**Status:** Conditional GO. Three preconditions are open (§2). The timer is still paused.
**Scope:** Resume production under a fixed configuration and measure hiring outcomes. This plan makes no architecture, qualification-rule, or candidate-package changes.

---

## 0. Verified state on 2026-10-07 (read-only checks, this session)

Every claim in the brief was checked against the live system. Where the brief and the live system differ, the live system wins.

| Check | Result | Matches brief? |
|---|---|---|
| Test suite | `pytest`: **1,279 passed**, 0 failed (29.7 s) | Yes (more than the brief's 1,047+) |
| `hermes.timer` | **inactive (paused)**. Last run 2026-10-07 08:00 | Yes |
| `hermes-watch.timer` (Gmail poll every 10 min) | active | n/a |
| `hermes-summary.timer` (21:00) | active | n/a |
| Daily cap | Was **100/day**. **Set to 25/day this session** (`config.yaml` `limits.other_per_day`, `limits.total_per_day`). `cap_enforcer.py` reads `0/25`. | Fixed |
| Qualification engine | Queue: 263 `scored` rows, all `qual_decision=qualified`, `qual_version=qe-1`. 57 `manual_review` (47 qe-1 `review`, plus 10 older rows). The gate runs at intake (`discover.py:337` → `filters.classify_tier` → `qualify.py`). | Yes |
| **Qualification engine committed?** | **No.** `src/qualify*.py` are untracked, and `filters.py`, `discover.py`, `tailor.py`, `config.yaml` and `profile/resume.yaml` are uncommitted. Production runs from the working tree. | **Gap** |
| Timeout containment | Validation report from 2026-10-06 14:45: all 15 invariants PASS, 0 watchdog fires, 0 duplicates, 0 orphans, 9 SUBMISSION_UNCONFIRMED (protected from retry). A `--once` pass today completed cleanly. | Yes |
| **Validation monitor "running in production"** | **Not running.** No monitor process is alive. The last continuous events are from 2026-10-06 14:44. | **Gap** |
| Queue mix | 263 qualified = **69 core / 194 stretch**. `stretch_share` = 0.15. | See R4 |
| Applications to date | 97 (88 `submitted` + 9 `submission_unconfirmed`). None carry `qual_version`, so **all 97 predate qe-1**. 87 went through Indeed. | n/a |
| Demonstrated throughput | Highest day **11**. Typical days 2–6. **25/day has never been reached.** | See R3 |
| Outcomes to date | 0 interviews, 2 job-linked rejections, 1 ack. `funnel_report.py`: 71 of 97 applications are under 14 days old. | Yes |
| **Response classifier** | `responses` has 3 rows marked `positive`, and **all 3 are spam** (Quora Digest, foundit alerts). | **Gap** (R2) |
| Application views | `funnel_report.py`: "NOT OBSERVABLE (no view events captured)" | Gap (§4.2) |
| Date anomaly | 26 submissions dated **2026-06-24**, three months before the pipeline existed. Their timestamps are unreliable. | Exclude (§4.4) |

---

## 1. Production Resumption Decision

### Verdict: **CONDITIONAL GO**

Resume once the three preconditions in §2 are closed. All three are small and fully reversible. None of them changes Hermes behaviour.

### Reasoning

**For GO:**
1. The safety layer is verified. All 1,279 tests pass. All 15 containment invariants passed in production telemetry. There have been no duplicate submissions, and unconfirmed submissions are protected from retry.
2. The qualification engine is live in the intake path, and every queued row was rescored and tagged `qe-1`. The cohort can therefore be attributed by `qual_version`.
3. More analysis can no longer improve the decision. There are 0 interviews in 97 applications, and 71 of those are too young to judge. Only new, tagged, matured applications can answer the question that matters: does the system produce interviews?
4. The 25/day cap is above the highest volume ever demonstrated (11/day), so it limits risk without becoming the bottleneck.

**Why conditional and not unconditional:**
1. **The production code is uncommitted.** A `git checkout`/`stash` or an accident could silently revert to the old gate in the middle of the cohort. The cohort's configuration must be pinned to a commit before day 0, or "stable configuration" cannot be verified.
2. **The validation monitor is not running**, although the brief says it is. Timeout containment would then go unobserved during the first unattended runs at the new rate.
3. **The response data is contaminated.** All 3 `positive` classifications are spam. Without a counting rule, the first checkpoint would report fake engagement.

**What would make it NO-GO:** a failing test, a containment invariant breach in the monitor's first cycle, or an inability to pin the configuration. None of these applies today.

---

## 2. Hermes Resumption Checklist

### Phase A: Preconditions (before the first run)

- [x] **A1.** Set the daily cap to 25 (`limits.total_per_day: 25`, `other_per_day: 25`). Verified with `python3 src/cap_enforcer.py` → `Total: 0/25`.
- [x] **A2.** Full regression suite: `python3 -m pytest -q` → 1,279 passed.
- [x] **A3.** Containment validation: `python3 scripts/watchdog_validation_monitor.py --once` completes, and the 2026-10-06 report is PASS on all 15 invariants.
- [ ] **A4. Pin the cohort configuration (owner action: commit).** Commit the qe-1 engine and its related changes. Then record the hash:
  `git rev-parse HEAD > output/cohort_qe1_commit.txt`, and `sha256sum config.yaml profile/resume.yaml resumes/*.pdf >> output/cohort_qe1_commit.txt`.
  *Why:* this fingerprint is the "stable configuration" the observation period depends on.
- [ ] **A5. Start the validation monitor persistently.** Run it continuously alongside the timer, for example `nohup python3 scripts/watchdog_validation_monitor.py --interval 15 >> output/monitor.log 2>&1 &`, or as a systemd user service. Confirm with `pgrep -af watchdog_validation_monitor`.
- [ ] **A6. Adopt the counting rule (§4.3)** before the first checkpoint: only job-linked, human-verified responses count. No code change is needed.
- [ ] **A7. Back up the DB:** `cp db/applications.db output/applications.backup-cohort-start-$(date +%Y%m%dT%H%M%S).db`.

### Phase B: Resume

- [ ] **B1.** Dry run: `scripts/run_hermes.sh --dry-run --limit 3`. Expect qe-1 rows to be selected, no submissions, and a clean exit.
- [ ] **B2.** Supervised first live run: `scripts/run_hermes.sh --limit 5`, watched with `scripts/hermes-status.sh`. Expect 5 or fewer submissions, each with evidence, no new `submission_unconfirmed` spike, and monitor events in `output/watchdog_validation_events.jsonl`.
- [ ] **B3.** Check that new submissions are tagged:
  `sqlite3 db/applications.db "SELECT qual_version, qual_decision, COUNT(*) FROM jobs WHERE status='submitted' AND applied_at >= '<day0>' GROUP BY 1,2"`. Expect `qe-1 | qualified`. **Stop if any row shows NULL.**
- [ ] **B4.** Enable the schedule: `systemctl --user start hermes.timer`, then confirm the next trigger with `systemctl --user list-timers 'hermes*'`.
- [ ] **B5.** Record **day 0** (the first live-submission date) in `output/cohort_qe1_commit.txt`.

### Phase C: First 72 hours

- [ ] **C1.** Daily: `scripts/hermes-status.sh`. Check submissions per day (25 or fewer), the outcome mix, and that no channel breaker is open.
- [ ] **C2.** Daily: `python3 scripts/watchdog_validation_report.py`. Expect 0 invariant breaches.
- [ ] **C3.** Day 3: re-run `pytest` and confirm the `config.yaml` sha256 still matches A4.

### Kill switches (stop with `systemctl --user stop hermes.timer`)

| Trigger | Threshold |
|---|---|
| Duplicate submission | Any (≥1) |
| Containment invariant breach (Q08–Q15) | Any |
| `submission_unconfirmed` rate | >10% of attempts in a day, with at least 10 attempts that day |
| Indeed account warning, restriction, or forced re-verification | Any |
| An untruthful claim in a submitted answer or letter | Any (critical defect) |
| Submissions without a `qual_version` | Any |

A kill switch is the **only** condition that allows a change during the observation period. Fix the defect, record it in the cohort log, and treat applications after the fix as a separate sub-cohort.

---

## 3. Observation rules (what stays frozen)

Frozen until the final read (§4.5): qualification rules and thresholds, `config.yaml` (apart from a kill-switch fix), `profile/resume.yaml`, the resume PDFs, cover-letter templates and prompts, screening answers, channel mix, and the 25/day cap.

Allowed: running the pipeline, collecting outcome data by hand, and releasing manual-review jobs. A released job is tagged as a separate arm (`qual_decision=review`) and is never pooled with `qualified`.

---

## 4. Outcome Measurement Framework

### 4.1 Cohort definitions

| Cohort | Definition | Use |
|---|---|---|
| **Q1 (treatment)** | `status IN ('submitted','submission_unconfirmed') AND qual_version='qe-1' AND applied_at >= day0` | Primary cohort |
| **B0 (baseline)** | The 97 earlier applications, excluding the 26 dated 2026-06-24 → **n=71 usable** | Context only. Not a control (see 4.4) |
| **MR (manual-review arm)** | Released `review` jobs | Kept separate, descriptive only |

An application is **mature** once it is 14 or more days old. Rates are computed **only over mature applications**. A missing signal on a young application is *pending*, not negative.

### 4.2 Metrics to collect

| # | Metric | Definition (strict) | Source | Status today |
|---|---|---|---|---|
| M1 | Applications submitted | Rows in Q1, by day, channel, tier, and confidence band | DB (`funnel_report.py`) | Automated |
| M2 | Submission integrity | Share of `submission_unconfirmed` and failure states among attempts | DB + monitor | Automated |
| M3 | **Resume / application views** | An employer viewed the application | **Indeed "My jobs" status** ("Viewed"/"Not selected"), recorded by hand weekly | **Not captured. A manual log is required.** |
| M4 | **Genuine responses** | A job-linked message from the employer or its ATS about *this* application, excluding Indeed auto-acks, digests, alerts, and marketing | Gmail + `responses.job_url` + manual verification | Partly automated. **The classifier is unreliable (R2).** |
| M5 | Rejections | An explicit "not moving forward" | Same as M4 | Partly automated |
| M6 | **Recruiter conversations** | A two-way human exchange (the candidate replied and a human answered) by email, phone, WhatsApp, or Indeed messages | **Manual log** | Not captured |
| M7 | **Interview requests** | An explicit invitation to a scheduled call, interview, or assessment with a human step. A take-home assignment counts, and is logged separately as M7a. | **Manual log**, cross-checked against Gmail | Not captured |
| M8 | Interview rate per 100 | 100 × M7 / mature Q1 | Derived | n/a |
| M9 | Time to first signal | Days from `applied_at` to the first M4/M5/M7 | Derived | n/a |
| M10 | Signals by qual confidence band and tier | M3–M7 split by `qual_confidence` band and core/stretch | `funnel_report.py` | Automated grouping |

**Manual outcome log.** Every M3, M6, and M7 event goes into one append-only file (`output/outcomes_manual.csv`): `date, job_url, company, event (view|response|rejection|conversation|interview_request|assessment), channel (email|phone|whatsapp|indeed_msg|linkedin), evidence_ref, notes`. Each row must reference a job in the DB. Phone and WhatsApp contacts that cannot be tied to a job are logged with `job_url=UNLINKED` and reported separately, never dropped.

### 4.3 Counting rules (prevent false signals)

1. An event counts only if it is **linked to a specific Q1 job** and **verified by a human** (the owner reads the message).
2. Digests, job alerts, marketing, "you appear in searches" messages, and Indeed auto-acknowledgements **never** count as responses. The `responses.classification='positive'` label is **not trusted** (3 of 3 are spam).
3. A response is not a conversation, and a conversation is not an interview. Each event goes into exactly one row of the strict hierarchy M4 ⊂ M6 ⊂ M7 by its highest stage, and the lower stages are counted cumulatively.
4. A view (M3) is a screen-stage signal only. It says nothing about candidate quality.
5. A missing signal is never a negative outcome. It is either *pending* (under 14 days) or *no signal* (14 days or more).

### 4.4 Minimum sample sizes

**What the data can and cannot show.** At the observed outcome levels (about 0–3 per 100), distinguishing a 1% interview rate from a 5% one with 80% power (one-sided, α=0.05) needs about **220 mature applications per arm**. The baseline has 71 usable applications and cannot be extended. **A statistically valid old-versus-new comparison is not achievable in 2–3 weeks.** Because the qe-1 cohort also ships a changed resume and cover-letter template (R1), even a large difference could not be attributed to qualification alone.

The plan therefore asks questions it *can* answer:

| Question | Minimum mature Q1 sample | Basis |
|---|---|---|
| Any metric reported as a per-100 rate | **n ≥ 30** (`funnel_report.py` already enforces this) | Below 30, report raw counts only |
| "Is the screen stage working?" (views, M3) | **n ≥ 50** | Views are common enough to show at 50 |
| "Are responses meaningfully non-zero?" (M4) | **n ≥ 100** | With 0 events in 100, the 95% upper bound is 3% (rule of three) |
| **Interview-rate verdict (M8)** | **n ≥ 150** | With 0 interviews in 150, the 95% upper bound is **2.0 per 100**, which is enough to call failure |
| Core vs stretch, or confidence-band comparison | **≥ 50 per subgroup** | Otherwise descriptive only |

**Feasibility:** demonstrated throughput is 2–11 per day. Twenty-one days at about 8 per day gives about 170 applications. Only those older than 14 days are mature. By the end of week 3, about **50–60 will be mature**, so **the interview verdict needs a final read on about day 35**, two weeks after applications stop counting toward the window.

### 4.5 Review cadence

All counts come from `funnel_report.py` plus the manual log. The checklist is the same each week: kill switches, the integrity metrics M1–M2, and the outcome metrics M3–M8 with the n beside every rate.

| Checkpoint | Date (if day 0 = 2026-10-08) | Mature Q1 expected | Decision allowed |
|---|---|---|---|
| **W1** | 2026-10-15 | ~0 | Operational only: throughput, integrity, kill switches. **No outcome conclusions.** |
| **W2** | 2026-10-22 | ~0–10 | Operational and data-quality review: is the manual log being filled in, and are the counting rules applied? Raw counts only. |
| **W3** | 2026-10-29 | ~50–60 | Screen-stage read (M3 views, M4 raw counts). An early **failure** call is possible only on views (§4.6). |
| **Final** | 2026-11-12 (day 35) | ~150–170 | Interview-rate verdict (M8) and response verdict (M4/M6). Decides which roadmap item (§5) to start. |

If day 0 slips, every date shifts by the same amount.

### 4.6 Success and failure criteria

These thresholds are **owner-set decision thresholds** for this candidate and market. They are not industry benchmarks, and none comes from Hermes outcome data, which does not exist yet. Each applies only at or above the stated minimum n of mature Q1 applications.

| Metric | Min n | **Success** | **Inconclusive** | **Failure** | Failure points to… |
|---|---|---|---|---|---|
| M3 Views (Indeed "Viewed") | 50 | ≥ 30% viewed | 10–30% | < 10% viewed | Visibility or timing (applying to stale or saturated posts, ATS filtering). Not the resume content. |
| M4 Genuine responses (incl. rejections) | 100 | ≥ 8 / 100 | 2–8 | < 2 / 100 | The screen stage (resume positioning, knockout answers) |
| M6 Recruiter conversations | 100 | ≥ 3 / 100 | 1–3 | 0 / 100 | Response handling or positioning |
| M7 Interview requests | 150 | ≥ 2 absolute **and** ≥ 1.5 / 100 | 1 request | 0 / 150 (95% upper bound ≈ 2/100) | The candidate package, not targeting (if views and responses are healthy) |
| M8 Interviews per 100 | 150 | ≥ 1.5 | 0.5–1.5 | 0 | As for M7 |

**Interpretation (the forbidden-assumption guards):**
- Success on M7/M8 shows that *the current bundle* (qe-1 targeting, the current package, Indeed India) produces interviews. It does **not** prove that qe-1 beats the old gate.
- Failure on M7 alongside healthy M3/M4 points at the late-funnel package (screening answers, response handling). It does not point at qualification.
- Failure on M3 shows the problem is upstream of anything the candidate package controls.
- "Inconclusive" means: extend the window at the same configuration. Do not change anything.

---

## 5. Parallel Side-Quest Roadmap (investigate only. Implement nothing during the observation window.)

Each item is an *investigation*: gather evidence and draft a proposal. Nothing ships until the final read. Ranked by expected ROI (impact × confidence ÷ effort).

| Rank | Item | What to investigate | Impact | Effort | Evidence confidence |
|---|---|---|---|---|---|
| **1** | **Recruiter reply handling** | Today a human reply arrives by Gmail notification and is handled ad hoc. Draft reply templates for scheduling, salary, notice period, and "tell us about yourself". Set a same-day response SLA. Define the channel log for phone and WhatsApp. **This also feeds M6/M7 measurement directly.** | High: a missed or slow reply wastes the rarest event in the funnel | Low (templates and a checklist) | **Medium.** It is structural: each reply is high-value. Only 2–3 genuine replies so far, so there are no reply-handling failures on record yet. |
| **2** | **Screening answers** | Audit the answers actually submitted to Indeed. Knockout questions ("years of X", degree, CTC) get automatic rejections. `years_experience_total: 1` and `has_bachelor: false` are truthful, but check whether the *phrasing* (free-text fields) is optimal. Cross-reference against the 2 rejections. | High: knockouts fail silently, before any human sees the resume | Low–Medium | **Medium.** Indeed knockout filtering is known to exist. Whether it affects these specific applications is unmeasured. |
| **3** | **Resume positioning** | 1 year paid plus 4 years hands-on, with no degree: is the top third making the strongest truthful case for the roles qe-1 accepts? Compare the three PDFs (`ai/backend/fullstack`) against the 69 core-queue postings. Prepare A/B variants for **after** the read. | High if M3 (views) is healthy but M4 fails | Medium | **Low–Medium.** No outcome data per resume variant yet. |
| **4** | **Portfolio / public proof** | Check whether AWIS (Go, 773 tests) and the 70k-line RAG platform have a public, verifiable artifact: repo, demo, or short write-up. Unverifiable claims weaken the screen for a no-degree candidate. | Medium–High at the conversation and interview stage | Medium–High | **Low.** Plausible mechanism, no funnel evidence. |
| **5** | **Cover letters** | Already reworked (a truthfulness fix in `tailor.py` and `why_interested_template`). Many Indeed flows ignore cover letters. Measure only: what share of Q1 applications attached one, and does attachment correlate with M4 (descriptive, n≥50 per group)? | Low–Medium | Low (measurement only) | **Low.** There is no evidence cover letters are the bottleneck, and the brief forbids assuming so. |

**Trigger mapping at the final read:** M3 failure → re-examine targeting freshness and channel (not a qualification redesign). M3 healthy, M4 failure → items 2 and 3. M4 healthy, M6/M7 failure → items 1 and 4.

---

## 6. Specialized Agent Recommendation

**Agent type:** `Plan` (the specialized design agent). **Model:** `sonnet` (Sonnet 5.5).

**Why this agent:**
- **Specialized, not general-purpose.** `Plan` is the design and strategy agent. Its tools are **read-only**: it cannot Edit, Write, or run notebooks. That mechanically enforces "must not redesign Hermes architecture". The agent *cannot* change code, config, or qualification rules. It can only read the DB, logs, and reports, then return analysis.
- **Sonnet over Opus:** the task is structured analysis of counts against pre-registered thresholds, not open-ended architecture. Sonnet handles this well at a fraction of Opus's cost, and matches the standing preference for Sonnet subagents.
- **Sonnet over Haiku:** the work needs careful statistical judgement: small-n intervals, cohort hygiene, telling spam from genuine replies, and confound reasoning. Haiku is more likely to over-read tiny counts. That is the exact failure this plan guards against.

**Exact task (one agent, reused across checkpoints through SendMessage):**

> You are the hiring-funnel measurement analyst for Hermes. Your scope is outcome measurement and experimental design ONLY. You must not propose architecture, qualification-rule, or pipeline changes.
> At each checkpoint (W1, W2, W3, Final), using `Hermes-Controlled-Resumption-And-Outcome-Measurement-Plan.md` §4 as the pre-registered protocol:
> 1. Run `python3 scripts/funnel_report.py` and read `output/outcomes_manual.csv`, `db/applications.db` (read-only), and `output/watchdog_validation_report.md`.
> 2. Audit data integrity: Q1 rows with no `qual_version`, unlinked or unverified responses, spam counted as a response, rows dated outside the window, and missing manual-log entries for job-linked Gmail replies.
> 3. Report every M1–M10 metric as a raw count plus n plus maturity. Give a per-100 rate only where §4.4's minimum n is met, with a 95% interval (Wilson, or rule of three for zero counts).
> 4. Classify each metric as Success, Inconclusive, Failure, or "Below min n" against §4.6 thresholds. Never extrapolate below the minimum n.
> 5. Flag any confound or threat to validity (Risk Register §7).
> Output: a checkpoint report under 400 words. Do not recommend optimizations before the Final checkpoint.

**When it runs:** first at W1 (2026-10-15), then reused at W2, W3, and Final. There is no standing cost between checkpoints.

---

## 7. Risk Register: threats that could invalidate conclusions

| # | Risk | Likelihood | Effect on conclusions | Mitigation |
|---|---|---|---|---|
| **R1** | **Bundled change (confound).** The qe-1 cohort also ships changed `profile/resume.yaml`, a changed `tailor.py` cover-letter logic, and a revised `why_interested_template`. | Certain | Any change in outcomes **cannot be attributed to qualification alone** | Frame every conclusion as "the current bundle". Freeze everything (§3). Attribution needs a later controlled variant test. |
| **R2** | **Response classifier mislabels spam as positive** (3 of 3 `positive` rows are Quora/foundit) | Certain (observed) | Inflated M4 and fake engagement | Counting rules §4.3. Only job-linked, human-verified events count. |
| **R3** | **Throughput far below the cap** (highest day 11, typical 2–6) | High | Mature n is under 150 by day 35, so the interview verdict slips | Report against the minimum n, never the calendar. Extend the window at the same configuration rather than lowering thresholds. |
| **R4** | **Queue skew: 194 stretch vs 69 core** with `stretch_share` 0.15. Core supply depends on fresh discovery. | High | The cohort mix drifts if core runs dry, making week-to-week numbers incomparable | Track M10 by tier every checkpoint. Never pool core and stretch rates when the mix shifts by more than 15 points. |
| **R5** | **Off-Gmail outcomes not captured** (phone, WhatsApp, Indeed messages) | High | M6/M7 undercounted. A missing signal looks like a negative. | Manual outcome log (§4.2). Unlinked contacts are logged, never dropped. |
| **R6** | **Uncommitted production code** | Medium | Silent reversion to the old gate mid-cohort | Precondition A4 (commit plus config fingerprint), and the day-3 hash check (C3) |
| **R7** | **Validation monitor not running** | Was certain, fixed by A5 | Containment regressions go unobserved | Precondition A5 and daily report check (C2) |
| **R8** | **Maturity lag:** Indian employer response times can exceed 14 days | Medium | Early checkpoints understate outcomes | Separate pending from no-signal. Final read at day 35. Late signals are back-filled into the cohort. |
| **R9** | **Market seasonality** (Diwali falls in this window) | Medium | Lower response rates unrelated to Hermes | Note the calendar in each checkpoint. Treat an Inconclusive result in this window as "extend", never "fail". |
| **R10** | **Baseline unusable as a control** (n=71 usable, mostly unmatured, a different package, 26 bad timestamps) | Certain | No valid old-versus-new claim | B0 is context only (§4.1). No comparative claim is made. |

---

## 8. Final Recommendation

1. **Resume Hermes now, conditionally.** Close A4 (commit and fingerprint), A5 (persistent monitor), and A6 (counting rule). Then run B1–B5. The cap is already 25/day and the regression suite is green.
2. **Freeze everything for the observation window** (§3). The only allowed change is a fix for a proven kill-switch defect.
3. **Collect evidence the system does not yet capture.** The manual outcome log (views, conversations, interview requests) is the most important new activity. Without it, M3, M6, and M7 cannot be measured at all.
4. **Judge against minimum n, not the calendar.** At realistic throughput, the interview-rate verdict comes at about day 35 (around 2026-11-12), not at week 3. Week 3 can only judge the screen stage.
5. **Expect a bundle verdict, not a qualification verdict.** The outcome will tell whether the *current system* produces interviews. It will not prove qe-1 beats the old gate (R1, R10).
6. **In parallel, do investigation only:** reply handling first, then screening answers. Both are cheap, and both improve measurement as well as outcomes. Nothing ships before the final read.
7. **Use one Plan/Sonnet measurement agent**, invoked at each checkpoint and reused through SendMessage.
