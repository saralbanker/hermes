# Hermes — Master Plan

**Document ID:** `HERMES-MASTER-PLAN-2026-09-27`  
**Status:** ACTIVE MASTER PLAN UNDER FROZEN ARCHITECTURE  
**Parent:** `ARCHITECTURE_REDESIGN_FINAL-2026-09-27-FROZEN.md`  
**Repository:** `saralbanker/hermes`  
**Baseline branch:** `overhaul-2026-09-23`  
**Target runtime:** Arch Linux · Ryzen 7 7730U · 16 GB RAM · Vega 8 iGPU · CPU-only  
**Primary runtime:** Ollama · SQLite/WAL · local Chromium/Chrome via BrowserGateway  
**Operating mode:** Continuous unattended worker while the laptop is available  
**Primary objective:** 100 truthful, confirmed, qualified new applications/day

> **Authority:** The frozen architecture is the parent technical specification. This Master Plan is the project-level execution contract beneath it. Every lower-level plan, prompt, implementation, and verification activity must work downward from these two documents. Lower-level documents may add implementation detail; they may not silently redefine architecture.

---

# 1. Mission

Hermes is a local-first job application automation system that continuously:

```text
DISCOVERS jobs
→ IDENTIFIES canonical opportunities
→ REFRESHES current state
→ APPLIES hard eligibility
→ RANKS fit
→ SCHEDULES by opportunity age
→ TAILORS application material just in time
→ RESOLVES a legitimate application route
→ SUBMITS through supported browser/channel automation
→ VERIFIES the outcome with evidence
→ RECORDS durable truth
→ MONITORS employer responses
→ REFILLS the actionable supply
```

The project is not a scraping script, a browser macro, or a security-evasion tool. The system's central problem is reliable stateful throughput under a single-machine, local-only constraint.

---

# 2. Primary Objective and Success Definition

## 2.1 Throughput target

The target is:

```text
100 confirmed, qualified new applications per 24 hours
```

Equivalent average rate:

```text
4.17 confirmed, qualified applications/hour
1 confirmed, qualified application every ~14.4 minutes on average
```

This is an operating target, not an architectural guarantee.

## 2.2 What counts

Only a newly submitted application with sufficient evidence counts toward the daily target.

```text
confirmed submission   = +1
already applied        = +0
unconfirmed submission = +0
failed                 = +0
blocked                = +0
```

A submit click, HTTP response, or local `ApplyResult` alone is not sufficient evidence of success.

## 2.3 Quality boundary

Throughput must never be increased by:

```text
fabricated candidate information
blind duplicate submission
fabricated confirmation
clearly ineligible applications
bypassing CAPTCHA / Turnstile / Cloudflare security controls
fake accounts used to evade platform restrictions
```

---

# 3. Hard Project Constraints

## 3.1 Hardware and runtime

```text
single laptop
Arch Linux
Ryzen 7 7730U
16 GB RAM
Vega 8 iGPU
CPU-only local inference
practical AI RAM budget: 7–10 GB
practical model-storage objective: 5–8 GB
SQLite/WAL
Ollama
local browser automation
no required cloud inference
no recurring paid API/service dependency
```

## 3.2 Availability

Hermes is designed as a continuous local service, not as three daily application batches.

```text
systemd-managed worker
+ continuous discovery/refill
+ continuous application consumption
+ independent response monitoring
```

## 3.3 Candidate/job policy

The current operating policy is parameterized and must remain configurable rather than scattered through source code.

Primary role families include:

```text
AI engineering
backend engineering
software engineering
full-stack engineering
founding / technical engineering
AI application development
TypeScript / Python / Node.js engineering
LLM-oriented engineering
```

Excluded role families include:

```text
QA
support
teaching / tutoring
non-technical operations
```

Location policy:

```text
remote roles: must be compatible with hiring from India
normal office/hybrid: within 20 km of Shahibaug, Ahmedabad
night-shift office/hybrid: within 10 km of Shahibaug, Ahmedabad
relocation is not assumed
```

Salary policy:

```text
India / India-remote published floor: ₹25,000/month
global remote published floor: ₹30,000/month equivalent
unknown published salary: not automatically rejected
```

Experience targeting:

```text
~70% core opportunities
~30% stretch opportunities
```

Stretch is a preference and must never override hard eligibility or fresh-first age priority.

Candidate facts are authoritative only when supported by the project fact source, currently `profile/facts.md`. Model prompts, config, and implementation code must not invent a competing candidate profile.

---

# 4. Frozen Architecture Inheritance

The Master Plan does not repeat the full architecture. It inherits the following decisions as immutable project constraints.

## 4.1 Canonical identity

```text
job URL = source locator / observation
canonical opportunity = durable identity
source observations = history of what sources reported
application attempts = history of what Hermes actually did
channel health = operational health of an application route
```

A confirmed prior application protects the canonical opportunity from duplicate application. Historical filtered/scored/skipped records do not permanently tombstone a still-valid opportunity.

## 4.2 Age and scheduling

The automatic application horizon is exactly 21 days:

```text
0–3 days
4–7 days
8–14 days
15–21 days
```

`>21 days` is terminal for automatic application.

Scheduling is a strict age cascade:

```text
0–3d → 4–7d → 8–14d → 15–21d
```

Fit ranks candidates within an available band. A freshly discovered candidate can preempt an older candidate at the next claim.

WFQ is not part of the base system.

## 4.3 Database

```text
SQLite is the system of record
WAL remains enabled
atomic claims use short write transactions
BEGIN IMMEDIATE where an immediate write claim is required
no SELECT ... FOR UPDATE
no browser-held DB write locks
no routine DB rewind after browser crash
backups are disaster-recovery snapshots
```

## 4.4 Browser

```text
BrowserGateway is the browser boundary
CDP adapter + Playwright adapter
structured DOM/ARIA/frame/shadow-root state
state-based readiness for SPAs
deterministic action validation
persistent sessions where authentication requires them
disposable contexts where isolation is useful
adaptive browser lifecycle
```

The browser architecture does not require a browser-agent LLM and does not require a new Chromium process per job.

## 4.5 AI

The frozen four-model baseline is:

```text
qwen3.5:4b
    primary generation specialist
    tailoring + difficult screening reasoning

phi4-mini:3.8b
    scoring / classification specialist

nomic-embed-text:v1.5
    embeddings / cheap pre-ranking

BAAI/bge-reranker-base
    ONNX top-k semantic reranking
```

Normal residency is sequential:

```text
one primary generative specialist at a time
```

The exact quantization, context size, batching, and timing are verification/tuning work; changing the baseline model architecture requires explicit architecture review.

## 4.6 Security

Hermes does not bypass or defeat:

```text
CAPTCHA
Turnstile
Cloudflare security challenges
rate limits
account verification
other platform security controls
```

A blocked route becomes a typed operational outcome and may be replaced by another legitimate supported route when one exists.

---

# 5. Project Baseline

The repository snapshot immediately preceding this Master Plan contained a working but batch-oriented implementation.

Baseline:

```text
repository: saralbanker/hermes
branch: overhaul-2026-09-23
baseline commit: f8a447e
historical audited DB rows: 8,688
```

Verified or historically proven components include:

```text
scheduled execution
Gmail IMAP watcher
local embeddings
local LLM scoring
local tailoring
Indeed application path
Greenhouse application path
OTP retrieval
response monitoring
```

Partially proven or restricted areas include:

```text
Direct Forms: implemented, not sufficiently production-proven
Lever: implemented, not production-proven
Ashby: blocked by observed anti-bot rejection
some Indeed flows: form/channel dependent
Gmail classification: requires stronger correlation/classification
```

The repository audit also exposed implementation defects that can waste attempts or destroy browser availability. The redesign must fix those defects without discarding proven production paths.

---

# 6. Evidence and Truth Model

Hermes must keep architecture, implementation state, and runtime truth separate.

## 6.1 Runtime evidence precedence

```text
runtime execution evidence
→ external application / employer evidence
→ database evidence
→ application history / email evidence where applicable
→ logs
→ source code
→ tests
→ documentation
→ historical agent reports
```

Where sources disagree, stronger evidence wins for current runtime truth.

## 6.2 State categories

Every major project statement should distinguish:

```text
DESIRED STATE
ARCHITECTURAL STATE
IMPLEMENTED STATE
RUNTIME STATE
VERIFIED STATE
```

Documentation defines intended design. It does not prove production behavior.

## 6.3 Core truth invariant

```text
No evidence → no confirmed submission.
```

For ambiguous outcomes:

```text
submission_unconfirmed
→ reconcile
→ only retry when evidence supports non-submission
```

---

# 7. Problem the Overhaul Must Solve

The old batch system fails to sustain the target because several losses are mixed together.

Primary failure classes:

```text
identity / deduplication loss
freshness / stale-inventory loss
eligibility loss
ranking loss
channel loss
browser execution loss
attempt-accounting loss
confirmation ambiguity
response-classification loss
resource exhaustion
```

The Master Plan therefore prioritizes system semantics and measurable funnel losses over cosmetic changes or speculative platform expansion.

---

# 8. Required System Shape

The final system is composed of the following logical planes:

```text
SOURCE FAN-IN
    ↓
OPPORTUNITY DOMAIN
    ↓
ELIGIBILITY + FIT
    ↓
STRICT AGE SCHEDULER
    ↓
CHANNEL ROUTER
    ↓
BROWSER GATEWAY
    ↓
APPLICATION EXECUTION
    ↓
VERIFICATION / EVIDENCE
    ↓
ATTEMPT + STATE LEDGER
    ↓
CONTINUOUS REFILL / FEEDBACK
```

Parallel supporting path:

```text
Gmail / response monitoring
    ↓
response classification
    ↓
opportunity/application correlation
    ↓
notification
```

The logical system is continuous even if individual source operations remain periodic because of legitimate source constraints.

---

# 9. Workstream Model

The overhaul is divided into seven implementation workstreams. These are engineering boundaries, not seven new products.

## Workstream 1 — Data and Opportunity Lifecycle

Owns:

```text
canonical identity
source observations
open-state refresh
age provenance
application_attempts
channel state separation
historical database migration
```

Success condition:

> Hermes can distinguish canonical job truth, observation history, application history, and channel state.

## Workstream 2 — Discovery and Reserve

Owns:

```text
source fan-in
legitimate HTTP/API-first discovery where available
continuous refresh
re-observation
freshness
ready-reserve calculation
300 ready-reserve planning target
historical reevaluation
21-day expiration
bounded refill backoff / source protection
```

Success condition:

> Hermes maintains actionable fresh supply without self-DOS loops or stale inventory inflation.

## Workstream 3 — Scheduler and Pipeline

Owns:

```text
strict age cascade
fresh preemption at next claim
retry overlays
just-in-time tailoring
70/30 core/stretch preference
atomic leases
continuous application consumption
```

Success condition:

> Hermes always selects from the correct age band and safely survives individual job failures.

## Workstream 4 — Browser Gateway

Owns:

```text
BrowserGateway
CDP adapter
Playwright adapter
structured page state
frames / supported shadow roots
SPA readiness
action validation
session handling
browser recovery
```

Success condition:

> Browser execution becomes state-aware without granting unrestricted control to a generative model.

## Workstream 5 — Local AI Runtime

Owns:

```text
four-model baseline
model routing
embeddings
reranking
scoring
cover-letter tailoring
screening answers
fact validation
memory-aware model residency
local benchmark harness
```

Success condition:

> The local AI path operates inside the laptop's practical resource envelope with measurable quality and latency.

## Workstream 6 — Application Reliability

Owns:

```text
attempt classification
submission evidence
submission-unconfirmed reconciliation
channel health
form-change recovery
rate-limit handling
security-block handling
submit-phase crash recovery
channel cooldown / circuit breaking
```

Success condition:

> A browser problem, channel problem, or ambiguous submission cannot corrupt canonical opportunity truth or create an unsafe duplicate.

## Workstream 7 — Continuous Operations and Validation

Owns:

```text
systemd service
cgroup/resource containment
startup recovery
shutdown behavior
health metrics
backup/restore drills
24/7 soak tests
throughput validation
```

Success condition:

> Hermes behaves as a durable local service rather than a batch script.

---

# 10. Discovery Strategy

Discovery is optimized for useful fresh supply rather than raw scrape volume.

## 10.1 Existing source scope

The current system includes:

```text
Indeed
Greenhouse
Lever
Ashby
We Work Remotely
Arbeitnow
Himalayas
Remotive
RemoteOK
supported direct / ATS routes
```

These remain the base source families.

## 10.2 Expansion rule

Additional candidate-facing platforms are optional and should be introduced only when measured supply/channel gaps justify them.

The project must not expand platform count merely to make architecture look larger.

Platform status is fixed: **Indeed** = supported primary channel; **We Work Remotely** = Future Phase 2; **Wellfound** = Future Phase 3; **Greenhouse**, **Lever**, and **Ashby** = Future Evaluation (already implemented at the discovery/routing level, not committed/actively-expanded production channels; Ashby submission is currently blocked by platform anti-bot); **LinkedIn** = permanently unsupported — Hermes must not automate LinkedIn and must not depend on LinkedIn. Rollout proceeds strictly in order: perfect Indeed, then add the single easiest platform, then add one medium-complexity platform, then stop and re-evaluate the hardest integrations before any further implementation.

## 10.3 Source handling

For each source:

```text
collect within legitimate limits
normalize
resolve canonical identity
store observation
refresh current state
apply policy
contribute to reserve when actionable
```

Where a source offers a legitimate public HTTP/API surface, that may be preferred over browser discovery.

No discovery technique is justified by a need to defeat a platform's security controls.

## 10.4 Refill protection

When reserve is low:

```text
increase legitimate refill effort
```

but never:

```text
busy-loop discovery every few seconds forever
```

Source and worker health must impose bounded backoff/cooldown behavior.

---

# 11. Eligibility and Fit Strategy

Hard eligibility is deterministic.

Typical hard gates:

```text
geography
published salary below policy floor
clearly excluded role
clearly impossible experience requirement
>21 days
confirmed duplicate / already applied
no supported legitimate application route
security block
```

Missing information becomes explicit uncertainty rather than silently fabricated values.

After hard eligibility:

```text
cheap deterministic fit
→ embedding similarity
→ BGE reranking
→ Phi-4-mini specialist judgment for survivors
```

Fit is a ranking signal, not a permanent dead-letter state.

A threshold change must be able to re-rank existing canonical opportunities without rediscovering them from scratch.

---

# 12. Reserve Strategy

The main reserve metric is:

```text
READY_RESERVE
```

It represents canonical opportunities that are currently actionable.

It excludes:

```text
already applied
live application attempt
expired opportunities
opportunities permanently blocked across all supported channels
historical low-score records that are not currently actionable
```

Planning target:

```text
READY_RESERVE_TARGET = 300
```

The number is a buffer target, not a guarantee that three days of successful submissions exist.

Secondary measurements should expose where supply is being lost:

```text
open reserve
eligible reserve
ranked reserve
channel-ready reserve
tailored reserve
```

---

# 13. Scheduler Strategy

The scheduler uses strict cascading age priority.

Claim order:

```text
0–3d
→ 4–7d
→ 8–14d
→ 15–21d
```

Within a selected age band, fit/rank may determine the candidate.

A newly discovered 1-day-old candidate may be selected at the next claim even if a previous loop had already evaluated older candidates.

Retry/recovery does not create a peer queue. A retry retains the opportunity's age semantics.

At `>21d`, automatic application ends permanently for that opportunity.

---

# 14. Application Strategy

## 14.1 Channel resolution

A canonical opportunity may have multiple legitimate routes:

```text
direct employer form
supported ATS
supported authenticated board flow
supported redirect
unsupported / account wall / blocked
```

The resolver chooses an available legitimate route without bypassing controls.

## 14.2 Channel health

Repeated operational failures belong to the channel-health model:

```text
AUTH_EXPIRED
RATE_LIMITED
FORM_SCHEMA_CHANGED
ACCOUNT_WALL
ANTIBOT_BLOCKED
NETWORK_UNAVAILABLE
HEALTHY
```

A channel may cool down while unrelated channels continue.

## 14.3 Provenance

Existing proven paths should be preserved during migration.

Current priorities are:

```text
keep Indeed usable
keep Greenhouse usable
prove/fix Direct Forms
prove/fix Lever where justified
keep Ashby safely blocked unless platform behavior changes
```

A channel is not considered production-capable merely because its code exists.

---

# 15. Browser Strategy

The browser is an execution subsystem behind a stable interface.

Required action loop:

```text
structured page state
→ candidate actions
→ deterministic validator
→ CDP / Playwright execution
→ new structured state
```

The decision layer must be bounded. No generative model receives unrestricted browser authority.

Browser readiness must consider:

```text
navigation
URL/frame stabilization
network quietness where meaningful
critical DOM/ARIA target availability
short state-stability window
```

Required session model:

```text
authenticated board → persistent supported session
public/direct → isolated context where useful
```

Resource policy must preserve page functionality. JS, required XHR/fetch, and form logic cannot be blocked blindly.

Browser restart policy is adaptive rather than a fixed universal page-count timer.

---

# 16. Local AI Strategy

The model architecture is specialized and sequential.

```text
Nomic
→ semantic retrieval / pre-ranking

BGE reranker
→ top-k semantic reranking

Phi-4-mini
→ fit scoring / bounded classification

Qwen3.5-4B
→ tailoring / difficult screening reasoning
```

Hard eligibility and final browser-action validation remain deterministic.

Tailoring must use verified candidate facts and may not invent:

```text
employment
education
salary
professional-experience years
clients
production claims
unsupported technologies
```

AI benchmark gates must measure:

```text
quality
latency
RSS / memory
model-switch behavior
CPU load
thermal stability
failure rate
```

Published model package size is not treated as a substitute for measured process RSS on Hermes' machine.

---

# 17. Application Truth and Crash Recovery

The application ledger must answer:

```text
What opportunity was claimed?
Which channel was used?
When did the attempt start?
What actually happened?
What evidence exists?
Was the result confirmed?
Can another attempt be made safely?
```

Every application execution receives an attempt record.

For submit-phase process death, the system must assume ambiguity until reconciled. It must not blindly requeue a job merely because its process disappeared.

Reconciliation may use:

```text
current page state
confirmation page/URL
legitimate account/application history
confirmation email
stored evidence
```

Only evidence supporting non-submission permits another attempt.

---

# 18. Response Monitoring Strategy

Response monitoring is independent of the application worker.

```text
Gmail IMAP
→ message normalization
→ evidence-aware classification
→ application/opportunity correlation
→ response state
→ notification
```

Notification follows the fixed communication path **Company → Platform → Gmail → Hermes → Telegram**. Each notification is assigned exactly one severity tier (defined in `SYSTEM_RULES.md` §31: Ignore / Log / Telegram Notification / High Priority Telegram Notification); only the latter two reach the user's Telegram client.

Classification must avoid broad false signals such as treating any `no-reply` message or generic footer phrase as an application acknowledgement.

A response-monitoring outage must not stop the application engine.

---

# 19. Operations Strategy

Production execution is:

```text
hermes-continuous.service
    ↓
state recovery
    ↓
discovery / refresh
    ↓
reserve maintenance
    ↓
continuous application worker
    ↓
verification
    ↓
maintenance / health
    ↺
```

The Gmail watcher remains a separate support path.

Legacy timers may remain for maintenance/diagnostics but must not be the primary application engine.

Startup:

```text
DB access / integrity
→ expired lease recovery
→ model availability
→ browser/session health
→ source refresh
→ reserve calculation
→ continuous loop
```

Shutdown:

```text
stop new claims
→ finish or safely close current action
→ commit state
→ close browser
→ close DB
```

Forced termination relies on durable state + lease recovery.

---

# 20. Resource Strategy

Base concurrency is deliberately conservative:

```text
1 active application browser worker
1 active application page by default
bounded supporting work
```

Parallel application workers are not part of the initial correctness baseline.

They may be added only as measured throughput optimizations after:

```text
queue correctness
browser stability
memory behavior
channel stability
confirmation safety
```

are already proven.

Arch Linux systemd/cgroup controls may bound service and child-process resource use.

Exact CPU/memory limits are tuning values derived from measured RSS and stability; no arbitrary universal browser limit is frozen by this document.

---

# 21. Observability Strategy

The system must expose enough telemetry to locate losses rather than guess at them.

Minimum operational measurements:

```text
open reserve
eligible reserve
ready reserve
age-band depth
core / stretch depth
applications attempted today
applications confirmed today
confirmation rate
submission-unconfirmed count
retryable failure count
channel health
form-change rate
anti-bot / CAPTCHA block count
browser restart / crash count
process RSS
model latency / failure rate
DB busy/retry count
source freshness
```

Funnel reporting must separate:

```text
SUPPLY FAILURE
DECISION FAILURE
BROWSER FAILURE
CHANNEL FAILURE
INFRASTRUCTURE FAILURE
CONFIRMATION FAILURE
```

The largest measured loss becomes the next optimization target.

---

# 22. Implementation Order

Implementation proceeds by dependency and risk.

```text
PHASE 0 — Planning lock
    architecture frozen
    master plan frozen
    lower-level contract documents created

PHASE 1 — Data foundation
    canonical identity
    observations
    attempts
    channel state
    migration

PHASE 2 — Discovery / reserve
    refresh
    freshness
    actionable reserve
    bounded refill

PHASE 3 — Scheduler / continuous pipeline
    age cascade
    leases
    just-in-time tailoring
    continuous worker

PHASE 4 — Browser gateway
    structured state
    CDP / Playwright adapters
    validator
    sessions
    recovery

PHASE 5 — Local AI
    four-model stack
    model router
    benchmarks
    fact validation

PHASE 6 — Application reliability
    evidence
    reconciliation
    channel health
    form-change recovery

PHASE 7 — Continuous operations
    systemd
    cgroups
    startup/shutdown
    soak testing

PHASE 8 — Throughput tuning
    identify largest loss
    tune
    measure
    repeat
```

A phase may overlap another only where its dependencies are already satisfied.

---

# 23. Validation Gates

## Gate A — Data truth

Must prove:

```text
canonical identity survives URL changes
multiple observations map correctly
historical filters do not poison current reserve
confirmed submission blocks duplicates
age provenance is explicit
>21d cannot auto-apply
```

## Gate B — Scheduler correctness

Must prove:

```text
freshest age band always wins
fresh arrival can preempt at next claim
retry does not become another age queue
claims are atomic
leases recover safely
```

## Gate C — Browser reliability

Must prove:

```text
structured page state is available
SPA readiness is reliable
supported frames/shadow roots are handled
actions are validated
proven channels survive migration
security challenges stop safely
browser crash does not rewind DB truth
```

## Gate D — AI reliability

Must prove:

```text
models run locally
resource budget is empirically acceptable
sequential residency is stable
fit scoring is useful
reranking is useful
tailoring is fact-grounded
screening answers remain truthful
```

## Gate E — Application truth

Must prove:

```text
confirmed submission requires evidence
every execution is logged as an attempt
ambiguous outcome is reconciled before retry
channel failure is isolated from opportunity truth
```

## Gate F — Continuous operation

Must prove:

```text
systemd service survives restart
startup recovery works
resource containment works
24/7 soak behavior is stable
throughput metrics are accurate
```

## Gate G — Target validation

Only after the preceding gates:

```text
measure sustained confirmed submissions/day
measure supply sufficiency
measure confirmation rate
measure browser/resource stability
```

The 100/day target is considered achieved only when real confirmed evidence supports it.

---

# 24. Non-Goals

The following are not required for the core overhaul:

```text
WFQ scheduler
>21-day application tier
generic HTTP replay of application POSTs
incognito for every job
new browser process per job
fixed browser restart after an arbitrary page count
blind CSS/JS blocking
unrestricted browser-agent LLM
security-evasion tooling
large distributed infrastructure
microservice decomposition
new candidate-facing platforms solely for architecture completeness
large dashboard before the engine is proven
```

A future control UI may expose selected business parameters, but the engine must not be blocked on building a large dashboard.

---

# 25. Documentation System

The overhaul uses eight core planning documents:

```text
FROZEN ARCHITECTURE
        ↓
01 MASTER_PLAN.md
        ↓
02 SYSTEM_RULES.md
03 DATA_MODEL.md
04 WORKFLOW_ENGINE.md
        ↓
05 BROWSER_SYSTEM.md
06 AI_SYSTEM.md
        ↓
07 EXECUTION_PROTOCOL.md
        ↓
08 IMPLEMENTATION_ROADMAP.md
```

The dependency meaning is:

```text
MASTER_PLAN
    defines project-level goals and boundaries

SYSTEM_RULES
    defines permanent rules under the Master Plan

DATA_MODEL
    defines persistence semantics

WORKFLOW_ENGINE
    defines lifecycle / scheduling semantics using Data Model + Rules

BROWSER_SYSTEM
    defines browser/channel execution under Architecture + Workflow

AI_SYSTEM
    defines local model behavior under Architecture + Workflow

EXECUTION_PROTOCOL
    defines how AI agents must inspect, change, test, and verify Hermes

IMPLEMENTATION_ROADMAP
    converts all preceding documents into build order and gates
```

No additional architecture document is required for the base overhaul.

A new planning document is justified only when an existing document would become ambiguous, internally contradictory, or unmanageably overloaded without it.

---

# 26. AI-Agent Working Contract

Every AI agent working on Hermes must follow this project sequence:

```text
READ authority documents
→ inspect relevant repository evidence
→ establish current truth
→ identify exact change boundary
→ execute only within the boundary
→ run targeted tests
→ run relevant integration/runtime verification
→ compare result to acceptance criteria
→ report evidence and remaining uncertainty
```

Agents must not:

```text
invent missing repository state
rewrite architecture because implementation is difficult
replace evidence with assumptions
change unrelated files for convenience
silently modify business policy
turn implementation failures into architecture changes
```

When a lower-level decision appears to conflict with the frozen architecture, the agent must stop at that boundary and surface the conflict rather than silently redesigning the system.

---

# 27. Change Control

## Ordinary implementation changes

Do not require architecture review when they only modify:

```text
selectors
prompt wording
timeouts
batch sizes
context sizes
memory thresholds
polling intervals
query tuning
logging
metrics presentation
internal code organization
```

provided frozen semantics remain unchanged.

## Architecture-change triggers

Explicit architecture review is required for changes involving:

```text
canonical identity semantics
21-day horizon
strict age cascade
submission confirmation semantics
browser security boundary
SQLite system-of-record decision
BrowserGateway boundary
continuous worker architecture
four-model baseline role structure
one-primary-generator residency rule
application attempt semantics
truthfulness constraints
```

A real architecture change must document:

```text
existing decision
new decision
reason
evidence
impact
migration requirement
rollback / recovery considerations
```

No implementation plan or AI prompt may smuggle an architectural change into ordinary coding work.

---

# 28. Definition of Done

Hermes is not considered overhaul-complete merely because code compiles or tests pass.

Completion requires alignment across:

```text
architecture
→ implementation
→ runtime behavior
→ verification evidence
```

At completion, Hermes must demonstrate:

```text
canonical opportunity lifecycle
continuous actionable supply
strict fresh-first scheduling
safe claims and recovery
structured browser execution
validated browser actions
four-model local AI operation
truthful application material
verified submission evidence
channel isolation
independent response monitoring
continuous systemd operation
resource containment
accurate throughput accounting
```

And, when sufficient legitimate supply and channel availability exist, measured operation must be capable of reaching the project's 100 confirmed, qualified applications/day target.

---

# 29. Final Project Directive

Hermes development now moves downward only:

```text
FROZEN ARCHITECTURE
        ↓
MASTER PLAN
        ↓
DOMAIN CONTRACTS
        ↓
EXECUTION PROTOCOL
        ↓
IMPLEMENTATION ROADMAP
        ↓
CODE + TESTS
        ↓
RUNTIME EVIDENCE
```

The project must avoid redesign churn.

The purpose of the remaining documents is to make the frozen architecture implementable, testable, and executable by AI coding agents without repeatedly reopening architectural questions.

The primary optimization loop is:

```text
MEASURE
→ FIND LARGEST REAL LOSS
→ FIX THAT LOSS
→ VERIFY
→ MEASURE AGAIN
```

Not:

```text
add complexity
→ add platforms
→ add agents
→ add concurrency
→ hope throughput improves
```

---

# 30. Master Plan Freeze

**Status:** `ACTIVE MASTER PLAN`  
**Date:** `2026-09-27`  
**Parent architecture:** `HERMES-ARCH-FINAL-2026-09-27`  
**Role:** project-level contract beneath the frozen architecture  
**Next document:** `SYSTEM_RULES.md`

> **Freeze rule:** The remaining seven documents are subordinate contracts. They may add precision and implementation detail, but they cannot silently replace this plan or the frozen architecture above it.
