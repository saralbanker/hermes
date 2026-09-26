# Hermes — System Architecture

**Repository:** `saralbanker/hermes`
**Branch:** `overhaul-2026-09-23`

## 1. Architecture Overview

Hermes is a single-machine, Python-based, SQLite-backed pipeline.

```text
                        ┌─────────────────────┐
                        │ systemd --user      │
                        │ scheduled timers    │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │ scripts/run_hermes  │
                        │ .sh                 │
                        │ lock / preflight /  │
                        │ timeout / alerts    │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │ src/pipeline.py     │
                        └──────────┬──────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
      │  DISCOVERY   │ ───► │   SCORING    │ ───► │  TAILORING   │
      └──────┬───────┘      └──────────────┘      └──────┬───────┘
             │                                            │
             │                                            ▼
             │                                     ┌──────────────┐
             └────────────────────────────────────►│    APPLY     │
                                                   └──────┬───────┘
                                                          │
                           ┌──────────────────────────────┼────────────────────┐
                           ▼              ▼               ▼          ▼         ▼
                       Indeed       Greenhouse          Lever      Ashby   Direct Forms
                           │              │               │          │         │
                           └──────────────┴───────────────┴──────────┴─────────┘
                                                          │
                                                          ▼
                                                ┌──────────────────┐
                                                │ SQLite database  │
                                                └──────────────────┘


                      Independent background path

                    ┌──────────────────────────┐
                    │ systemd watcher timer   │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │ response_watcher.py      │
                    │ Gmail IMAP → classify    │
                    │ → DB update → notify     │
                    └──────────────────────────┘
```

---

# 2. Main Entry Points

## `scripts/run_hermes.sh`

Unattended operating-system entry point.

Responsibilities:

```text
Acquire process lock
↓
Run preflight
↓
Wait for network when necessary
↓
Check Ollama availability
↓
Start pipeline
↓
Enforce hard execution timeout
↓
Notify on failure
```

The shell script and Python pipeline intentionally share the same lock file:

```text
output/hermes.lock
```

This prevents scheduled and manual runs from overlapping.

---

## `src/pipeline.py`

Main orchestrator.

Default execution:

```text
discover
→ score
→ tailor
→ apply
```

It also supports individual stage execution.

The pipeline does not contain the implementation of each stage. It imports the stage entry point and executes it.

It also:

* initializes the database
* collapses cross-board duplicate roles before downstream work
* creates the virtual display before application
* records stage timing / CPU / memory metrics

---

# 3. Discovery Architecture

## Entry point

```text
src/discover.py
```

## Sources

```text
Indeed
Greenhouse
Lever
Ashby
Himalayas
Remotive
RemoteOK
```

## Flow

```text
Configured target roles
        ↓
Source collectors
        ↓
Normalize job fields
        ↓
Drop duplicate URLs
        ↓
Generate company+title dedupe key
        ↓
Location filter
        ↓
Age filter
        ↓
Role/tier filter
        ↓
Salary filter
        ↓
SQLite
```

## Important modules

```text
discover.py
sources_ats.py
filters.py
geo.py
db.py
config.yaml
```

Discovery stores rejected jobs rather than silently discarding them when appropriate.

Typical stored states at this stage:

```text
discovered
filtered
expired
skipped
```

Cross-board deduplication is based primarily on normalized:

```text
company + title
```

This prevents the same role from consuming downstream scoring and application capacity multiple times.

---

# 4. Scoring Architecture

## Entry point

```text
src/score.py
```

## Local AI path

```text
Job description
      ↓
nomic-embed-text
      ↓
Similarity pre-filter
      ↓
qwen3:4b-instruct-2507-q4_K_M
      ↓
Score + reasoning
      ↓
SQLite
```

## Important properties

Scoring is local.

```text
Ollama
localhost:11434
```

Configured models:

```text
qwen3:4b-instruct-2507-q4_K_M
nomic-embed-text
```

Embedding similarity reduces the number of jobs sent to the LLM.

The LLM writes the final numeric score and reasoning into the database.

Primary transition:

```text
discovered → scored
```

---

# 5. Tailoring Architecture

## Entry point

```text
src/tailor.py
```

## Input

```text
Scored job
+
profile/facts.md
+
selected resume variant
```

## Local AI path

```text
Job
 ↓
Candidate facts
 ↓
Local Qwen model
 ↓
Tailored application material
 ↓
Truthfulness validation
 ↓
output/tailored/
 ↓
SQLite metadata
```

The candidate fact source is:

```text
profile/facts.md
```

`llm.py` exposes this fact sheet as the authoritative candidate-information source.

The tailoring layer contains validation intended to prevent unsupported or misattributed project claims.

Primary transition:

```text
scored → tailored
```

---

# 6. Application Architecture

## Entry point

```text
src/apply.py
```

`apply.py` is the central application dispatcher.

It performs:

```text
Get tailored queue
↓
Apply tier allocation
↓
Duplicate check
↓
Atomic job claim
↓
Channel resolution
↓
Call channel-specific applier
↓
Receive ApplyResult
↓
Persist state
```

---

# 7. Application Queue

Hermes separates roles into:

```text
core
stretch
```

Configured target is approximately:

```text
70% core
30% stretch
```

Stretch roles require a higher score threshold.

Queue construction happens before browser work.

The application engine therefore decides which roles should consume the daily capacity before submission begins.

---

# 8. Application Claiming

A tailored job is not immediately submitted.

It first transitions:

```text
tailored
   ↓
applying
```

using an atomic SQLite update.

This prevents two Hermes processes from taking the same job.

Each claimed job increments:

```text
attempts
```

Maximum:

```text
3 attempts
```

---

# 9. Application Routing

`apply.py` determines the application channel.

Possible channels:

```text
indeed
greenhouse
lever
ashby
redirect
direct
```

Routing logic:

```text
Existing apply_channel?
        │
        ├── yes → use it
        │
        └── no
             ↓
         inspect board
             ↓
         determine channel
```

Redirect targets are resolved before selecting the final applier.

---

# 10. Indeed Architecture

## Main module

```text
src/indeed_apply.py
```

Indeed uses an authenticated persistent browser profile.

Browser execution:

```text
Playwright / Chrome
        ↓
Xvfb virtual display
        ↓
Indeed application page
        ↓
Form interaction
        ↓
Submission
        ↓
Success evidence
```

The application engine can also detect an external:

```text
Apply on company site
```

path.

That path is passed to:

```text
src/redirect_resolver.py
```

which determines whether the destination is:

```text
Greenhouse
Lever
Ashby
Direct employer form
```

or unsupported.

---

# 11. ATS Architecture

## Main module

```text
src/ats_apply.py
```

ATS support:

```text
Greenhouse
Lever
Ashby
```

Shared flow:

```text
ATS URL
 ↓
Playwright
 ↓
Field extraction
 ↓
Answer resolution
 ↓
Form filling
 ↓
Validation
 ↓
Submit
 ↓
Evidence
```

DOM extraction support is provided by:

```text
src/ats_extract.js
```

Candidate answers come from:

```text
src/answers.py
```

---

# 12. Greenhouse OTP Architecture

Greenhouse may require a security code.

Flow:

```text
Greenhouse application
        ↓
OTP requested
        ↓
Gmail receives code
        ↓
otp_resolver.py
        ↓
Gmail IMAP
        ↓
Extract code
        ↓
Enter into browser
        ↓
Continue application
        ↓
Confirmation
```

Credential handling is centralized through the Gmail helpers.

---

# 13. Direct Form Architecture

## Main module

```text
src/direct_form.py
```

Used when an employer has a hand-built application form rather than a supported ATS.

It reuses form-processing primitives from:

```text
ats_apply.py
```

where applicable.

Flow:

```text
Resolved employer URL
        ↓
Direct-form browser
        ↓
Inspect fields
        ↓
Map candidate answers
        ↓
Fill fields
        ↓
Advance / submit
        ↓
Return ApplyResult
```

Current architecture supports the channel, but production success is not yet sufficiently proven.

---

# 14. Redirect Architecture

## Main module

```text
src/redirect_resolver.py
```

Purpose:

```text
Aggregator/listing URL
        ↓
Real browser navigation
        ↓
Employer destination
        ↓
Detect ATS or direct form
```

Used for:

```text
Remotive
Himalayas
RemoteOK
Indeed external Apply links
```

This prevents the main application engine from needing to know every aggregator's redirect behavior.

---

# 15. Application Result Contract

All application engines return:

```text
states.ApplyResult
```

Defined in:

```text
src/states.py
```

Structure:

```text
state
detail
screenshot
evidence
meta
```

The important architectural rule is:

```text
Appliers return results.
apply.py owns DB state transitions.
```

Application modules should not invent independent database state strings.

---

# 16. State Architecture

Core lifecycle:

```text
discovered
    ↓
scored
    ↓
tailored
    ↓
applying
    ↓
submitted
```

Failure branches include:

```text
filtered
skipped
expired
invalid
login_required
security_interstitial
captcha_required
blocked_antibot
otp_required
network_error
form_changed
already_applied
submission_unconfirmed
unsupported_channel
model_unavailable
model_timeout
failed
```

Retryable states are explicitly defined in:

```text
src/states.py
```

The current retryable set is:

```text
security_interstitial
network_error
failed
login_required
otp_required
model_unavailable
model_timeout
```

with:

```text
MAX_ATTEMPTS = 3
```

---

# 17. Submission Verification

A job is not considered successfully submitted merely because a submit button was clicked.

`ApplyResult` enforces:

```text
SUBMITTED
+
evidence
```

Otherwise the result is rejected as an invalid success result.

This creates the central application invariant:

```text
No evidence → no submitted state
```

For uncertain submission outcomes:

```text
submission_unconfirmed
```

is used so Hermes does not blindly resubmit.

---

# 18. Database Architecture

Primary persistence:

```text
SQLite
db/applications.db
```

Schema:

```text
db/schema.sql
```

Core tables:

```text
jobs
daily_limits
responses
```

`responses` is initialized by the Gmail watcher.

Important `jobs` data includes:

```text
URL
company
title
description
location
salary
score
score_reason
tier
required_years
status
status_reason
attempts
resume_variant
cover_letter_path
application evidence
response information
timestamps
```

---

# 19. Database Responsibilities

`src/db.py` provides the persistence boundary for:

```text
insert/update jobs
job lookup
deduplication
application claiming
daily counters
status counts
tier counts
database initialization
schema migration
```

The application engine does not maintain an independent in-memory source of truth.

SQLite is the shared state between pipeline stages.

---

# 20. Daily Capacity Architecture

## Module

```text
src/cap_enforcer.py
```

Before an application is attempted:

```text
daily count
↓
limit check
↓
allow / stop
```

Configured limits:

```text
LinkedIn: 0
Other boards: 100
Total: 100
```

Daily counts are persisted in:

```text
daily_limits
```

A successful submission increments the daily counter.

---

# 21. Browser Runtime Architecture

Browser execution depends on:

```text
Google Chrome / Chromium
Playwright
Xvfb
persistent browser profiles
```

Virtual display management:

```text
src/display.py
```

Hermes creates private virtual displays so headful browser sessions can run without appearing on the user's normal desktop.

The architecture intentionally uses headful browser execution under Xvfb rather than assuming headless mode works for every target.

---

# 22. Browser Recovery

`display.py` also handles cleanup of Hermes-owned browser resources.

It identifies only Hermes-specific browser profiles and Hermes Xvfb instances.

This avoids killing unrelated desktop browser processes.

Startup cleanup is designed to remove:

```text
orphan Chrome processes
stale Singleton locks
orphan Hermes Xvfb processes
```

---

# 23. Gmail Architecture

Gmail functionality is shared between:

```text
otp_resolver.py
response_watcher.py
```

Credential access is centralized.

Connection:

```text
Gmail
 ↓
IMAP over TLS
 ↓
Hermes
```

The application itself does not need a separate email subsystem.

---

# 24. Response Watcher Architecture

## Module

```text
src/response_watcher.py
```

Execution is independent of the main job pipeline.

```text
systemd watcher timer
        ↓
response_watcher.py
        ↓
Gmail inbox
        ↓
message parsing
        ↓
deterministic classification
        ↓
responses table
        ↓
matching submitted job
        ↓
desktop notification when positive
```

Classification is deterministic.

No LLM is required.

Categories:

```text
positive
rejection
ack
other
```

A previously positive response is never downgraded by a later weaker classification.

---

# 25. Notification Architecture

Notifications are handled through:

```text
src/notify.py
```

Used for:

```text
positive employer responses
scheduler failures
login requirements
runtime failures
```

Desktop notification is an operational side effect, not part of core job state.

---

# 26. Local LLM Architecture

## Single client

```text
src/llm.py
```

This is the common interface for local model communication.

Consumers include:

```text
score.py
tailor.py
```

The module handles:

```text
chat
embedding
model availability
timeouts
HTTP failures
response validation
```

This avoids maintaining separate Ollama clients with different error behavior.

---

# 27. Configuration Architecture

Primary configuration:

```text
config.yaml
```

It contains:

```text
candidate profile metadata
geographic rules
salary rules
search sources
target roles
scoring thresholds
daily limits
resume paths
LLM configuration
notification settings
screening answers
```

Secrets are not intended to live in `config.yaml`.

---

# 28. Candidate Truth Architecture

Candidate factual information is sourced from:

```text
profile/facts.md
```

The LLM should not invent candidate facts outside the verified fact source.

Application-specific deterministic answers are stored separately in:

```text
src/answers.py
```

This creates two distinct layers:

```text
facts.md
    ↓
candidate truth

answers.py
    ↓
how that truth is expressed in application fields
```

---

# 29. Reliability Boundaries

Hermes intentionally isolates failures by stage.

Example:

```text
One discovery source fails
        ↓
Other discovery sources continue
```

```text
One application fails
        ↓
Result is recorded
        ↓
Next job continues
```

```text
One model request fails
        ↓
LLM failure is represented explicitly
        ↓
Caller can use fallback behavior
```

```text
One Gmail message cannot be parsed
        ↓
That message is skipped
        ↓
Watcher continues
```

The system should therefore fail at the smallest practical unit rather than terminating the entire batch.

---

# 30. Critical Architectural Invariants

These must remain true during future modifications:

```text
1. Only apply.py converts ApplyResult into persisted application states.

2. SUBMITTED requires evidence.

3. Applying the same role twice must be prevented by dedupe checks.

4. A job must be atomically claimed before browser application begins.

5. Application attempts must never exceed MAX_ATTEMPTS.

6. submission_unconfirmed must never be blindly retried.

7. Candidate facts used by LLMs must come from verified sources.

8. Daily application limits must be enforced before submission.

9. A failed discovery source must not stop unrelated discovery sources.

10. One failed application must not terminate the remaining queue.

11. Browser cleanup must affect only Hermes-owned browser/display resources.

12. SQLite remains the shared state between stages.
```

---

# 31. Primary Dependency Graph

```text
run_hermes.sh
    ↓
pipeline.py
    ├── discover.py
    │     ├── sources_ats.py
    │     ├── filters.py
    │     ├── geo.py
    │     └── db.py
    │
    ├── score.py
    │     ├── llm.py
    │     ├── filters.py
    │     └── db.py
    │
    ├── tailor.py
    │     ├── llm.py
    │     ├── filters.py
    │     └── db.py
    │
    └── apply.py
          ├── indeed_apply.py
          ├── ats_apply.py
          │     ├── ats_extract.js
          │     └── otp_resolver.py
          ├── direct_form.py
          ├── redirect_resolver.py
          ├── answers.py
          ├── cap_enforcer.py
          ├── display.py
          └── db.py


response_watcher.py
    ├── otp_resolver.py
    ├── db.py
    └── notify.py
```

---

# 32. What Should Not Be Introduced Without Need

Hermes is intentionally not an enterprise distributed system.

Do not introduce by default:

```text
microservices
message brokers
Redis
PostgreSQL
Kubernetes
cloud browser infrastructure
paid LLM APIs
distributed workers
complex agent orchestration
```

The existing architecture is intentionally:

```text
one machine
one Python application
SQLite
local Ollama
systemd
browser automation
```

Future changes should improve reliability and application coverage before introducing architectural complexity.

---

# 33. Architecture Change Rule

When modifying Hermes:

```text
Preserve the existing pipeline
unless the current architecture is proven to be the cause of the problem.
```

Prefer:

```text
small module change
+
tests
+
runtime verification
```

over:

```text
large rewrite
```

A new abstraction is justified only when the existing boundary is demonstrably causing repeated problems.

---

# 34. Simplified Mental Model

The entire system can be understood as:

```text
FIND
 ↓
FILTER
 ↓
RANK
 ↓
PREPARE
 ↓
APPLY
 ↓
VERIFY
 ↓
TRACK RESPONSE
```

with SQLite connecting every step.

The most important control module is:

```text
apply.py
```

The most important persistence module is:

```text
db.py
```

The most important lifecycle contract is:

```text
states.py
```

The most important configuration source is:

```text
config.yaml
```

The most important candidate-truth source is:

```text
profile/facts.md
```
