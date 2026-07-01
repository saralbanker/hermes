---
name: system-auditor
description: "Use this skill when investigating system-level failures, mysterious behaviors, or multi-component issues where the root cause is unknown and may span services, config, or infrastructure."
version: 1.0.0
triggers:
  - "system failure"
  - "not working in production"
  - "works locally breaks in prod"
  - "investigate"
  - "trace the issue"
  - "find the root cause"
  - "@system-auditor"
token_budget: 3500
tools_required:
  - view_file
  - run_terminal
  - search_code
output_contract:
  format: "Evidence-based incident report + root cause + fix plan"
  includes:
    - symptom-log
    - pipeline-trace
    - root-cause
    - blast-radius
    - fix-plan
works_with:
  - debugging-master
  - performance-optimizer
  - dependency-analyzer
  - task-planner
risk: high
---

## Mission

Investigate system-level failures by following evidence, not intuition. Trace the request pipeline from input to output, find where reality diverges from expectation, apply the Five Whys to reach a structural root cause, assess blast radius across dependent systems, and produce a fix plan with both immediate mitigation and permanent prevention. Every conclusion is backed by logs, metrics, or observed state — never by "probably."

## When To Activate

- A system or service is down or behaving incorrectly in production
- Something works locally but breaks in staging/production
- Multiple components are failing simultaneously
- The root cause is unknown and may span services, config, or infrastructure
- **Anti-trigger**: Do NOT activate for single-function bugs (use `debugging-master`) or performance-only issues (use `performance-optimizer`)

## Core Concepts

### 1. Symptom vs Cause
The error message is the **symptom**. The root cause is what made that error possible. "500 Internal Server Error" is a symptom. "Missing `DATABASE_URL` env variable in production deployment config" is the cause. Never stop at the symptom. Never report the symptom as the finding.

### 2. Pipeline Traversal
Every system failure happens somewhere in the pipeline: `input → validation → processing → storage → output`. Start at the input edge (where the request enters the system). Trace forward step by step until you find where reality diverges from expectation. That divergence point is the investigation focus.

```
Request → Load Balancer → API Gateway → Auth Middleware → Handler → DB Query → Response
                                                              ↑
                                          "Divergence here: handler receives null user"
```

### 3. Evidence Before Hypothesis
Collect logs, metrics, and current state BEFORE forming a hypothesis. Forming a hypothesis first causes confirmation bias — you unconsciously seek evidence that supports it and ignore evidence that contradicts it. Evidence first, hypothesis second, always.

### 4. Blast Radius
Before fixing, determine what else is affected. A database connection pool exhaustion affects ALL services using that DB, not just the one that reported the error. Map the blast radius:
- What services share this dependency?
- What users/features are impacted?
- Is data integrity at risk?

### 5. Five Whys
For each answer to "why did this fail?", ask why again. Stop at 5 or when you reach a **structural** cause:
```
1. Why did the API return 500? → DB query timed out
2. Why did the DB query time out? → Connection pool exhausted
3. Why was pool exhausted? → Connections not being released after use
4. Why aren't connections released? → Missing `finally` block in query wrapper
5. Why wasn't this caught? → No connection pool monitoring or alerting
```
Root cause: missing connection cleanup + no monitoring. Fix both.

## Reasoning Graph

```
[INPUT: System failure description]
  │
  ├─► [CLASSIFY: Do we have logs?]
  │     │
  │     ├─► [BRANCH A: Logs available]
  │     │     ├── Extract error timestamps + messages
  │     │     ├── Find FIRST error in timeline (not latest)
  │     │     │     └── `sort -t'T' -k2 error.log | head -5`
  │     │     ├── Trace pipeline from that point forward
  │     │     ├── Identify divergence point
  │     │     │     └── Where does actual state ≠ expected state?
  │     │     ├── Apply 5 Whys from divergence point
  │     │     ├── Assess blast radius
  │     │     │     └── What else depends on the failing component?
  │     │     └── [VALIDATE: root cause is structural, not accidental]
  │     │
  │     └─► [BRANCH B: No logs / blind investigation]
  │           ├── List all components in the request path
  │           ├── Test each component's health independently:
  │           │     ├── DB: `SELECT 1` or connection test
  │           │     ├── Cache: `redis-cli ping`
  │           │     ├── API: `curl http://localhost:PORT/health`
  │           │     └── Queue: check consumer lag
  │           ├── Binary search: failure before or after component X?
  │           ├── Isolate failing component
  │           ├── Enable logging → reproduce → now go to Branch A
  │           └── [VALIDATE]
  │
  └─► [OUTPUT: Incident report]
```

## Execution Steps

### Branch A: Logs Available

### Step 1: Collect Evidence
Gather: error logs, timestamps, affected endpoints/services, recent deployments or config changes.
```bash
# Recent errors sorted by time
grep -i "error\|fatal\|exception" /var/log/app/*.log | sort | tail -50

# Recent deployments
git log --oneline -10 --since="2 days ago"

# Environment diff
diff <(env | sort) <(ssh prod 'env | sort')  # compare local vs prod env
```

### Step 2: Find the First Error
Sort events chronologically. The **first** error is the cause; subsequent errors are cascading failures. The most recent error is usually a consequence, not the origin.

### Step 3: Identify the Component
Which service/module produced the first error? That is your investigation scope. Don't investigate everything — investigate the origin.

### Step 4: Trace Backwards
What inputs does the failing component receive? Are they valid? Follow data upstream until you find the source of invalid/missing data.

### Step 5: Apply Five Whys
Starting from the first error, ask "why?" five times. Stop when the answer is structural (missing test, missing monitoring, bad default config) not accidental ("someone typo'd a variable").

### Step 6: Assess Blast Radius
```bash
# What imports/depends on the failing module?
grep -rn "import.*from.*<failing-module>" src/

# What services connect to the failing DB/cache/queue?
grep -rn "DATABASE_URL\|REDIS_URL" */config/ */.env
```

### Step 7: Produce Fix Plan
Two parts:
1. **Immediate mitigation**: Restore service NOW (rollback, restart, config fix)
2. **Root fix**: Prevent recurrence (code fix, add monitoring, add test, fix deploy pipeline)

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| Logs show no errors but system is broken | Silent failure — errors are swallowed | Add logging at suspected failure points, reproduce, check return values |
| Works locally, fails in prod | Environment difference (env vars, versions, network) | `diff` local config against prod config; check `node -v`, dependency versions |
| Issue disappears when investigated | Timing/load-dependent (Heisenbug) | Reproduce under load (`ab -n 1000 -c 50 http://...`); add persistent metrics, not interactive debugging |
| Multiple simultaneous failures | Shared dependency failed (DB, cache, DNS, cert) | Check health of shared infrastructure FIRST before investigating individual services |
| Logs are too noisy to find the signal | No log levels or structured logging | Filter: `grep -v "INFO\|DEBUG" logs.txt` to see only WARN/ERROR/FATAL |

## Validation Gate

- [ ] Root cause identified (structural, not accidental)
- [ ] Five Whys applied — stopped at a structural/systemic cause
- [ ] Blast radius assessed — other affected systems listed
- [ ] Timeline reconstructed from the FIRST error, not the most recent
- [ ] Fix plan has BOTH immediate mitigation AND permanent root fix
- [ ] Evidence cited for every conclusion (log line, metric, observed state)

## Output Contract

Incident report containing:
- **Symptom log**: What was observed, when, by whom, frequency
- **Pipeline trace**: Which components were checked, where divergence was found
- **Root cause**: The structural issue, reached via Five Whys, with evidence (file:line or log excerpt)
- **Blast radius**: List of other systems/features affected by the root cause
- **Fix plan**: Immediate mitigation (restore service) + root fix (prevent recurrence) + monitoring additions
