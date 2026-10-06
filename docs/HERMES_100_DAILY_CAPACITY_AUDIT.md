# Hermes 100 Confirmed Applications/Day Mechanical Capacity Audit

**Date:** 2026-10-04  
**Audit Scope:** Read-only mechanical verification of repository logic, database state, configuration, and systemd units.  
**State:** Scheduler disabled (`hermes.timer`, `hermes.service`, `hermes-continuous.service` inactive). Layer 1 validation gate active.  

---

## 1. Final Verdict

# ❌ VERDICT: NO (Internally Impossible)

Hermes cannot mechanically achieve 100 confirmed applications/day under its current logic, database reality, and external platform constraints.

### Core Determinative Findings:
1. **Supply Deficit (1.6% of Required Volume):** Daily discovery yields ~207.4 raw jobs. After location/seniority filters (52.5% loss) and scoring thresholds (79.5% loss), only **20.3 qualifying jobs/day** enter the queue across all boards combined. Lifetime discovery-to-submission conversion is **0.76%** (78 confirmed / 10,211 discovered). Supporting 100 confirmed submissions/day requires **13,158 discovered jobs/day**.
2. **Platform Monoculture (8 of 9 Platforms Yield 0 Submissions):**
   - **Ashby:** Hard-blocked in code (`src/apply.py:177`) with `BLOCKED_ANTIBOT`.
   - **LinkedIn:** Hard-blocked in config (`limits.linkedin_per_day: 0`) and code (`src/discover.py:282`).
   - **Wellfound:** Omitted from config (`config.yaml:search.boards`).
   - **Himalayas:** 100% failure rate; all redirects hit mandatory talent account walls (`src/redirect_resolver.py:108` → `UNSUPPORTED_CHANNEL`).
   - **Arbeitnow, WWR, RemoteOK:** 0% confirmation rate due to ATS account walls, Ashby redirects, and unhandled `KeyError: 'ats'` runtime crashes (`src/apply.py:114`).
   - **Lever:** Discovered 152 jobs all-time; 0 qualifying scores, 0 submissions.
   - **Greenhouse:** Discovered 4,549 jobs all-time; 94.5% filtered by location; 1 lifetime submission (0.02%), 0 active qualifying.
   - **Indeed:** The **only** functional channel in production (77 of 78 lifetime submissions). Recent 7-day average: **4.0 confirmed submissions/day** (peak 11).
3. **Serial Execution Budget Ceiling:** Single-threaded browser automation (`src/apply.py:12`), 20–45s inter-job delays (`src/apply.py:425`), and a 360s job budget (`src/indeed_apply.py:45`). Scheduled mode (3 runs × 150 min = 450 min/day) with a 20% attempt-to-submit success rate caps throughput at **~25–30 submissions/day** even with infinite supply. Overcoming the 80% failure rate to reach 100 submissions requires 500 attempts (**29.2 hours of serial execution/day**).

---

## 2. Platform Capacity Matrix

| Platform | Ingestion Capacity | Qualifying Supply / Day | Application Concurrency & Delays | Confirmed Submissions (All-Time / 7-Day) | Principal Bottleneck (`file:function:line`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Indeed** | 14 queries × 40 limit (`results_wanted: 40`, `hours_old: 72`). ~190 raw/run. | ~10–15 qualifying jobs/day (score ≥6.5). Active pool: 15. | Concurrency: 1 (Xvfb headful Chrome). Delay: 20–45s. Timeout: 360s. | **77** all-time / **28** in 7d (**4.0/day**, peak 11) | Supply exhaustion: Daily new fresher/junior roles in India/Remote yield <15 qualifying jobs/day. |
| **Greenhouse** | 85 companies (`data/ats_companies.yaml`). 4,549 discovered all-time. | 0 active qualifying in DB (4,300 filtered for US/EU location). | Concurrency: 1. `ats_apply.py:run_ats_apply`. Delay: 20–45s. | **1** all-time (Cloudflare SWE on 2026-09-25) / **0** in 7d | `src/filters.py:287` / `src/geo.py:64`: 94.5% eliminated by location filters (SF/NYC on-site or US-only remote). |
| **Lever** | 23 companies (`data/ats_companies.yaml`). 152 discovered all-time. | 0 active qualifying in DB (max score 6.0 vs 6.5 floor). | Concurrency: 1. `ats_apply.py:_apply_lever`. Delay: 20–45s. | **0** all-time / **0** in 7d | `src/score.py:69` & `src/tailor.py:280`: 0% qualifying scores above threshold. |
| **Ashby** | 70 companies (`data/ats_companies.yaml`). 1,672 discovered all-time. | 1 active qualifying in DB. | **0 (Hard-blocked)**. Returns `BLOCKED_ANTIBOT` immediately. | **0** all-time / **0** in 7d | `src/apply.py:177`: `if channel == S.CH_ASHBY: return ApplyResult(BLOCKED_ANTIBOT, "ashby disabled...")`. |
| **Himalayas** | Search API (`q=role`, `country=India`). 709 discovered all-time. | 0 active qualifying in DB (426 scored, avg 3.97). | Concurrency: 1 via `src/redirect_resolver.py`. | **0** all-time / **0** in 7d | `src/redirect_resolver.py:108` & `src/apply.py:133`: Redirects hit `himalayas.app/signup/talent` (`account_required` → `UNSUPPORTED_CHANNEL`). |
| **Arbeitnow** | Public API. 176 discovered all-time; ~22 raw/run. | 4 active qualifying in DB. | Concurrency: 1 via `src/redirect_resolver.py`. | **0** all-time / **0** in 7d | `src/apply.py:114`: Crash `KeyError: 'ats'` when resolver output lacks `'ats'` key; remaining hit Ashby bot block. |
| **WWR** | 4 RSS feeds. 86 discovered all-time; ~69 raw/run. | 0 active qualifying in DB. | Concurrency: 1 via `src/redirect_resolver.py`. | **0** all-time / **0** in 7d | `src/redirect_resolver.py:108`: Hits `weworkremotely.com` account wall or resolves to blocked Ashby. |
| **RemoteOK** | Public API. 10 discovered all-time; ~9 raw/run. | 0 active qualifying in DB. | Concurrency: 1 via `src/redirect_resolver.py`. | **0** all-time / **0** in 7d | `src/redirect_resolver.py:108`: Hits account wall (`account_required:remoteok.com`). |
| **Remotive** | Public API. 66 discovered all-time; ~18 raw/run. | 0 active qualifying in DB (all scores ≤6.0). | Concurrency: 1 via `src/redirect_resolver.py`. | **0** all-time / **0** in 7d | `src/score.py:69`: 0% qualifying scores; heavy geographic filter loss. |
| **LinkedIn** | Python-jobspy (disabled). | 0 (622 marked `backlog:linkedin_disabled`). | **0 (Hard-blocked)**. Capped at 0 in config to prevent permanent ban. | **0** all-time / **0** in 7d | `config.yaml:76`: `limits.linkedin_per_day: 0`; `src/discover.py:282`: `"linkedin": "none"`. |
| **Wellfound** | Scraper in `src/sources_wellfound.py`. | 0 (Unconfigured). | **0 (Hard-blocked)**. Deliberately omitted from `search.boards`. | **0** all-time / **0** in 7d | `config.yaml:37-44` & `src/discover.py:12-22`: Excluded because postings require Wellfound candidate accounts. |

---

## 3. Quantitative Pipeline Funnel

### All-Time Funnel (10,211 Total Discovered Jobs in `jobs`)
```
[10,211] Discovered Raw Jobs
   ├── [6,336] (62.1%) Filtered (Location, Non-Eng Title, Seniority >8y, Salary <25k INR)
   ├── [1,460] (14.3%) Expired (>21 days old or closed on site)
   └── [  728] ( 7.1%) Skipped (LinkedIn disabled: 622; Cross-board duplicates: 106)
[ 3,105] Scored Jobs (Evaluated by embedding + LLM)
   └── [1,758] (56.6%) Score Rejected (<6.5 for Core, <7.5 for Stretch)
[ 1,347] Qualifying Scored Jobs (Ever met score floor)
   ├── [  536] Skipped post-scoring (508 backlog LinkedIn, 28 duplicates)
   ├── [  494] Expired in backlog before slots opened
   ├── [  130] Unsupported Channel (Himalayas/WWR/RemoteOK account walls)
   ├── [   41] Form Changed (Unanswerable questions, novel DOM structures)
   ├── [   49] Other Failures / Blocked (Ashby bot blocks, timeouts, crashes)
   ├── [   20] Currently Active Qualifying Scored Pool
   ├── [    2] Currently Tailored in Active Queue
   └── [    3] Validation Failed / Manual Review (Company="Unknown", retired projects)
[   315] Attempted Jobs (Dispatched to browser applier)
   └── [   78] Confirmed Submitted (77 Indeed, 1 Greenhouse)
```
- **Discovered → Confirmed Conversion Rate:** **0.76%** (1 in 131 jobs).
- **Attempted → Confirmed Conversion Rate:** **24.8%** (1 in 4.0 attempts).

### Recent 7-Day Window Funnel (2026-09-28 to 2026-10-04)
- **Raw Discovered / Day:** 207.4
- **Passed Filters / Day:** 98.6 (52.5% loss)
- **Scored / Day:** 99.0
- **Qualifying / Day:** 20.3 (79.5% loss at score thresholds)
- **Attempted / Day:** 20.0
- **Confirmed Submitted / Day:** **4.0** (all 28 submissions on Indeed)
- **Recent 7-Day Attempt Breakdown (140 attempts):**
  - `unsupported_channel`: 76 (54.3% — Himalayas account walls)
  - `submitted`: 28 (20.0% — Indeed confirmations)
  - `failed`: 10 (7.1% — 7 `KeyError: 'ats'`, 3 timeouts)
  - `form_changed`: 11 (7.9% — unanswerable custom questions)
  - `blocked_antibot` / `expired` / `network_error`: 15 (10.7%)

---

## 4. Root Cause Pinpoints

| # | Bottleneck | File & Function | Exact Code Pinpoint | Impact |
| :- | :--- | :--- | :--- | :--- |
| **1** | **Ingestion Deficit & Filter Loss** | `src/filters.py:passes_filters` `src/geo.py:is_location_eligible` | `config.yaml:16,25`: `willing_to_relocate: false`, `radius_km: 20`<br>`config.yaml:62,68`: `min_score: 6.5`, `stretch_min_score: 7.5` | 62.1% filtered at discovery; 79.5% of scored jobs rejected. Net qualifying supply capped at ~20 jobs/day. |
| **2** | **Ashby Hard Block** | `src/apply.py:route` | `src/apply.py:176-177`: `if channel == S.CH_ASHBY: return ApplyResult(BLOCKED_ANTIBOT, "ashby disabled...")` | Hardcoded code disable. 0 of 1,672 Ashby jobs can execute. |
| **3** | **Himalayas Account Wall** | `src/redirect_resolver.py:_account_wall`<br>`src/apply.py:_apply_resolved_target` | `src/redirect_resolver.py:108`: `same_host and bool(SIGNUP_WALL_RE.search(...))` | 76 of 76 recent Himalayas attempts failed as `unsupported_channel`. 0 confirmed submissions all-time. |
| **4** | **Arbeitnow Parser Defect** | `src/apply.py:_apply_resolved_target` | `src/apply.py:114`: `meta = json.loads(target["ats_meta"])`<br>`job["apply_channel"] = meta["ats"]` | Runtime crash `KeyError: 'ats'` on resolved listings lacking the `'ats'` key. 0 confirmed submissions all-time. |
| **5** | **Tailoring Batch Choke** | `src/tailor.py:select_jobs` | `src/tailor.py:285`: `cap = max(0, cfg["scoring"].get("max_tailor_per_run", 60) - already_queued)` | Logic limits active tailored pool to 60 jobs per run. |
| **6** | **Serial Execution Bottleneck** | `src/apply.py:run_queue`<br>`scripts/run_hermes.sh` | `src/apply.py:12`: Concurrency = 1<br>`src/apply.py:425`: `time.sleep(random.uniform(20, 45))`<br>`scripts/run_hermes.sh:30`: `flock -n 9` | Mean cycle time is 210s/attempt. Single-threaded process cannot attempt >411 jobs in 24 hours. |
| **7** | **Metadata Gate Rejections** | `src/submission_gate.py:run_submission_gate`<br>`src/apply.py:apply_one` | `src/submission_gate.py:228`: Placeholder company check (`Unknown`)<br>`src/submission_gate.py:270`: Retired project check (`HeatMax`) | Fail-closed Layer 1 pre-submission gate blocks 100% of malformed listings or stale covers before browser dispatch. |

---

## 5. 100/Day Capacity Math

### A. Supply Arithmetic (The Fundamental Blocker)
- Observed all-time conversion: $\frac{78 \text{ confirmed}}{10,211 \text{ discovered}} = \mathbf{0.76\%}$
- Required raw discovery for 100 confirmed/day:
  $$\frac{100}{0.0076} = \mathbf{13,158 \text{ new raw jobs/day}}$$
- Observed daily discovery rate: **207.4 raw jobs/day**.
- **Supply Deficit: 63.4x**.

### B. Indeed Specific Supply Math
- Indeed is the sole producing channel (77 of 78 submissions).
- Indeed attempt-to-submit conversion: ~26.6%.
- Required qualifying Indeed jobs for 100 confirmed/day: $\frac{100}{0.266} = \mathbf{376 \text{ qualifying jobs/day}}$.
- Observed Indeed qualifying rate: 10.5% of raw listings.
- Required raw Indeed discovery: $\frac{376}{0.105} = \mathbf{3,580 \text{ raw Indeed jobs/day}}$.
- Observed raw Indeed discovery: **~190 jobs/run** (yielding <15 qualifying jobs/day).

### C. Execution Time Arithmetic
- Mean cycle per attempt: $30\text{s (nav)} + 120\text{s (fill)} + 27.5\text{s (submit)} + 32.5\text{s (delay)} = \mathbf{210 \text{ seconds (3.5 minutes)}}$.
- At observed 20% attempt-to-submit conversion, 100 confirmed submissions require:
  $$\frac{100}{0.20} = \mathbf{500 \text{ attempts/day}}$$
- Serial time required:
  $$500 \times 210 \text{ s} = 105,000 \text{ seconds} = \mathbf{29.17 \text{ hours/day}}$$
- Even under 24/7 continuous operation, a single-threaded worker cannot exceed 411 attempts ($411 \times 20\% = \mathbf{82 \text{ submissions/day}}$). Under scheduled systemd mode (3 runs × 150 min = 450 min), theoretical capacity is capped at $\frac{450}{3.5} \times 20\% = \mathbf{25.7 \text{ submissions/day}}$.

---

## 6. Production Readiness Conclusion

### Can re-enabling Hermes realistically move toward 100 confirmed applications/day based solely on internal evidence?

# ⛔ CONCLUSION: NO

Re-enabling `hermes.timer` or `hermes-continuous.service` will immediately return the system to steady-state equilibrium at **~3 to 6 confirmed applications/day**, exactly matching historical operational records.

1. **Backlog Starvation:** The active production database contains only **20 qualifying scored jobs** across all platforms (15 Indeed, 4 Arbeitnow, 1 Ashby). Processing this pool yields ~3–4 submissions before the queue starves.
2. **Channel Dead-Ends:** 8 of the 9 configured platforms are functionally dead ends for submission due to code disables (`apply.py:177`), third-party account walls (`redirect_resolver.py:108`), parser exceptions (`apply.py:114`), or zero qualifying scores.
3. **Execution Limits:** The single-threaded browser model with human delays cannot execute the transaction volume necessary to reach 100 confirmed submissions against web application friction.
