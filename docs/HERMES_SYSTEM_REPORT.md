# Hermes: System Report

*Written 2026-09-23. Covers what exists today, what was changed today, what is unfinished, and what the system should become.*

---

## 1. What Hermes should be

An automated job-application system that runs on your laptop with no input from you.

| Requirement | Detail |
|---|---|
| Volume | **100 applications per day** |
| Job type | High-paying software, full-stack, backend and AI roles |
| Location | **Remote** (open to candidates in India), **or** on-site/hybrid **within 20 km of Shahibaug, Ahmedabad** |
| Honesty | **No lies** on the resume, cover letters or form answers. Say, professionally, that you build software with AI tools. |
| Resume | May be rebuilt if it has faults |
| Autonomy | Runs by itself. If something needs you, that one task should be all you do. |
| Notification | **A laptop notification when an employer responds positively** (interview, shortlist, assessment) |
| Budget | Up to 5 GB of downloads (models or tools). Zero API cost: runs on local AI. |
| New project | **AWIS** should be shown on the resume |

---

## 2. Who the candidate is (verified facts)

The source of truth is `profile/facts.md`. Every AI prompt may use only these facts.

- **Saral Banker**, Shahibaug, Ahmedabad · +91 9016990136 · saralbanker1@gmail.com
- **Education:** Diploma in Computer Engineering, LJ Polytechnic, May 2026, CGPA 8.36/10, top 10%. No bachelor's degree.
- **Experience:** Freelance Full-Stack & AI Developer, Jan 2025 to present, part-time while studying until May 2026.
  - **Shade Ledger** (paid contract, Rs. 60,000): billing system for an industrial estate of 220+ units. Saves 40+ hours a month.
  - **HeatMax**: product catalog site for a boiler manufacturer.
- **Projects:**
  - **AWIS** (Jul 2026 to now): event-sourced workflow engine in Go. About 25k lines of Go, 773 test functions, 168 commits. The repo is private.
  - **Neuro-Zenith**: AI productivity platform with RAG, pgvector, BullMQ and multi-LLM routing. About 70k lines, 44 migrations.
  - **Hermes**: this system.
- **Does not have:** AWS/GCP/Azure/Kubernetes production experience, Java/Spring/.NET/PHP, healthcare or fintech domain experience, team-lead experience, or any full-time job history.

---

## 3. The laptop it runs on

| Item | Value |
|---|---|
| CPU | AMD Ryzen 7 7730U, 16 threads, no GPU |
| RAM | 15 GB (about 6.5 GB free) |
| Disk | `/mnt/data`: 67 GB free · `/`: 5.8 GB free |
| OS | Arch Linux, KDE on **Wayland** |
| Browsers | google-chrome-stable, brave |
| AI runtime | Ollama 0.33.3. Models are stored in `/mnt/data/ollama`. |

**Installed AI models**

| Model | Size | Use |
|---|---|---|
| `qwen3:4b-instruct-2507-q4_K_M` | 2.5 GB | Scoring, cover letters, form answers. **Downloaded today.** |
| `nomic-embed-text` | ~0.3 GB | Fast pre-ranking of jobs. **Downloaded today.** |
| `qwen2.5:3b` | 1.9 GB | Old. No longer used. |

Measured speed: about 10 s to score one job, and about 25–45 s per cover letter.

---

## 4. How it works (pipeline)

```
DISCOVER  →  FILTER  →  SCORE  →  TAILOR  →  APPLY  →  WATCH REPLIES
 job boards   location    local AI   cover      browser    Gmail →
 + APIs       seniority   1–10       letter     fills      laptop
              salary                 (checked)  forms      notification
              age
```

1. **Discover**
   - **Sources:**
     - Indeed, with a remote search plus an Ahmedabad on-site search
     - **Himalayas** (jobs open to India, newest first)
     - Remotive and RemoteOK
     - **company career pages** on Greenhouse, Lever and Ashby
   - LinkedIn is **off**, because automating it risks a permanent account ban.
2. **Filter** (no AI, instant). A job is kept only if it passes all of these:
   - **Location:** remote and open to India, or ≤20 km from Shahibaug. Gandhinagar and GIFT City pass; Sanand, Vadodara and Bengaluru on-site do not.
   - **Seniority:** skip Senior/Lead/Staff/Manager titles and postings that ask for more than 3 years.
   - **Age:** skip postings older than 21 days.
   - **Salary:** skip jobs that publish a salary below the floor. The floor is not set yet.
3. **Score**: the embedding model pre-ranks jobs, then the AI scores fit from 1 to 10 against the facts. Jobs scoring 6.5 or more move on.
4. **Tailor**: the AI writes 2 short paragraphs from the facts only. A **fact-checker rejects** any made-up number, any percentage, or any claimed skill or domain you don't have. After 2 rejections, a letter built only from facts is used instead. Every letter ends with a fixed, honest paragraph about building with AI coding agents.
5. **Apply**: each job goes to the right applier: Indeed, Greenhouse, Lever, Ashby, or an "apply redirect" that follows a listing to the employer's form. The cap is 100 per day, with a 20–45 s gap between applications.
6. **Watch replies**: poll Gmail, classify each employer reply, and send a laptop notification with a sound for positive ones. A 21:00 daily summary is also planned. **This step is not built yet.**

**Schedule:** runs are planned at 08:00, 13:00 and 19:00 through a systemd user timer. Only 08:00 is live today, still using the old script.

---

## 5. Why it was not working (root causes found today)

Only **26 applications were ever recorded as submitted**, all on June 24. Indeed's own "Applied" page shows 54, some of them made outside Hermes.

| # | Problem | Real cause |
|---|---|---|
| 1 | The daily run crashed every morning, Sep 14–23 | The config asked for `qwen3:4b`, which wasn't installed. The resulting error type wasn't handled, so the keyword fallback never ran. |
| 2 | 853 jobs failed with "login wall" | **Cloudflare blocked the invisible (headless) Chrome.** The block page contains "Sign in", which the code mistook for a login wall. The Indeed login was valid the whole time. |
| 3 | Cover letters lied | The small AI invented claims: "healthcare experience matches precisely", GCP, "reduced overhead by 30%". |
| 4 | Recruiters couldn't call you | The uploaded resume had the **wrong phone number**: 9**106**990136. |
| 5 | Resume "variants" did nothing | The full-stack, backend and AI PDFs were **the same file**. |
| 6 | Wrong experience claim | Forms answered "2 years". The honest figure is closer to 1 year, part-time. |
| 7 | Ollama system service down since Sep 11 | A user-started `ollama serve` already holds the port. Harmless: that copy is the one serving requests. |

**Database before today:** 2,211 jobs in total.
- Discovered 416, scored 140, tailored 584, submitted 26, errors 1,045 (853 false "login wall", 187 low overlap).
- By board: Indeed 1,536, LinkedIn 622, Remotive 53.

---

## 6. What was done today

### Finished and tested (by me)
| File | What it does |
|---|---|
| `profile/facts.md` | Verified fact sheet. The only facts the AI may use. |
| `profile/resume.yaml` + `scripts/build_resumes.py` | **New resume**: 3 genuinely different **one-page** PDFs (full-stack, backend, AI), with the correct phone, LinkedIn and AWIS. ATS-safe. Old PDFs are in `resumes/old/`. |
| `src/llm.py` | One shared AI client. A missing model no longer crashes the run. |
| `src/geo.py` | Location filter: remote-from-India, or ≤20 km. 15/15 test cases correct. |
| `src/filters.py` | Seniority, salary and staleness filters |
| `src/answers.py` | Truthful answers to form questions. Returns "no answer" rather than guessing. |
| `src/score.py` | Rewritten around facts + embeddings + fast AI scoring |
| `src/tailor.py` | Rewritten with the cover-letter fact-checker. The old lying letter is correctly rejected. |
| `src/discover.py` | Added Himalayas, the Ahmedabad on-site search and the filters |
| `src/db.py` | New columns: apply channel, ATS info, location reason, employer response |
| `config.yaml` | Honest answers, 100/day, geography, salary block, scoring settings |

The database was backed up to `output/applications.backup-2026-09-23.db` before any schema change.

### Started by subagents, **unfinished** (all stopped on request)
| Agent | Task | State when stopped |
|---|---|---|
| Career-page agent | Greenhouse/Lever/Ashby discovery + form filler | Files written: `src/sources_ats.py`, `src/ats_apply.py`, `src/ats_extract.js`, `data/ats_companies.yaml`, `scripts/validate_ats_companies.py`. Lever test fill correct; Ashby just started; no Greenhouse result reported. |
| Indeed agent | Rewrite `src/indeed_apply.py` to get past Cloudflare | Testing only. **No file changed.** |
| Operations agent | Job routing, backlog cleanup, Gmail reply notifications, 3 runs/day, failure alerts | Only `src/redirect_resolver.py` written |

All 3 agents ran Claude Opus 5.5 at medium effort. **No application was submitted and nothing was committed to git.**

### The browser-window problem
Indeed blocks invisible Chrome, so the plan was a visible Chrome placed off-screen. **Wayland ignores off-screen positions**, so test windows appeared on your screen. The fix is to run Chrome inside a hidden virtual display (Xvfb), which needs one install (see section 8).

---

## 7. What is still missing

1. **Indeed applier** that passes Cloudflare without showing windows. Needs Xvfb.
2. **Finish the career-page applier**: Ashby test and result, Greenhouse result.
3. **`apply.py` routing** of each job to the right applier.
4. **Backlog cleanup**:
   - expire old jobs
   - re-filter the 853 false "login wall" jobs
   - regenerate all 584 old (untrustworthy) cover letters
5. **Reply watcher + laptop notification** for positive employer replies, plus the 21:00 daily summary.
6. **Scheduler**: 3 runs/day, a lock so runs never overlap, auto-start of Ollama, failure notifications.
7. **Cleanup**:
   - status script
   - remove dead code (`local_apply.py`, `switch_mode.py`, possibly `usage_guard.py` and `stealth-launcher.js`)
   - update `preflight.py`
8. **End-to-end dry run**, then commit.

**Heads-up:** tomorrow's 08:00 run still uses the old scheduler script. Its discover, score and cover-letter steps use the new code, but the old Indeed applier is still blocked by Cloudflare, so applications fail harmlessly. To pause it: `systemctl --user stop hermes.timer`.

---

## 8. What you need to do (only these)

| Task | Why | Command |
|---|---|---|
| Install a hidden virtual display | So browser automation never opens windows on your screen | `sudo pacman -S xorg-server-xvfb` |
| Answer the 5 questions below | They change filters and form answers | — |
| *(Rarely)* Re-login to Indeed | Only if Indeed logs you out. Hermes will notify you. | `python scripts/indeed_setup.py` |

---

## 9. Open questions

1. **Salary floor.** No minimum is written anywhere. What's the lowest you'd accept, in ₹ LPA for India/India-remote roles and in USD for global remote roles?
2. **Years of experience.** The config now says **1 year**; it previously said 2. Which is honestly correct?
3. **Seniority.** Keep skipping roles that ask for more than 3 years or have Senior titles, or also send "stretch" applications to 4–5-year roles?
4. **Reaching 100/day.** Honest filtering may leave about 40–80 good matches a day. Add Naukri (login + captcha risk), or accept fewer, better-matched applications?
5. **Visibility.** Make the AWIS repo public, or add a public README/demo? Confirm `linkedin.com/in/saralbanker` is yours.

---

## 10. Risks and honest limits

- **100/day is not guaranteed.** It depends on how many fresh, eligible, well-matched jobs exist each day.
- **Captchas:** some Greenhouse, Lever and Ashby forms show a captcha. Those jobs are skipped, not forced.
- **Seniority gap:** most high-paying remote roles want 3–5+ years. Response rates will be highest on junior and mid-level roles.
- **Laptop must be on** at run times. Missed runs catch up when it wakes (`Persistent=true`).
- **Indeed may change its pages** or tighten Cloudflare. The applier will need occasional fixes.
