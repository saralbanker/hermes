# Job Application Automation — Full Roadmap

## Verdict: Why Custom Claude Code + Playwright MCP Wins

| Approach | Speed | Accuracy | Reliability | Ban Risk | Control |
|----------|-------|----------|-------------|----------|---------|
| LazyApply / SaaS mass-apply | ⚡ Fast | ❌ 1-2% callback | ❌ CAPTCHA blocks, bans | 🔴 High | ❌ None |
| ApplyPilot (open source) | ✅ Good | ✅ Per-job tailoring | ⚠️ Early stage | 🟡 Medium | ⚠️ Limited |
| **Custom Claude Code + Playwright MCP** | ✅ Fast | ✅✅ Highest (AI reads each form) | ✅ Full stealth stack | 🟢 Low | ✅ Full |

**Winner: Custom Claude Code + Playwright MCP + Stealth Layer**

Why:
- Claude reads and understands each form intelligently — no hardcoded field maps
- Per-job resume tailoring = 40% higher ATS pass rate (2026 Jobvite data)
- GateSolve MCP solves CAPTCHAs inline, no manual intervention
- Stealth browser + human-like pacing = zero detectable automation signatures
- Self-healing: Claude adapts when form layouts change across ATS providers
- Full control: you set pace, targets, filters, and scoring threshold

---

## Goal

Build a fully automated, stealth job application pipeline that: discovers matched jobs → scores fit → tailors resume per role → writes cover letter → fills and submits applications → tracks everything — hands-free, daily.

---

## Success Criteria

- [ ] Discovers 50-100 relevant jobs/day across LinkedIn, Indeed, Glassdoor, ZipRecruiter
- [ ] Scores each job vs. your resume (skip anything under 7/10)
- [ ] Submits ≤15 LinkedIn + ≤30 other-board applications/day (safe pacing)
- [ ] Zero account bans or flags
- [ ] Each application has a tailored resume + cover letter
- [ ] All applications tracked in SQLite with status + date
- [ ] CAPTCHA handled automatically

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Orchestrator** | Claude Code CLI (Sonnet 4.6) | Reads forms, makes decisions, adapts to layout changes |
| **Browser** | Playwright MCP (official Microsoft) | Real browser = undetectable vs. API-only tools |
| **Stealth** | `playwright-extra` + `puppeteer-extra-plugin-stealth` + gaussian delays | Patches navigator.webdriver, fingerprints, timing |
| **CAPTCHA** | GateSolve MCP | Solves Cloudflare Turnstile, reCAPTCHA, hCaptcha in ~12-15s |
| **Job Discovery** | JobSpy (Python) | Scrapes LinkedIn, Indeed, Glassdoor, ZipRecruiter in one call |
| **AI Scoring/Tailoring** | Claude API (claude-sonnet-4-6) | Resume match scoring + per-job rewriting |
| **Database** | SQLite (via `better-sqlite3`) | Deduplication, tracking, job history |
| **Runtime** | Python 3.11 + Node.js 20 | Python for scraping/AI; Node for Playwright |
| **Config** | YAML + `.env` | Resume library, scoring threshold, daily limits |

---

## File Structure

```
hermes/
├── job-automation-roadmap.md       ← this file
├── .env                            ← API keys (never committed)
├── config.yaml                     ← preferences, limits, filters
├── resumes/
│   ├── resume-software-eng.pdf
│   ├── resume-devops.pdf
│   └── resume-fullstack.pdf
├── src/
│   ├── discover.py                 ← JobSpy scraper
│   ├── score.py                    ← Claude API job-fit scorer
│   ├── tailor.py                   ← Claude API resume + cover letter writer
│   ├── apply.py                    ← Claude Code + Playwright MCP submitter
│   ├── tracker.py                  ← SQLite read/write
│   └── pipeline.py                 ← Main orchestrator (runs all stages)
├── db/
│   └── applications.db             ← SQLite database
├── output/
│   └── tailored/                   ← Per-job tailored resumes + cover letters
└── .mcp.json                       ← MCP server config (Playwright + GateSolve)
```

---

## Task Breakdown

### Phase 0: Environment Setup
- [ ] **T0.1** Create `.env` with `ANTHROPIC_API_KEY`, `GATESOLVE_API_KEY`
  → Verify: `python -c "import os; print(os.getenv('ANTHROPIC_API_KEY')[:10])"`

- [ ] **T0.2** Install Python deps: `pip install jobspy anthropic python-dotenv pyyaml better-sqlite3`
  → Verify: `python -c "import jobspy, anthropic; print('ok')"`

- [ ] **T0.3** Install Node deps: `npm install @playwright/mcp playwright-extra puppeteer-extra-plugin-stealth better-sqlite3`
  → Verify: `node -e "require('@playwright/mcp'); console.log('ok')"`

- [ ] **T0.4** Install Playwright browsers: `npx playwright install chromium`
  → Verify: `npx playwright --version`

- [ ] **T0.5** Create `.mcp.json` with Playwright MCP + GateSolve MCP servers
  → Verify: `claude mcp list` shows both servers

---

### Phase 1: Job Discovery (`src/discover.py`)
- [ ] **T1.1** Write `discover.py` using JobSpy to scrape jobs with your role + location filters from `config.yaml`
  → OUTPUT: list of raw jobs written to SQLite `jobs` table
  → Verify: `python src/discover.py` returns ≥20 jobs

- [ ] **T1.2** Add deduplication: skip jobs already in DB (match on `url` column)
  → Verify: running twice produces 0 new inserts on second run

---

### Phase 2: AI Scoring (`src/score.py`)
- [ ] **T2.1** Write `score.py` — sends each job description + your master resume to Claude API, gets 1-10 fit score + reason
  → OUTPUT: `score` and `score_reason` columns updated in `jobs` table
  → Verify: 5 sample jobs get scores with explanations

- [ ] **T2.2** Add threshold filter: only pass jobs scoring ≥7 to next stage
  → Verify: `SELECT COUNT(*) FROM jobs WHERE score >= 7` returns reasonable subset

---

### Phase 3: Resume Tailoring + Cover Letter (`src/tailor.py`)
- [ ] **T3.1** Write `tailor.py` — for each qualifying job, Claude API:
  1. Picks best base resume from `resumes/` by job family
  2. Rewrites 3-5 bullet points to mirror job description keywords
  3. Writes 3-paragraph cover letter targeting company + role
  → OUTPUT: saves `output/tailored/{company}-{job-title}-resume.pdf` + `.txt` cover letter
  → Verify: inspect 2 outputs — keywords from JD appear in resume

- [ ] **T3.2** Store tailored resume path + cover letter path in `jobs` table
  → Verify: `SELECT tailored_resume, cover_letter FROM jobs LIMIT 5` all populated

---

### Phase 4: Stealth Browser Setup
- [ ] **T4.1** Create `stealth-launcher.js` — Playwright with `playwright-extra` + stealth plugin, gaussian delay helper (mean 800ms, σ 400ms), human-like mouse movement
  → Verify: run against https://bot.sannysoft.com — all checks green

- [ ] **T4.2** Wire GateSolve into `.mcp.json` — registers `solve_captcha` tool available to Claude Code
  → Verify: `claude mcp list` shows `gatesolve` with `solve_captcha` tool

- [ ] **T4.3** Add daily cap enforcer: read `applications_today` from DB, halt if LinkedIn ≥15 or total ≥40
  → Verify: mock 15 LinkedIn entries, run — pipeline stops at LinkedIn block

---

### Phase 5: Application Submission (`src/apply.py`)
- [ ] **T5.1** Write Claude Code prompt template that:
  1. Navigates to the job application URL
  2. Reads the form fields using accessibility snapshot
  3. Fills each field with data from `config.yaml` (name, contact, experience)
  4. Uploads tailored resume
  5. Pastes cover letter into text areas
  6. Handles screening questions with AI-generated answers
  7. Calls `solve_captcha` if CAPTCHA detected
  8. Submits and screenshots confirmation
  → Verify: test against a real Easy Apply job in dry-run mode (don't submit)

- [ ] **T5.2** Add per-application state machine in `tracker.py`:
  States: `discovered → scored → tailored → submitted → confirmed → error`
  → Verify: after dry-run, job shows `status=submitted` in DB

- [ ] **T5.3** Add error recovery: on Claude failure, mark `status=error`, log reason, continue to next job
  → Verify: inject a bad URL, pipeline skips it and continues

---

### Phase 6: Main Pipeline (`src/pipeline.py`)
- [ ] **T6.1** Wire all stages in sequence: `discover → score → tailor → apply`
  Add total runtime estimate + per-job timing log
  → Verify: `python src/pipeline.py --dry-run` completes all stages without submitting

- [ ] **T6.2** Add `config.yaml` controls:
  ```yaml
  daily_limit_linkedin: 15
  daily_limit_other: 30
  min_score: 7
  target_roles: ["software engineer", "backend engineer"]
  location: "Remote"
  experience_years: 3
  salary_min: 100000
  ```
  → Verify: changing `min_score: 9` drastically reduces pipeline output

- [ ] **T6.3** Add CLI: `python src/pipeline.py [--dry-run] [--discover-only] [--apply-only] [--limit N]`
  → Verify: each flag works correctly

---

### Phase 7: Tracking Dashboard
- [ ] **T7.1** Write `tracker.py` CLI: `python src/tracker.py stats` shows:
  - Total applied today / this week
  - Status breakdown (submitted, confirmed, error)
  - Top companies applied to
  - Average score of applications
  → Verify: output renders correctly after Phase 5

---

### Phase X: Verification

- [ ] Run security scan: `python .agents/skills/vulnerability-scanner/scripts/security_scan.py .`
  (Check: no API keys in source, no hardcoded credentials)
- [ ] Test stealth: launch browser against bot detection sites, all checks green
- [ ] Test CAPTCHA: trigger a reCAPTCHA in dry-run, GateSolve resolves it
- [ ] End-to-end dry-run: `python src/pipeline.py --dry-run --limit 3`
- [ ] Live test: submit 1 real application, verify confirmation screenshot saved
- [ ] Check DB: `status=confirmed` for live test job

---

## Implementation Order (Critical Path)

```
T0 (env) → T1 (discover) → T2 (score) → T3 (tailor) → T4 (stealth) → T5 (apply) → T6 (pipeline) → T7 (tracker) → Phase X
```

Phases 1-3 can be tested without browser. Phase 4-5 require browser + MCP.

---

## Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| LinkedIn ban | Cap at 15/day, gaussian delays, rotate to Greenhouse/Lever/Workday |
| CAPTCHA blocks | GateSolve MCP handles inline; fallback to manual pause |
| ATS form layout changes | Claude reads accessibility snapshot dynamically — no hardcoded selectors |
| Resume mismatch | Threshold score ≥7 filters bad fits; multiple base resumes by job family |
| Claude API rate limits | Add `time.sleep(2)` between scoring calls; batch tailor in groups of 5 |
| Duplicate applications | URL-based deduplication + DB constraint on `(url, company)` |

---

## Estimated Timeline

| Phase | Time to Build | Notes |
|-------|--------------|-------|
| Phase 0 — Setup | 1 hour | One-time |
| Phase 1 — Discovery | 2 hours | JobSpy is well-documented |
| Phase 2 — Scoring | 1 hour | Simple Claude API call |
| Phase 3 — Tailoring | 2 hours | Prompt engineering for quality |
| Phase 4 — Stealth | 2 hours | Most critical for reliability |
| Phase 5 — Apply | 3 hours | Most complex; test carefully |
| Phase 6 — Pipeline | 1 hour | Wiring + config |
| Phase 7 — Tracker | 1 hour | Simple SQLite queries |
| **Total** | **~13 hours** | Spread across 2-3 days |

---

## Daily Operating Routine (once built)

```bash
# Every morning — runs full pipeline
python src/pipeline.py --limit 40

# Check results
python src/tracker.py stats

# Review what was applied to
python src/tracker.py list --status submitted --today
```

---

## Notes

- Start `resumes/` with at least 3 variants: general software, backend-focused, fullstack/product
- Pre-write answers to the 20 most common screening questions in `config.yaml` — Claude uses them as context but rewrites per-company
- GateSolve free tier: 100 solves/month. At $0.02/solve after that, cost is negligible
- LinkedIn 50/day is the hard cap; stay at 15 to avoid behavioral flags
- Diversify: target Greenhouse/Lever/Workday direct portals for most volume — LinkedIn for visibility
