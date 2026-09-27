# Phase 1 — Stabilize Core Infrastructure and Re-Prove Submission Engine

---

# Current truth state

Hermes currently contains working components, partially implemented fixes, unknown repository state, uncommitted changes, and conflicting reports from multiple investigation sessions.

Known facts:

- Scheduler is functional.
- Gmail IMAP authentication is functional.
- Crash recovery exists.
- Greenhouse has at least one confirmed submission.
- Indeed historically produced confirmed submissions.
- Direct Forms exist but are not yet proven.
- Lever remains largely unproven.
- Ashby experiences anti-bot blocking.
- Multiple browser-related failures have been observed.
- Orphaned Chrome processes have been observed.
- Application throughput remains significantly below target.
- Repository contains many modified and untracked files.
- Current runtime state is not fully verified.

Target:

- Establish a trustworthy baseline.
- Re-prove application capability.
- Eliminate infrastructure instability.
- Generate evidence before new platform expansion.

---

# Evidence hierarchy

Priority order:

1. Live runtime behavior
2. Confirmed submission evidence
3. SQLite database state
4. Gmail confirmations
5. Application history
6. Process state
7. Systemd state
8. Runtime logs
9. Automated tests
10. Existing documentation
11. Previous AI-generated reports

Whenever evidence conflicts:

Higher-ranked evidence wins.

---

# Phase 1A — Browser Infrastructure Stability

## Execution objective

Fully investigate browser infrastructure.

Determine:

- How Xvfb is created
- How Xvfb is destroyed
- How browsers connect to Xvfb
- Browser lifecycle
- Browser ownership model
- Browser recovery behavior
- Failure recovery behavior
- Port usage
- Chrome profile usage
- DrissionPage startup path
- Playwright startup path

Verify whether failures are caused by:

- Xvfb
- Chrome profile locking
- Dead browser processes
- Port conflicts
- Browser launch races
- Scheduler interactions
- Other causes

Do not assume Xvfb is the root cause.

Root cause must be proven.

---

## Required investigation

Trace:

```text
scheduler
→ browser launcher
→ display manager
→ browser startup
→ browser shutdown
→ cleanup
→ recovery
```

Identify:

```text
files involved
functions involved
dependencies involved
```

Create runtime validation steps.

---

## Success criteria

Must prove:

```text
Browser launches reliably
Browser closes cleanly
Browser survives scheduler execution
No orphaned browser sessions
No profile lock failures
No display failures
```

Final proof:

```text
1 confirmed Indeed submission
```

without manual intervention.

---

# Phase 1B — Chrome Cleanup and Recovery

## Execution objective

Fully investigate process cleanup.

Determine:

- How Chrome processes are tracked
- How child processes are tracked
- What happens after crash recovery
- What happens after SIGTERM
- What happens after SIGKILL
- What happens after scheduler interruption
- What happens after reboot

Verify:

- Orphan cleanup logic
- Recovery logic
- Attempt reclaim logic
- Retry logic

---

## Required investigation

Trace:

```text
job start
→ browser launch
→ application execution
→ browser exit
→ cleanup
```

Trace:

```text
forced crash
→ recovery
→ reclaim
→ resume
```

Determine:

```text
why orphaned Chrome processes exist
why reclaim exceeded attempt cap
whether duplicate applications are possible
```

---

## Success criteria

Must prove:

```text
0 orphaned Chrome processes
0 duplicate applications
attempt cap always enforced
recovery always resumes safely
```

Final proof:

```text
Hard kill Hermes
Restart Hermes
Observe successful recovery
Observe no duplicate applications
```

---

# Phase 1C — Funnel Metrics and Gmail Verification

## Execution objective

Create trustworthy visibility into Hermes.

Current problem:

No verified end-to-end funnel exists.

Need measurable evidence for:

```text
discovered
filtered
scored
tailored
queued
attempted
submitted
confirmed
```

for every channel.

---

## Gmail investigation

Determine:

```text
email ingestion path
reply watcher path
classification logic
storage logic
notification logic
```

Verify:

```text
acknowledgement detection
rejection detection
interview detection
other classification
```

Do not build advanced email intelligence.

Only verify correctness.

---

## Required implementation plan

Create metrics for:

### Indeed

```text
discovered
filtered
scored
attempted
submitted
confirmed
```

### Greenhouse

```text
discovered
filtered
scored
attempted
submitted
confirmed
```

### Direct Forms

```text
discovered
filtered
scored
attempted
submitted
confirmed
```

### Lever

```text
discovered
filtered
scored
attempted
submitted
confirmed
```

### Ashby

```text
discovered
filtered
scored
attempted
blocked_antibot
```

---

## Success criteria

Must generate:

```text
docs/FUNNEL_BASELINE.md
```

containing:

```text
Per channel:

Discovered
Filtered
Scored
Tailored
Queued
Attempted
Submitted
Confirmed
Failure reasons
```

Must also prove:

```text
acknowledgements classified correctly
rejections classified correctly
interviews classified correctly
```

---

# Forbidden assumptions

Do not assume:

- Previous reports are correct
- Documentation is correct
- Tests reflect production
- Xvfb is the root cause
- Browser failures have a single cause
- Greenhouse remains functional
- Direct Forms remain functional
- Gmail classifications are accurate
- Existing metrics are trustworthy
- Submission counts are accurate without evidence

Do not:

- Add new platforms
- Add new ATS integrations
- Add new discovery sources
- Optimize throughput
- Increase worker count
- Modify scoring logic
- Modify tailoring logic
- Expand platform coverage

---

# Required deliverables

Create:

```text
docs/PHASE1_BROWSER_AUDIT.md
docs/PHASE1_RECOVERY_AUDIT.md
docs/FUNNEL_BASELINE.md
```

Each document must contain:

```text
Current architecture
Evidence collected
Files involved
Functions involved
Root cause hypotheses
Validation methodology
Risk assessment
Recommended fixes
Implementation order
Success criteria
```

---

# Phase 1 Exit Conditions

Before Phase 2 begins, all of the following must be true:

```text
1 confirmed Indeed submission
0 orphaned Chrome processes
attempt cap enforced
recovery proven
funnel metrics operational
Gmail classification verified
```

Only after all Phase 1 conditions are satisfied may Hermes proceed to:

```text
Direct Forms
Greenhouse
Lever
Platform expansion
Continuous queue architecture
100/day optimization
```
