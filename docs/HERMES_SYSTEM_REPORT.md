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

- **Saral Banker**, Shahibaug, Ahmedabad · +91 9106990136 · saralbanker1@gmail.com
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

## 4. How it works (after the 2026-09-23 evening overhaul)

```
DISCOVER → NORMALIZE/DEDUPE → HARD FILTER → EMBED PRE-RANK → LLM SCORE → CORE/STRETCH
→ TAILOR (fact-checked) → RESUME VARIANT → ROUTE CHANNEL → APPLY → VERIFY → TRACK → WATCH REPLIES
```

| Stage | Module | Notes |
|---|---|---|
| Discover | `src/discover.py`, `src/sources_ats.py` | Indeed (remote + Ahmedabad), Greenhouse/Lever/Ashby APIs (147 companies), Himalayas, Remotive, RemoteOK. Cross-board dedupe on normalised company+title; only an *eligible* listing claims a role. |
| Filter | `src/filters.py`, `src/geo.py` | Engineering-title allow-list; QA/support/sales/recruiting/design/analyst/PM excluded (title decisive, description only by duty phrases). Remote must be open to India (also checks the description's `Location:` line). On-site ≤20 km of Shahibaug, ≤10 km for night shift. Pay floors ₹25k/month India, ₹30k/month global. Tier: core ≤4 years & non-senior; stretch = Senior/Lead/founding or 5–8 years; >8 years or management → filtered. |
| Score | `src/score.py` | nomic-embed pre-rank, then qwen3 4B 1–10, ordered by role priority (AI > backend > full-stack > SWE > automation > frontend). Max 250/run. Keyword fallback if Ollama is down. |
| Tailor | `src/tailor.py` | Core ≥6.5, stretch ≥7.5. Max 60 letters queued. Validator rejects numbers not in facts, absent skills/domains, "% ", and any "N years of professional experience" overstatement. Template fallback. |
| Apply | `src/apply.py` + `src/states.py` | State machine; 70/30 core/stretch allocation of the day's plan; atomic claim; dedupe; channel router (indeed / greenhouse / lever / ashby / redirect); only a confirmation page counts as submitted; retryable failures re-queued up to 3 attempts; channel breaker on login/Cloudflare; 150 min budget per run. |
| Browsers | `src/display.py` | Headful Chrome inside a private Xvfb display (never on the Wayland desktop). Not an anti-bot bypass: CAPTCHAs/Turnstile are classified and skipped. |
| Answers | `src/answers.py` | Deterministic rules; skill-specific "years of X" answered from facts (0 when absent or academic-only); sponsorship/authorization depend on the job's country; LLM only for open questions, with the posting as context; `None` (skip job) rather than a guess. |
| Replies | `src/response_watcher.py`, `src/notify.py` | Gmail IMAP poll every 10 min, deterministic classifier (positive/rejection/ack/other), persistent dedupe table `responses`, urgent desktop notification + sound for positives, 21:00 summary. |
| Schedule | `scripts/run_hermes.sh`, `scripts/*.timer`, `scripts/install_timers.sh` | 08:00/13:00/19:00 (Persistent), flock single-instance, network wait, Ollama start via its user service, 4 h hard timeout, failure notifications. |

States: `discovered → filtered | scored → tailored → applying → submitted`, failures:
`skipped, expired, invalid, login_required, security_interstitial, captcha_required, otp_required,
network_error, form_changed, already_applied, submission_unconfirmed, unsupported_channel, failed`.

## 5. Operations

| Task | Command |
|---|---|
| Status | `scripts/hermes-status.sh` |
| Full run now (same as timer) | `systemctl --user start hermes.service` or `scripts/run_hermes.sh` |
| Dry run (fills forms, never submits) | `scripts/run_hermes.sh --dry-run --limit 5` |
| Apply only | `scripts/run_hermes.sh --apply-only` |
| Stop scheduling | `systemctl --user disable --now hermes.timer` |
| Stop a run in progress | `systemctl --user stop hermes.service` |
| Logs | `tail -f output/hermes_cron.log`, `journalctl --user -u hermes -u hermes-watch` |
| Metrics per run | `tail -1 output/metrics.jsonl` |
| Re-login to Indeed | `python scripts/indeed_setup.py` |
| Tests | `python -m pytest tests -q` |

## 6. Known limitations

- Indeed sometimes shows an interactive Cloudflare "Verify you are human" check. Hermes records
  `security_interstitial`, retries on a later run, and pauses Indeed for the run after 3 in a row.
- Gmail App Password in `output/gmail_app_password.txt` is rejected by Google (must be regenerated) —
  until then email OTP and reply watching cannot read mail.
- Forms that require a take-home link, or an answer not supported by the facts, are skipped (`form_changed`).
- 100/day depends on supply: about 24% of scored jobs reach the apply threshold.
