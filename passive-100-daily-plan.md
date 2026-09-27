# Hermes — Shortest Path to 100 Daily Applications

**Target:** 100 confirmed applications/day, continuously unattended, on the existing laptop, with no recurring API cost.

---

# Stage 1

## Current truth state

The core pipeline works.

The immediate blocker is the Xvfb ownership bug in `src/display.py`, which currently destroys Hermes' own Xvfb process and breaks browser application.

The previous plan also incorrectly treats today's `6026 raw → 4 eligible` result as evidence for a future 700–800 eligible/day requirement. Most scraped jobs were already in the database, so raw volume and fresh-job volume were conflated.

Other verified problems:

* Infrastructure failures consume application attempts.
* Gmail response classification is incorrect.
* Direct Forms are unproven.
* Lever is unproven.
* Ashby is blocked by platform anti-bot behavior.

## Evidence hierarchy

Runtime → DB → external application evidence → email → tests → logs → documentation.

## Investigation objective

Audit only the defects that can prevent unattended submission:

1. Xvfb/browser lifecycle.
2. Application attempt accounting.
3. Queue continuity after a failed job.
4. Gmail classification.
5. Current fresh-job supply after deduplication.

Do not expand platforms yet.

## Forbidden assumptions

* 6,000 raw jobs means 6,000 usable jobs.
* 700–800 eligible jobs/day is required.
* 1,500 ATS companies are required.
* 100/day is achievable before measuring fresh supply.
* Ashby should be bypassed.

## Required deliverable

A verified baseline where:

```text
browser works
+
attempts are safe
+
queue survives individual failures
+
fresh-job/day is measurable
```

---

# Stage 2

## Current truth state

After Stage 1, Hermes can reliably consume jobs again.

The remaining challenge is keeping the queue full enough for continuous application.

Existing discovery already uses Indeed, ATS feeds, Himalayas, Remotive, and RemoteOK.

Public supply can be expanded without immediately creating a 1,500-company registry.

## Evidence hierarchy

Fresh eligible jobs/day → tailored jobs/day → queued jobs/day → submitted jobs/day.

## Execution objective

### Phase 2A — Make Hermes continuous

Replace the three large application bursts with:

```text
DISCOVERY/SCORING/TAILORING
        ↓
continuous queue
        ↓
APPLICATION WORKER
```

Use systemd so the application worker stays alive and restarts automatically.

Discovery/refill can run hourly.

Application processing should run continuously whenever:

```text
queue > 0
daily cap > 0
```

### Phase 2B — Expand supply selectively

Add only high-value sources that are cheap/free to access.

First:

```text
We Work Remotely RSS
Jobicy public API
Arbeitnow
```

Then expand Greenhouse/Lever company coverage based on actual India/remote hiring yield.

Do not jump directly to 1,500 ATS companies.

### Phase 2C — Fix freshness

The real metric becomes:

```text
fresh jobs discovered/day
```

not:

```text
raw jobs scraped/day
```

Prevent old database rows from dominating every cycle.

## Forbidden assumptions

* More ATS companies automatically produce more fresh jobs.
* Every public feed is worth integrating.
* Every discovered role should be stored permanently without cost/benefit.
* More scraping is better than better freshness.

## Required deliverable

Enough fresh qualified jobs to maintain:

```text
at least 120–150 tailored/queueable jobs/day
```

before expanding again.

---

# Stage 3

## Current truth state

Greenhouse is proven.

Indeed is proven historically and must be re-enabled after Stage 1.

Lever and Direct Forms need production proof.

Ashby is blocked and should not consume development time.

The previous plan incorrectly makes Ashby stealth a core task; remove it entirely.

## Evidence hierarchy

Confirmed real submission → employer acknowledgement → application history → DB → runtime evidence.

## Execution objective

### Phase 3A — Core channels

Get these reliable first:

```text
Indeed
Greenhouse
Direct Forms
```

### Phase 3B — Lever

Give Lever one real production path.

Only add Lever-specific logic when an actual form proves generic ATS handling is insufficient.

### Phase 3C — Direct Forms

Support the common form subset:

```text
text
textarea
select
radio
checkbox
file upload
next
submit
```

Unknown field:

```text
stop
→ form_changed
→ continue next job
```

### Phase 3D — Ashby

Keep:

```text
blocked_antibot
```

Do not implement stealth/evasion/bypass logic.

### Phase 3E — Optional platform expansion

Only add another candidate-facing platform when measured ATS/direct-form supply cannot sustain 100/day.

Potential access to prepare:

```text
Naukri
Foundit
Instahyre
Wellfound
LinkedIn
```

Treat LinkedIn as optional because Hermes currently has its application limit set to zero.

## Forbidden assumptions

* Every ATS needs dedicated code.
* Every platform is worth integrating.
* Ashby must work.
* LinkedIn is required for 100/day.
* One successful dry-run proves production.

## Required deliverable

At least:

```text
Indeed       = reliable
Greenhouse   = reliable
Direct Form  = reliable for common forms
Lever        = verified or explicitly unsupported
Ashby        = safely skipped
```

plus enough additional sources to keep the queue full.

---

# Stage 4

## Current truth state

At this point the system should have:

```text
continuous queue
+
working application channels
+
fresh job supply
```

The remaining question is actual throughput.

## Evidence hierarchy

Real submitted applications/day → application time/job → queue depth → failure rate.

## Final objective

### Phase 4A — Start with one application worker

Measure:

```text
applications/hour
success rate
browser stability
CPU/RAM/temperature
```

Do not immediately create 5 parallel browsers.

### Phase 4B — Scale only when necessary

If one worker cannot reach 100/day:

```text
2 workers
→ measure
```

If still insufficient and stable:

```text
3 workers
→ measure
```

Stop increasing concurrency when the laptop becomes unstable or channel failure rates rise.

### Phase 4C — Continuous 24/7 operation

Architecture:

```text
systemd
├── discovery/refill
├── scoring/tailoring
├── application worker
└── Gmail watcher
```

The application worker continuously consumes the queue instead of waiting for scheduled bursts.

### Phase 4D — Measure the actual funnel

Track only:

```text
fresh jobs
eligible
score-passed
tailored
queued
attempted
submitted
failed
```

Find the largest loss.

Fix that loss.

Repeat.

### Phase 4E — 100/day target

Do not define success as:

```text
100 attempts
```

Define success as:

```text
100 confirmed submissions
```

while maintaining:

```text
truthful applications
duplicate protection
submission evidence
3-attempt maximum
daily cap
safe recovery
```

## Forbidden assumptions

* 100/day is guaranteed by code.
* More concurrency always increases throughput.
* More platforms are always necessary.
* A fixed five-run schedule is truly 24/7.
* Low-quality jobs should be submitted to hit 100.

## Required deliverable

Hermes continuously runs:

```text
discover
→ filter
→ score
→ tailor
→ queue
→ apply
→ verify
```

and reaches:

```text
100 confirmed submissions/day
```

without manual intervention, while keeping the existing SQLite + Ollama + Playwright/DrissionPage + systemd architecture.

# Final Execution Order

```text
1. Fix Xvfb
2. Fix attempt accounting
3. Fix Gmail classifier
4. Re-prove Indeed
5. Make application worker continuous
6. Measure fresh-job supply
7. Add WWR + Jobicy + Arbeitnow
8. Expand Greenhouse/Lever coverage selectively
9. Prove Direct Forms
10. Prove Lever
11. Skip Ashby
12. Add Naukri/Foundit/Instahyre/Wellfound only if supply requires them
13. Start with 1 browser worker
14. Scale to 2, then 3 only if required
15. Measure continuously
16. Fix the largest throughput loss
17. Reach 100 confirmed/day
18. Freeze production baseline
```
