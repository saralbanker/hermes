# Agent Build Plan — Job Automation System
# Hermes Project

> This document is the single source of truth for building the job automation
> pipeline. Every agent receives this document as their brief. All shared
> contracts (schema, interfaces, paths) are defined here so agents never
> make conflicting assumptions.

---

## Project Overview

We are building a fully automated job application pipeline for **Saral Banker**
(Full Stack + AI Engineer, Ahmedabad, India). The system:

1. Discovers 100+ matched jobs/day across LinkedIn, Indeed, Glassdoor, ZipRecruiter
2. Scores each job vs. Saral's resume using local Qwen 2.5 Instruct (free, private)
3. Filters to jobs scoring ≥7.5/10 only
4. Tailors resume bullets + writes cover letter per job using Qwen
5. Uses Claude Code + Playwright MCP (stealth browser) to fill and submit each application
6. Tracks everything in SQLite with full status state machine
7. Enforces daily limits (≤15 LinkedIn, ≤40 total) to prevent account bans

**Tech stack:** Python 3.11 + Node.js 20 · SQLite · JobSpy · Qwen 2.5 local ·
Playwright MCP · playwright-extra stealth · GateSolve MCP (CAPTCHA)

---

## Execution Workflow

```
┌─────────────────────────────────────────────────────────┐
│  STEP 1 — FOUNDATION (main agent, ~20 min)              │
│  Creates shared contracts before any agent starts:      │
│  folder structure, SQLite schema, db.py, config.yaml,   │
│  .env.example, requirements.txt, package.json           │
└──────────────────────┬──────────────────────────────────┘
                       │ Foundation complete — agents start
          ┌────────────┼────────────┐
          ↓            ↓            ↓
┌─────────────┐ ┌─────────────┐ ┌──────────────────┐
│  AGENT 1    │ │  AGENT 2    │ │  AGENT 3         │
│  Data Layer │ │  Intel Layer│ │  Stealth Layer   │
│  ~35 min    │ │  ~40 min    │ │  ~30 min         │
│             │ │             │ │                  │
│ discover.py │ │ score.py    │ │ stealth-          │
│ tracker.py  │ │ tailor.py   │ │  launcher.js     │
│             │ │ keywords.py │ │ .mcp.json        │
│             │ │             │ │ cap_enforcer.py  │
└──────┬──────┘ └──────┬──────┘ └────────┬─────────┘
       └───────────────┴─────────────────┘
                       │ All 3 agents done
┌──────────────────────▼──────────────────────────────────┐
│  STEP 3 — INTEGRATION (main agent, ~30 min)             │
│  apply.py — integrates stealth + tailored files + DB    │
│  pipeline.py — wires all stages, CLI flags              │
│  Phase X — verification                                 │
└─────────────────────────────────────────────────────────┘
```

**Total estimated time: ~1.5 hours** (vs 13 hours sequential)

---

## SHARED CONTRACTS
### (All agents MUST use these exactly — do not deviate)

### A. Directory Structure

```
/mnt/data/rj/hermes/
├── src/
│   ├── db.py                ← SHARED: created in foundation, used by all
│   ├── discover.py          ← Agent 1
│   ├── tracker.py           ← Agent 1
│   ├── score.py             ← Agent 2
│   ├── tailor.py            ← Agent 2
│   ├── keywords.py          ← Agent 2
│   ├── cap_enforcer.py      ← Agent 3
│   ├── stealth-launcher.js  ← Agent 3
│   ├── apply.py             ← Integration (main agent)
│   └── pipeline.py          ← Integration (main agent)
├── db/
│   └── applications.db      ← SQLite database (auto-created)
├── resumes/
│   ├── resume-fullstack.pdf
│   ├── resume-backend.pdf
│   └── resume-ai.pdf
├── output/
│   └── tailored/            ← Per-job tailored cover letters (.txt)
├── screenshots/             ← Confirmation screenshots from apply.py
├── config.yaml              ← All settings
├── .env                     ← API keys (never committed)
├── .env.example             ← Template
├── .mcp.json                ← Agent 3 creates this
├── requirements.txt         ← Foundation creates this
└── package.json             ← Foundation creates this
```

### B. SQLite Schema (Canonical — created by foundation in `db/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    url                     TEXT UNIQUE NOT NULL,
    company                 TEXT NOT NULL,
    title                   TEXT NOT NULL,
    location                TEXT,
    job_board               TEXT,       -- 'linkedin'|'indeed'|'glassdoor'|'zip_recruiter'
    description             TEXT,
    salary_min              INTEGER,
    salary_max              INTEGER,
    date_posted             TEXT,

    -- Scoring (set by score.py)
    score                   REAL,       -- 1.0–10.0
    score_reason            TEXT,

    -- Tailoring (set by tailor.py)
    resume_variant          TEXT,       -- 'fullstack'|'backend'|'ai'
    cover_letter_path       TEXT,       -- relative: output/tailored/{slug}-cover.txt

    -- Submission (set by apply.py)
    status                  TEXT NOT NULL DEFAULT 'discovered',
    -- discovered → scored → tailored → applying → submitted → confirmed → error
    status_reason           TEXT,
    applied_at              TEXT,       -- ISO 8601 datetime
    screenshot_path         TEXT,       -- relative: screenshots/{slug}.png

    -- Meta
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_limits (
    date            TEXT PRIMARY KEY,   -- YYYY-MM-DD
    linkedin_count  INTEGER NOT NULL DEFAULT 0,
    other_count     INTEGER NOT NULL DEFAULT 0,
    total_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TRIGGER IF NOT EXISTS update_jobs_timestamp
AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = datetime('now') WHERE id = NEW.id;
END;
```

### C. `src/db.py` — Shared Database Module (created by foundation)

All agents import from this. Never use raw sqlite3 calls in other files.

```python
# src/db.py
import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "applications.db"
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()

def upsert_job(job: dict) -> int:
    """Insert or ignore a job. Returns rowid."""
    conn = get_conn()
    cur = conn.execute("""
        INSERT OR IGNORE INTO jobs (url, company, title, location, job_board,
            description, salary_min, salary_max, date_posted)
        VALUES (:url, :company, :title, :location, :job_board,
            :description, :salary_min, :salary_max, :date_posted)
    """, job)
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    return rowid

def update_job(url: str, fields: dict):
    """Update arbitrary columns on a job by URL."""
    cols = ", ".join(f"{k} = :{k}" for k in fields)
    conn = get_conn()
    conn.execute(f"UPDATE jobs SET {cols} WHERE url = :_url",
                 {**fields, "_url": url})
    conn.commit()
    conn.close()

def get_jobs_by_status(status: str) -> list[sqlite3.Row]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = ? ORDER BY score DESC", (status,)
    ).fetchall()
    conn.close()
    return rows

def get_jobs_above_score(min_score: float) -> list[sqlite3.Row]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE score >= ? AND status = 'scored' ORDER BY score DESC",
        (min_score,)
    ).fetchall()
    conn.close()
    return rows

def count_today(board: str | None = None) -> int:
    """Count applications submitted today. board='linkedin' for LinkedIn-specific."""
    from datetime import date
    today = date.today().isoformat()
    conn = get_conn()
    if board:
        row = conn.execute(
            "SELECT linkedin_count FROM daily_limits WHERE date = ?", (today,)
        ).fetchone()
        conn.close()
        return row["linkedin_count"] if row else 0
    else:
        row = conn.execute(
            "SELECT total_count FROM daily_limits WHERE date = ?", (today,)
        ).fetchone()
        conn.close()
        return row["total_count"] if row else 0

def increment_daily(board: str):
    """Increment the daily counter. board='linkedin' or 'other'."""
    from datetime import date
    today = date.today().isoformat()
    conn = get_conn()
    conn.execute("""
        INSERT INTO daily_limits (date, linkedin_count, other_count, total_count)
        VALUES (?, 0, 0, 0)
        ON CONFLICT(date) DO NOTHING
    """, (today,))
    if board == "linkedin":
        conn.execute(
            "UPDATE daily_limits SET linkedin_count = linkedin_count + 1, "
            "total_count = total_count + 1 WHERE date = ?", (today,)
        )
    else:
        conn.execute(
            "UPDATE daily_limits SET other_count = other_count + 1, "
            "total_count = total_count + 1 WHERE date = ?", (today,)
        )
    conn.commit()
    conn.close()
```

### D. `config.yaml` — Pre-filled with Saral's Profile (created by foundation)

```yaml
profile:
  name: "Saral Banker"
  email: "saralbanker1@gmail.com"
  phone: "+91 9016990136"
  location: "Ahmedabad, Gujarat, India"
  github: "github.com/saralbanker"
  portfolio: "orvion-co.vercel.app"
  years_experience: 2
  education: "Diploma in Computer Engineering, LJ Polytechnic (May 2026), CGPA 8.36/10"
  work_authorization: "India — authorized, no sponsorship needed"
  willing_to_relocate: false
  available: "Immediately"

search:
  target_roles:
    - "full stack engineer"
    - "software engineer"
    - "backend engineer"
    - "AI engineer"
    - "founding engineer"
    - "AI application developer"
    - "TypeScript engineer"
  location: "Remote"
  country_indeed: "India"
  results_wanted: 30          # per board per run
  hours_old: 72               # only jobs posted in last 72 hours
  min_score: 7.5

limits:
  linkedin_per_day: 15
  other_per_day: 30
  total_per_day: 40
  min_delay_seconds: 45       # between applications
  max_delay_seconds: 120

resumes:
  fullstack: "resumes/resume-fullstack.pdf"
  backend: "resumes/resume-backend.pdf"
  ai: "resumes/resume-ai.pdf"
  default: "resumes/resume-fullstack.pdf"

qwen:
  base_url: "http://localhost:11434"
  model: "qwen2.5:instruct"
  timeout: 60

screening_answers:
  years_experience_total: "2"
  years_experience_typescript: "2"
  years_experience_react: "2"
  years_experience_node: "2"
  years_experience_python: "2"
  degree: "Diploma in Computer Engineering"
  currently_employed: "No"
  notice_period: "Immediately available"
  salary_expectation_inr: "Open to competitive offers"
  salary_expectation_usd: "Open to competitive offers"
  work_authorization: "Yes, authorized to work in India"
  requires_visa_sponsorship: "No"
  willing_to_relocate: "Open to fully remote positions"
  why_interested_template: >
    I'm drawn to high-ownership engineering roles where I can architect and
    ship complete systems end-to-end. I independently designed and built
    Neuro-Zenith — a 70k+ LOC production AI platform spanning RAG pipelines,
    real-time collaboration, async job processing, and multi-provider LLM
    routing. I've also delivered a production financial system as a paid
    contract engagement. I thrive with autonomy and hard problems.
  biggest_achievement: >
    Independently architected and shipped Neuro-Zenith: a 70,000+ LOC
    modular AI productivity platform across 400+ source files, 44 database
    migrations, a full RAG pipeline, Socket.IO real-time collaboration,
    BullMQ async processing, multi-provider LLM routing, and a 4-pipeline
    GitHub Actions CI/CD system — from first principles, with no team.
  describe_yourself: >
    Full Stack and AI Application Engineer who ships complete production-grade
    systems independently. Strong in TypeScript/Node.js/React/PostgreSQL with
    deep AI/LLM integration experience. I prefer founding-stage environments,
    full ownership, and hard problems.
```

### E. Resume Variant Selection Logic (used by tailor.py)

```
Job title contains any of:              → Use resume variant
"AI", "LLM", "ML", "machine learning",
"RAG", "NLP", "artificial intelligence" → ai
"backend", "API", "server", "database",
"infrastructure", "platform"            → backend
everything else                         → fullstack
```

### F. Saral's Master Resume Text (for scoring prompts)

```
Saral Banker — Full Stack Engineer · AI Application Developer · Founding Engineer

SKILLS: TypeScript, JavaScript, Python, SQL | React 18, Next.js, Vite, Tailwind CSS,
shadcn/ui, Framer Motion | Node.js, Express 4, FastAPI, REST API, Socket.IO 4 |
RAG Pipelines, pgvector HNSW, BGE-base-576M embeddings, OpenRouter, Gemini API,
local Qwen 2.5 Instruct, prompt engineering, multi-provider LLM routing |
PostgreSQL (raw driver, 44 migrations), Supabase, Redis 7, MySQL, SQLite, pgvector |
Docker, Docker Compose, GitHub Actions CI/CD, GHCR, Terraform |
BullMQ, event-driven architecture, RBAC, JWT auth, rate limiting, audit logging |
Sentry, Prometheus, Pino | Kotlin (Android)

EXPERIENCE:
- Contract Full Stack Engineer (Jan 2025–Mar 2026): Built financial operations
  platform for 220-unit rental business. Automated billing, PDF invoices via
  WhatsApp Business API, late-fee logic. Saved 40+ hrs/month. Rs.60,000 contract.
  Stack: React, Next.js, TypeScript, Node.js, PostgreSQL, Supabase.

PROJECTS:
- Neuro-Zenith (2025–2026): 70k+ LOC modular AI platform. Full RAG pipeline
  (document ingestion → BGE embeddings → pgvector HNSW → semantic search).
  Socket.IO real-time collaboration. BullMQ/Redis async jobs. Multi-provider LLM
  routing (OpenRouter, Gemini, local Qwen 2.5). RBAC, JWT, 3-layer middleware.
  Prometheus + Sentry observability. 4-pipeline GitHub Actions CI/CD.
  Docker Compose. 30 backend test files (Jest + Supertest).
- Smart Parking System: Real-time occupancy, optimistic concurrency control.
- Carbon Compass: Emissions tracking, time-series dashboard.

EDUCATION: Diploma in Computer Engineering, LJ Polytechnic (May 2026), CGPA 8.36/10,
Top 10% of class.

CERTS: IBM Python for Data Science · Google Cybersecurity · Agile PM
```

---

## STEP 1 — FOUNDATION BRIEF (Main Agent)

**Objective:** Create all shared infrastructure before any agent starts.
No agent can begin until foundation is confirmed complete.

**Deliverables (in order):**

1. Create directory structure:
   ```bash
   mkdir -p /mnt/data/rj/hermes/{src,db,resumes,output/tailored,screenshots}
   ```

2. Write `db/schema.sql` — exact SQL from Section B above

3. Write `src/db.py` — exact code from Section C above

4. Write `config.yaml` — exact content from Section D above

5. Write `.env.example`:
   ```
   GATESOLVE_API_KEY=your_key_here
   # Anthropic API key only needed if you replace Qwen with Claude API
   # ANTHROPIC_API_KEY=your_key_here
   ```

6. Write `requirements.txt`:
   ```
   python-jobspy==1.1.80
   anthropic
   python-dotenv
   pyyaml
   scikit-learn
   spacy
   reportlab
   Pillow
   rich          # for tracker.py CLI output
   ```

7. Write `package.json`:
   ```json
   {
     "name": "hermes-job-automation",
     "version": "1.0.0",
     "private": true,
     "scripts": {
       "stealth-test": "node src/stealth-launcher.js --test"
     },
     "dependencies": {
       "playwright-extra": "^4.3.6",
       "puppeteer-extra-plugin-stealth": "^2.11.2",
       "@playwright/test": "^1.45.0",
       "yaml": "^2.4.5",
       "better-sqlite3": "^11.0.0"
     }
   }
   ```

8. Verify foundation:
   ```bash
   ls /mnt/data/rj/hermes/src/db.py
   ls /mnt/data/rj/hermes/db/schema.sql
   ls /mnt/data/rj/hermes/config.yaml
   python -c "import sys; sys.path.insert(0,'src'); from db import init_db; init_db(); print('DB OK')"
   ```

**EXIT GATE:** All 8 deliverables exist + DB init runs without error → agents may start.

---

## AGENT 1 BRIEF — Data Layer

**Agent name:** Data Layer Agent
**Assigned to:** `backend-specialist` agent profile
**Working directory:** `/mnt/data/rj/hermes`
**Files to create:** `src/discover.py`, `src/tracker.py`
**Must NOT touch:** `src/db.py` (read-only for this agent), `score.py`, `tailor.py`, `stealth-launcher.js`

---

### Context (read this before writing any code)

You are building two Python modules for a job application automation system
for Saral Banker (Full Stack + AI Engineer). The system discovers jobs from
multiple boards, scores them, tailors resumes, and auto-submits applications.

You own the **data layer**: scraping jobs from job boards and providing a
CLI tracking dashboard. Both modules use `src/db.py` (already written — do
not modify it). The SQLite schema is already initialised.

The shared DB module is at `src/db.py`. Import it as:
```python
import sys
sys.path.insert(0, str(Path(__file__).parent))
from db import init_db, upsert_job, update_job, get_jobs_by_status, count_today
```

---

### Task 1A: `src/discover.py`

**Purpose:** Scrape job listings from multiple boards and save to SQLite.

**Key library:** `python-jobspy` — usage:
```python
from jobspy import scrape_jobs
jobs_df = scrape_jobs(
    site_name=["linkedin", "indeed", "glassdoor", "zip_recruiter"],
    search_term="full stack engineer",
    location="Remote",
    results_wanted=30,
    hours_old=72,
    country_indeed="India",
)
```

**Full specification for `discover.py`:**

```
discover.py
├── load_config()           → reads config.yaml, returns dict
├── scrape_all_roles()      → iterates config.search.target_roles,
│                             calls JobSpy for each, returns combined DataFrame
├── deduplicate(df)         → drops rows where url already in DB
├── save_to_db(df)          → calls upsert_job() for each row
├── main()                  → orchestrates above, prints summary
└── CLI: python src/discover.py [--dry-run] [--limit N]
```

**Field mapping** from JobSpy DataFrame to `upsert_job()` dict:
```python
{
    "url":         row.job_url,
    "company":     row.company,
    "title":       row.title,
    "location":    row.location,
    "job_board":   row.site,             # 'linkedin'|'indeed'|'glassdoor'|'zip_recruiter'
    "description": row.description,
    "salary_min":  row.min_amount,
    "salary_max":  row.max_amount,
    "date_posted": str(row.date_posted) if row.date_posted else None,
}
```

**Deduplication logic:**
```python
# Query existing URLs from DB before inserting
conn = get_conn()
existing = {r["url"] for r in conn.execute("SELECT url FROM jobs").fetchall()}
conn.close()
new_jobs = df[~df["job_url"].isin(existing)]
```

**Output on run:**
```
[discover] Scraping 6 roles across 4 boards...
[discover] Found 187 raw jobs
[discover] 23 already in DB, skipping
[discover] Saved 164 new jobs
[discover] Done in 28.3s
```

**CLI flags:**
- `--dry-run`: scrape + deduplicate but don't write to DB, just print count
- `--limit N`: only scrape N results per role (for testing)

**Verification:**
```bash
python src/discover.py --limit 5
# Should print: Saved N new jobs (N > 0)
python src/discover.py --limit 5
# Should print: 0 already in DB... Saved 0 new jobs (dedup works)
```

---

### Task 1B: `src/tracker.py`

**Purpose:** CLI dashboard for tracking application pipeline stats.

**Full specification:**

```
tracker.py
├── cmd_stats()     → summary table: totals by status, today's count, weekly count
├── cmd_list()      → paginated list of jobs filtered by status/date
├── cmd_export()    → export jobs to CSV
└── CLI entry point with subcommands
```

**CLI interface:**
```bash
python src/tracker.py stats
python src/tracker.py list [--status STATUS] [--today] [--limit N]
python src/tracker.py export [--output FILE]
```

**`stats` output (use `rich` library for tables):**
```
┌─────────────────────────────────────┐
│       Hermes — Application Stats    │
├───────────────┬──────────┬──────────┤
│ Status        │  Total   │  Today   │
├───────────────┼──────────┼──────────┤
│ discovered    │   164    │    164   │
│ scored        │    58    │     58   │
│ tailored      │    42    │     42   │
│ submitted     │    38    │     38   │
│ confirmed     │    31    │     31   │
│ error         │     7    │      7   │
├───────────────┼──────────┼──────────┤
│ TOTAL applied │    31    │     31   │
│ LinkedIn used │    12/15 │          │
│ Other used    │    19/30 │          │
│ Avg score     │    8.2   │          │
└───────────────┴──────────┴──────────┘
```

**`list` output:**
```
 # │ Company          │ Title                    │ Score │ Status    │ Applied
───┼──────────────────┼──────────────────────────┼───────┼───────────┼─────────
 1 │ Stripe           │ Full Stack Engineer       │  9.1  │ confirmed │ 2h ago
 2 │ Linear           │ Software Engineer         │  8.8  │ submitted │ 3h ago
 3 │ Vercel           │ Founding Engineer         │  8.5  │ tailored  │ —
```

**Verification:**
```bash
python src/tracker.py stats   # shows table without error
python src/tracker.py list --today --limit 5   # shows today's jobs
python src/tracker.py export --output /tmp/test.csv && head /tmp/test.csv
```

---

## AGENT 2 BRIEF — Intelligence Layer

**Agent name:** Intelligence Layer Agent
**Assigned to:** `backend-specialist` agent profile
**Working directory:** `/mnt/data/rj/hermes`
**Files to create:** `src/keywords.py`, `src/score.py`, `src/tailor.py`
**Must NOT touch:** `src/db.py`, `src/discover.py`, `src/tracker.py`, `src/stealth-launcher.js`

---

### Context

You are building the AI intelligence layer for a job automation system for
Saral Banker. Your modules score jobs against Saral's resume using local
Qwen 2.5 Instruct (running at `http://localhost:11434`) and tailor the
resume + write a cover letter per job.

**Key context about Saral:**
- Full Stack + AI Engineer, 2 years experience
- Flagship project: Neuro-Zenith (70k+ LOC AI platform)
- Skills: TypeScript, React 18, Next.js, Node.js, FastAPI, PostgreSQL,
  pgvector, RAG pipelines, Redis, BullMQ, Docker, GitHub Actions
- Target roles: Full Stack Engineer, Backend Engineer, AI Engineer,
  Founding Engineer

**Qwen 2.5 Instruct is already running locally via Ollama.** Call it via:
```python
import requests

def call_qwen(prompt: str, system: str = "") -> str:
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "qwen2.5:instruct",
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 800}
        },
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()
```

The shared DB module is at `src/db.py`. Import it as shown in Agent 1 brief.

---

### Task 2A: `src/keywords.py`

**Purpose:** Fast, free keyword extraction from job descriptions using
TF-IDF + spaCy. Used by score.py (pre-filter) and tailor.py (targeted rewrite).

**Specification:**
```python
# src/keywords.py

def extract_keywords(text: str, top_n: int = 20) -> list[str]:
    """
    Extract top N keywords from a job description.
    Uses spaCy for noun phrases + sklearn TF-IDF for ranking.
    Returns list of keyword strings, highest relevance first.
    """

def keyword_overlap_score(resume_text: str, jd_text: str) -> float:
    """
    Fast cosine similarity between resume and JD using TF-IDF.
    Returns 0.0–1.0. Used to pre-filter before calling Qwen.
    Threshold: < 0.25 → skip (obvious mismatch), don't burn Qwen tokens.
    """

def missing_keywords(resume_text: str, jd_keywords: list[str]) -> list[str]:
    """
    Returns keywords from jd_keywords not present in resume_text.
    Used by tailor.py to know what to inject.
    """
```

**Implementation notes:**
- Use `sklearn.feature_extraction.text.TfidfVectorizer` for vectorisation
- Use `sklearn.metrics.pairwise.cosine_similarity` for overlap score
- Pre-filter with `keyword_overlap_score < 0.25` before Qwen scoring
- No external API calls in this module — must be fully local/free

---

### Task 2B: `src/score.py`

**Purpose:** Score each `status='discovered'` job against Saral's resume
using TF-IDF pre-filter + Qwen 2.5 for final scoring.

**Full specification:**

```
score.py
├── load_resume_text()    → returns the master resume text (Section F of this doc)
├── prefilter(jobs)       → runs keyword_overlap_score, drops < 0.25
├── score_job(job, resume_text)  → calls Qwen, returns (score: float, reason: str)
├── score_batch(jobs)     → scores all jobs, updates DB, prints progress
└── CLI: python src/score.py [--limit N] [--min-overlap 0.25]
```

**Qwen scoring prompt template:**
```
SYSTEM: You are a technical recruiter evaluating candidate-job fit.
Score strictly on technical skill match and seniority alignment.
Respond ONLY with JSON: {"score": 8.5, "reason": "one sentence"}

PROMPT:
CANDIDATE RESUME:
{resume_text}

JOB DESCRIPTION:
Company: {company}
Title: {title}
Description: {description}

Rate fit 1.0–10.0. Consider:
- Technical stack overlap (TypeScript/Node/React/PostgreSQL/Python/AI weighted highest)
- Seniority match (Saral has 2 years, Diploma education — penalise if 5+ YOE required)
- Remote-friendliness
- Founding/small-team fit given Neuro-Zenith solo ownership

JSON only, no other text.
```

**Score parsing:**
```python
import json, re

def parse_score_response(resp: str) -> tuple[float, str]:
    # Strip markdown code fences if present
    cleaned = re.sub(r"```json|```", "", resp).strip()
    data = json.loads(cleaned)
    return float(data["score"]), str(data["reason"])
```

**DB update after scoring:**
```python
update_job(job["url"], {
    "score": score,
    "score_reason": reason,
    "status": "scored"
})
```

**Output:**
```
[score] 164 jobs to score (after pre-filter: 89 remain)
[score] ████████████████████ 89/89  avg score: 7.8
[score] Above threshold (≥7.5): 34 jobs → ready for tailoring
```

**Verification:**
```bash
python src/score.py --limit 5
# Should update 5 jobs with score + score_reason in DB
sqlite3 db/applications.db "SELECT title, score, score_reason FROM jobs WHERE score IS NOT NULL LIMIT 5"
```

---

### Task 2C: `src/tailor.py`

**Purpose:** For each `status='scored'` job above threshold, pick the best
resume variant, extract missing keywords, generate a targeted cover letter,
save outputs, update DB.

**Resume variant selection (use exactly this logic):**
```python
def select_resume_variant(title: str, description: str) -> str:
    text = (title + " " + description).lower()
    ai_kws = ["ai", "llm", "ml", "machine learning", "rag", "nlp",
               "artificial intelligence", "embedding", "vector"]
    backend_kws = ["backend", "api", "server", "database", "infrastructure",
                   "platform", "devops", "cloud"]
    if any(kw in text for kw in ai_kws):
        return "ai"
    if any(kw in text for kw in backend_kws):
        return "backend"
    return "fullstack"
```

**Cover letter Qwen prompt template:**
```
SYSTEM: You are writing a cover letter for Saral Banker, a Full Stack and AI
Engineer. Write in first person, professional but direct tone. No fluff.
Three short paragraphs max. Do NOT address with "Dear Hiring Manager" — start
directly with the hook sentence.

PROMPT:
Write a cover letter for this role:

Company: {company}
Title: {title}
Key missing keywords to naturally include: {missing_kws}

Job Description (excerpt):
{description[:1500]}

Candidate background:
- 70k+ LOC AI platform (Neuro-Zenith): RAG, Socket.IO, BullMQ, multi-provider LLM, CI/CD
- Paid contract: financial ops platform for 220-unit rental business (Rs.60k)
- Stack: TypeScript, React 18, Next.js, Node.js, FastAPI, PostgreSQL, pgvector, Docker
- Available immediately, open to remote, India

Rules:
- Paragraph 1: Hook — why THIS company/role specifically (reference something real about them)
- Paragraph 2: Strongest proof point from Neuro-Zenith or Shade Ledger relevant to this role
- Paragraph 3: One sentence on availability + invite to talk
- Max 200 words total
- No lists, no headers
```

**Output paths:**
```python
def make_slug(company: str, title: str) -> str:
    import re
    raw = f"{company}-{title}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw)[:60].strip("-")

cover_letter_path = f"output/tailored/{slug}-cover.txt"
```

**DB update after tailoring:**
```python
update_job(job["url"], {
    "resume_variant": variant,      # 'fullstack'|'backend'|'ai'
    "cover_letter_path": cover_letter_path,
    "status": "tailored"
})
```

**Full pipeline in tailor.py:**
```
tailor.py
├── get_qualifying_jobs()    → gets status='scored', score >= min_score from config
├── select_resume_variant()  → as above
├── generate_cover_letter()  → calls Qwen with template above
├── save_cover_letter()      → writes to output/tailored/{slug}-cover.txt
├── process_job()            → orchestrates above for one job
├── main()                   → asyncio.gather() over all qualifying jobs (10 concurrent)
└── CLI: python src/tailor.py [--limit N] [--dry-run]
```

**Concurrency:** Use `asyncio` with a semaphore of 5 to process 5 jobs concurrently:
```python
import asyncio
sem = asyncio.Semaphore(5)

async def process_job_async(job):
    async with sem:
        # call_qwen is synchronous — wrap with asyncio.to_thread()
        cover = await asyncio.to_thread(generate_cover_letter, job)
        ...
```

**Verification:**
```bash
python src/tailor.py --limit 3 --dry-run
# prints: Would tailor 3 jobs — cover letter previews shown
python src/tailor.py --limit 3
ls output/tailored/   # should show 3 .txt files
sqlite3 db/applications.db "SELECT title, resume_variant, cover_letter_path, status FROM jobs WHERE status='tailored' LIMIT 3"
```

---

## AGENT 3 BRIEF — Stealth Layer

**Agent name:** Stealth Layer Agent
**Assigned to:** `devops-engineer` agent profile
**Working directory:** `/mnt/data/rj/hermes`
**Files to create:** `src/stealth-launcher.js`, `.mcp.json`, `src/cap_enforcer.py`
**Must NOT touch:** `src/db.py`, any Python src files from Agents 1/2

---

### Context

You are building the browser stealth layer for a job automation system.
Claude Code uses Playwright MCP to control a real browser for submitting
job applications. Your job is to:

1. Create a stealth-patched browser launcher that makes automation
   undetectable to LinkedIn and ATS job boards
2. Configure `.mcp.json` so Claude Code can use Playwright MCP + GateSolve
3. Create a Python daily-limit enforcer that blocks the pipeline if daily
   application caps are reached

The main constraint: **LinkedIn bans accounts** that show automation
signatures or apply too fast. Your stealth setup must pass bot detection
tests. Human-like timing is as important as technical patches.

---

### Task 3A: `src/stealth-launcher.js`

**Purpose:** Playwright browser launcher with stealth patches + human-like
timing. Used by `apply.py` (integration phase) to launch the browser.

**Full specification:**

```javascript
// src/stealth-launcher.js
// Launch a stealth-patched Chromium browser for job applications

const { chromium } = require("playwright-extra");
const StealthPlugin = require("puppeteer-extra-plugin-stealth");
chromium.use(StealthPlugin());

// Gaussian random delay (human-like timing)
// mean=800ms, sigma=400ms, clamped to [200ms, 3000ms]
function gaussianDelay(mean = 800, sigma = 400) {
    // Box-Muller transform
    const u1 = Math.random(), u2 = Math.random();
    const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    return Math.max(200, Math.min(3000, Math.round(mean + sigma * z)));
}

async function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

// Human-like typing: types one character at a time with variable delay
async function humanType(page, selector, text) {
    await page.click(selector);
    for (const char of text) {
        await page.type(selector, char, { delay: gaussianDelay(80, 30) });
    }
}

// Human-like scroll: random scroll distance, smooth
async function humanScroll(page, distance = null) {
    const d = distance ?? gaussianDelay(400, 200);
    await page.evaluate((d) => window.scrollBy({ top: d, behavior: "smooth" }), d);
    await sleep(gaussianDelay(500, 200));
}

async function launchStealthBrowser(headless = false) {
    const browser = await chromium.launch({
        headless: headless,
        args: [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1366,768",
            "--start-maximized",
        ],
    });

    const context = await browser.newContext({
        viewport: { width: 1366, height: 768 },
        userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
                   "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        locale: "en-IN",
        timezoneId: "Asia/Kolkata",
        geolocation: { latitude: 23.0225, longitude: 72.5714 }, // Ahmedabad
        permissions: ["geolocation"],
    });

    // Extra stealth: remove automation fingerprints
    await context.addInitScript(() => {
        Object.defineProperty(navigator, "webdriver", { get: () => undefined });
        Object.defineProperty(navigator, "plugins", {
            get: () => [1, 2, 3, 4, 5],
        });
        window.chrome = { runtime: {} };
    });

    return { browser, context, gaussianDelay, sleep, humanType, humanScroll };
}

// Test mode: verify stealth against bot detection
async function testStealth() {
    const { browser, context, sleep } = await launchStealthBrowser(false);
    const page = await context.newPage();
    console.log("[stealth] Navigating to bot detection test...");
    await page.goto("https://bot.sannysoft.com");
    await sleep(3000);
    await page.screenshot({ path: "screenshots/stealth-test.png" });
    console.log("[stealth] Screenshot saved to screenshots/stealth-test.png");
    await browser.close();
}

// CLI: node src/stealth-launcher.js --test
if (process.argv.includes("--test")) {
    testStealth().catch(console.error);
}

module.exports = { launchStealthBrowser, gaussianDelay, sleep, humanType, humanScroll };
```

**Verification:**
```bash
node src/stealth-launcher.js --test
# Opens browser, navigates to bot.sannysoft.com
# Saves screenshot to screenshots/stealth-test.png
# All tests should show green (not red)
```

---

### Task 3B: `.mcp.json`

**Purpose:** Configure Playwright MCP and GateSolve MCP so Claude Code
can use `browser_*` tools and `solve_captcha` tool during apply.py.

**Create `.mcp.json` at project root:**

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--headless"],
      "env": {}
    },
    "gatesolve": {
      "command": "npx",
      "args": ["-y", "@gatesolve/mcp@latest"],
      "env": {
        "GATESOLVE_API_KEY": "${GATESOLVE_API_KEY}"
      }
    }
  }
}
```

**Note on GateSolve:** The GATESOLVE_API_KEY is read from `.env` at runtime.
The `${GATESOLVE_API_KEY}` syntax is resolved by Claude Code's MCP runner.

**Verification:**
```bash
# Add .mcp.json to project root, then:
cat .mcp.json   # confirm JSON is valid
node -e "require('fs').readFileSync('.mcp.json'); console.log('valid JSON')"
# Note: 'claude mcp list' verification happens during integration phase
```

---

### Task 3C: `src/cap_enforcer.py`

**Purpose:** Check daily application limits before apply.py proceeds.
Raises an exception if LinkedIn cap (15) or total cap (40) is hit.
Called at the start of every application attempt.

**Full specification:**

```python
# src/cap_enforcer.py
"""
Daily application cap enforcer.
Reads limits from config.yaml and current counts from daily_limits table.
Raises CapExceeded if any limit is hit.
"""
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from db import count_today

class CapExceeded(Exception):
    """Raised when a daily application limit is reached."""
    pass

def load_limits() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg["limits"]

def check_can_apply(job_board: str):
    """
    Call this before every application attempt.
    job_board: 'linkedin' or 'other'

    Raises CapExceeded with a message if any limit is hit.
    Does nothing (returns None) if application is allowed.
    """
    limits = load_limits()

    total_today = count_today()
    if total_today >= limits["total_per_day"]:
        raise CapExceeded(
            f"Daily total cap reached: {total_today}/{limits['total_per_day']}. "
            f"Pipeline stopping for today."
        )

    if job_board == "linkedin":
        linkedin_today = count_today(board="linkedin")
        if linkedin_today >= limits["linkedin_per_day"]:
            raise CapExceeded(
                f"LinkedIn daily cap reached: {linkedin_today}/{limits['linkedin_per_day']}. "
                f"Skipping LinkedIn jobs for today."
            )

def remaining_today() -> dict:
    """Returns dict of remaining application slots for reporting."""
    limits = load_limits()
    linkedin_used = count_today(board="linkedin")
    total_used = count_today()
    return {
        "linkedin_remaining": max(0, limits["linkedin_per_day"] - linkedin_used),
        "other_remaining": max(0, limits["other_per_day"] - (total_used - linkedin_used)),
        "total_remaining": max(0, limits["total_per_day"] - total_used),
    }

if __name__ == "__main__":
    # Quick status check
    r = remaining_today()
    print(f"LinkedIn remaining: {r['linkedin_remaining']}")
    print(f"Other remaining:    {r['other_remaining']}")
    print(f"Total remaining:    {r['total_remaining']}")
```

**Verification:**
```bash
python src/cap_enforcer.py
# Shows: LinkedIn remaining: 15 / Other remaining: 30 / Total remaining: 40
# (since no applications submitted yet)

# Test limit enforcement:
python -c "
import sys; sys.path.insert(0,'src')
from db import init_db, increment_daily
from cap_enforcer import check_can_apply, CapExceeded
init_db()
# Simulate 15 LinkedIn apps
for _ in range(15): increment_daily('linkedin')
try:
    check_can_apply('linkedin')
    print('FAIL: Should have raised CapExceeded')
except CapExceeded as e:
    print(f'PASS: {e}')
"
```

---

## STEP 3 — INTEGRATION BRIEF (Main Agent)

**Prerequisite:** All 3 agents have completed and verified their deliverables.

**Files to create:** `src/apply.py`, `src/pipeline.py`

---

### Integration A: `src/apply.py`

**Purpose:** For each `status='tailored'` job, invoke Claude Code headlessly
with a Playwright MCP session to fill and submit the application.

This is the most complex module. Key design:
- Reads tailored cover letter from `cover_letter_path` in DB
- Reads config.yaml for all personal info + screening answers
- Constructs a detailed prompt for Claude Code to navigate + fill the form
- Runs Claude Code as a subprocess with `--mcp-config .mcp.json`
- Parses Claude's output to determine success/failure
- Updates DB status + increments daily counter
- Takes confirmation screenshot

**Claude Code invocation pattern:**
```python
import subprocess, json

def invoke_claude_apply(job: dict, cover_letter: str, config: dict) -> dict:
    """
    Spawns Claude Code with the apply prompt.
    Returns {"success": bool, "screenshot": path|None, "error": str|None}
    """
    prompt = build_apply_prompt(job, cover_letter, config)

    result = subprocess.run(
        ["claude", "--mcp-config", ".mcp.json", "-p", prompt,
         "--output-format", "json", "--max-turns", "30"],
        capture_output=True, text=True, timeout=300,
        cwd="/mnt/data/rj/hermes"
    )

    # Parse Claude's JSON output to determine success
    ...
```

**Apply prompt template:**
```
You are applying for a job on behalf of Saral Banker using the browser tools.

JOB:
Company: {company}
Title: {title}
Application URL: {url}
Job Board: {job_board}

PERSONAL INFO (use exactly as given):
Name: Saral Banker
Email: saralbanker1@gmail.com
Phone: +91 9016990136
Location: Ahmedabad, Gujarat, India
LinkedIn: (search for saralbanker if asked)
GitHub: github.com/saralbanker
Portfolio: orvion-co.vercel.app
Years Experience: 2
Education: Diploma in Computer Engineering, LJ Polytechnic (May 2026), CGPA 8.36/10

COVER LETTER (paste this exactly into any cover letter / message / "why us" field):
{cover_letter}

RESUME TO UPLOAD: {resume_path}

SCREENING ANSWERS (use these as base, adapt naturally to match the question):
{screening_answers_yaml}

INSTRUCTIONS:
1. Navigate to the application URL
2. Check if already on the form or need to click "Apply" / "Easy Apply"
3. Fill EVERY field — use the personal info above
4. If asked for resume/CV: upload {resume_path}
5. If a text box asks "why are you interested" or similar: paste the cover letter
6. For salary: say "Open to competitive offers" or a range if required
7. For experience years: answer accurately from personal info
8. If you see a CAPTCHA: call the solve_captcha tool with the page URL
9. After submission: take a screenshot and save to screenshots/{slug}.png
10. Return ONLY: {{"success": true, "screenshot": "screenshots/{slug}.png"}}
    or {{"success": false, "error": "reason"}}

IMPORTANT:
- If the job board is 'linkedin', stay within LinkedIn Easy Apply — do not navigate away
- Do not make up information not provided above
- If a required field is unknown, leave blank and note it
- If the form fails or errors, return success: false with the error message
```

**State machine transitions:**
```python
# Before apply:
update_job(url, {"status": "applying"})

# On success:
update_job(url, {
    "status": "submitted",
    "applied_at": datetime.utcnow().isoformat(),
    "screenshot_path": screenshot_path
})
increment_daily("linkedin" if job_board == "linkedin" else "other")

# On failure:
update_job(url, {"status": "error", "status_reason": error_msg})
```

---

### Integration B: `src/pipeline.py`

**Purpose:** Master orchestrator. Runs all stages in sequence with CLI flags.

```python
# pipeline.py

def run_discover(args): ...    # calls discover.main()
def run_score(args): ...       # calls score.main()
def run_tailor(args): ...      # calls tailor.main()
def run_apply(args): ...       # calls apply.main()

def main():
    parser = argparse.ArgumentParser(description="Hermes Job Pipeline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    parser.add_argument("--tailor-only", action="store_true")
    parser.add_argument("--apply-only", action="store_true")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    # Full pipeline (default)
    if not any([args.discover_only, args.score_only,
                args.tailor_only, args.apply_only]):
        run_discover(args)
        run_score(args)
        run_tailor(args)
        if not args.dry_run:
            run_apply(args)
```

**Verification (Phase X):**
```bash
# 1. Security check
python .agents/skills/vulnerability-scanner/scripts/security_scan.py .

# 2. Dry run end-to-end
python src/pipeline.py --dry-run --limit 3

# 3. Individual stage tests
python src/discover.py --limit 5
python src/score.py --limit 3
python src/tailor.py --limit 2
python src/cap_enforcer.py

# 4. Stats check
python src/tracker.py stats

# 5. Live apply test (single job, real submission)
python src/apply.py --limit 1
```

---

## Agent Handoff Protocol

When each agent completes, they must output:

```markdown
## Agent [N] — [Name] Complete

Files created:
- [x] src/file1.py — verified with: [command used]
- [x] src/file2.py — verified with: [command used]

Test results:
[paste actual terminal output from verification commands]

Notes for integration agent:
[anything the integration agent needs to know — edge cases, assumptions, etc.]
```

Main agent waits for all 3 completion reports before starting integration.

---

## Risk Register

| Risk | Owner | Mitigation |
|------|-------|-----------|
| Qwen not running | Agent 2 | Add startup check in score.py; clear error if `localhost:11434` unreachable |
| JobSpy rate-limited | Agent 1 | Add 2s delay between board scrapes; --limit flag for testing |
| Schema mismatch | All | Use only `src/db.py` functions — never raw SQL in feature files |
| stealth test fails | Agent 3 | Screenshot saved at screenshots/stealth-test.png for inspection |
| Cover letter too long | Agent 2 | Add word count check; truncate at 250 words before saving |
| GateSolve key missing | Agent 3 | .mcp.json uses env var; `python -c "import os; print(os.getenv('GATESOLVE_API_KEY'))"` to verify |

---

## Definition of Done

- [ ] `python src/discover.py --limit 5` saves ≥5 jobs, dedup works
- [ ] `python src/score.py --limit 5` scores jobs, updates DB
- [ ] `python src/tailor.py --limit 3` writes 3 cover letter .txt files
- [ ] `node src/stealth-launcher.js --test` screenshot shows green bot tests
- [ ] `python src/cap_enforcer.py` shows correct remaining counts
- [ ] `python src/tracker.py stats` shows full table without error
- [ ] `python src/pipeline.py --dry-run --limit 3` runs all stages, no crash
- [ ] Security scan: no API keys in source, no hardcoded credentials
- [ ] `python src/apply.py --limit 1` submits 1 real application with screenshot
