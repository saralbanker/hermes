# Hermes — Implementation Roadmap

**Document ID:** HERMES-IMPLEMENTATION-ROADMAP-2026-09-28  
**Status:** FINAL IMPLEMENTATION ROADMAP  
**Document:** 8/8  
**Repository:** saralbanker/hermes  
**Baseline branch:** overhaul-2026-09-23  
**Baseline commit:** f8a447e  
**Purpose:** Turn the frozen Hermes architecture into a verified, continuously operable implementation without reopening design decisions.

> This is the execution roadmap for the frozen redesign. It sequences implementation, migration, verification, rollout, and retirement of legacy paths. It does not redefine the architecture.

---

# 1. Roadmap Objective

The objective is to transform the current legacy Hermes implementation into the frozen architecture while preserving every verified safety property.

The implementation target is:

~~~
continuous local worker
→ legitimate job discovery
→ canonical opportunity identity
→ deterministic hard eligibility
→ semantic fit ranking
→ strict fresh-first scheduling
→ safe application execution
→ submission evidence
→ durable reconciliation
→ response monitoring
→ recovery
→ repeat
~~~

The operational target remains:

~~~
100 qualified, confirmed applications/day target
24/7-capable continuous operation
zero recurring paid external/API cost
single-laptop local execution
truthful candidate data
no security-control bypass
~~~

100/day is a target, not a guarantee.

---

# 2. Roadmap Authority

Implementation authority is:

~~~
frozen architecture
→ Master Plan
→ System Rules
→ Data Model
→ Workflow Engine
→ Browser System
→ AI System
→ Execution Protocol
→ Implementation Roadmap
→ source code
~~~

This roadmap is subordinate to all earlier architecture/domain contracts.

Where the roadmap conflicts with a parent document, the parent document wins and the conflict must be recorded rather than silently resolved in code.

---

# 3. Runtime Truth Rule

The repository documents describe intended behavior.

They do not prove that the behavior works.

Runtime truth must be established through:

~~~
controlled execution
external-channel evidence
durable database state
application history / email evidence
logs
tests
source inspection
documentation
~~~

Every milestone in this roadmap ends with a verification gate.

---

# 4. Frozen Architecture Contract

The following decisions are implementation invariants.

~~~
canonical opportunity identity
source observations separated from opportunity truth
application attempts separated from observations
channel health separated from opportunity truth
derived work queue
strict age cascade
hard eligibility before scoring
~70% core / ~30% stretch preference
100/day qualified, confirmed-only target
BrowserGateway
Playwright + CDP adapters
structured DOM/ARIA control surface
deterministic action validator
screenshots as evidence/diagnostic fallback
legitimate HTTP/API-first public discovery when appropriate
no generic private replay
persistent authenticated sessions where required
adaptive browser reuse/restart
local AI role separation
one primary generative specialist normally resident
SQLite + WAL
BEGIN IMMEDIATE for atomic claim paths
durable leases
explicit ambiguous-submission state
continuous worker
systemd/cgroup/resource awareness
~~~

No implementation phase may redefine these.

---

# 5. Frozen Non-Goals

The implementation must not add or restore:

~~~
Laya as a required model or dependency
Camoufox as the main browser
browser stealth / fingerprint evasion
CAPTCHA or Turnstile bypass
Cloudflare challenge bypass
generic private HTTP replay
WFQ as the scheduler
fixed 800 MB browser cgroup assumptions
kill-Chromium-after-every-application behavior
incognito/new-context-per-job as a universal rule
blanket CSS blocking
1000/day as a system target
unrequested platform expansion
large UI/control-plane work before engine proof
~~~

A proposal that requires one of these is a change-control event, not an implementation detail.

---

# 6. Current Repository Truth

The current branch still contains legacy orchestration and channel-specific code.

Important legacy surfaces include:

~~~
src/pipeline.py
src/apply.py
src/states.py
src/db.py
src/discover.py
src/response_watcher.py
src/score.py
src/tailor.py
src/answers.py
src/llm.py
src/indeed_apply.py
src/ats_apply.py
src/direct_form.py
src/redirect_resolver.py
src/otp_resolver.py
src/cap_enforcer.py
src/filters.py
src/geo.py
~~~

The repository also contains existing tests for:

~~~
application routing
ATS behavior
direct forms
Indeed classification/session/stall behavior
OTP resolution
filters
geography
adversarial cases
application engine
~~~

These tests are regression assets during migration.

---

# 7. Current Legacy Shape

The legacy model combines several concepts that the redesign separates.

The old flow effectively mixes:

~~~
job identity
source observation
score
tailoring
application attempts
channel
response state
~~~

The redesign separates these concepts into durable contracts.

The migration must preserve historical evidence while changing ownership boundaries.

---

# 8. Existing Proven Behavior

Historically verified paths must be treated as protected regression surfaces.

Known proven or historically demonstrated behavior includes:

~~~
Indeed confirmed submissions
Greenhouse confirmed submission
Greenhouse Gmail OTP flow
Cloudflare-protected Greenhouse route completed without bypassing security
~~~

These paths are not assumed to remain healthy forever.

They must be revalidated during migration.

---

# 9. Historically Unproven or Restricted Paths

The migration must not treat code existence as proof for:

~~~
Lever
Ashby
generic direct forms
~~~

Ashby is particularly sensitive to anti-bot/security controls.

A channel remains unavailable or blocked when runtime evidence says it cannot be safely automated under the frozen security boundary.

---

# 10. Scoped Platforms

The target application/discovery scope is the source scope frozen in MASTER_PLAN.md §10.1 and ARCHITECTURE_REDESIGN_FINAL.md §6. This roadmap does not define a separate platform list:

~~~
Indeed
Greenhouse
Lever
Ashby
We Work Remotely
Arbeitnow
RemoteOK
Remotive
Himalayas
supported direct / ATS routes
~~~

This roadmap does not add new job platforms.

A platform may still produce no application route when its current path is unsupported, blocked, or otherwise outside the approved channel contract.

---

# 11. Candidate Policy Baseline

The implementation must preserve the current candidate policy:

~~~
about 4 years hands-on software development
about 1+ year paid client-facing freelance experience
Computer Engineering Diploma completed May 2026
CGPA 8.36
top 10%
no invented bachelor's degree
no inflated professional-experience claim
~~~

These facts are governed by profile/facts.md and must not be rewritten by the roadmap.

---

# 12. Geographic and Compensation Policy

Current policy values remain:

~~~
normal office/hybrid radius: under 20 km from Shahibaug, Ahmedabad
night-shift office/hybrid radius: under 10 km
remote India published salary floor: about ₹25,000/month
remote global published salary floor: about ₹30,000/month
~~~

Unknown salary remains unknown.

Missing location remains uncertain.

Neither may be silently converted into a pass or fail without the applicable deterministic rule.

---

# 13. Age Policy

Automatic application horizon:

~~~
0–3 days
4–7 days
8–14 days
15–21 days
>21 days = automatic application forbidden
~~~

Age bands are scheduler semantics, not discovery buckets.

Retries and recovery do not create alternative age queues.

---

# 14. Core / Stretch Policy

Target mix:

~~~
~70% core
~30% stretch
~~~

The mix is a preference within hard eligibility.

It must never:

~~~
override hard filters
invert fresh-first scheduling
require fabricated experience
~~~

---

# 15. Implementation Strategy

Migration is performed as a sequence of bounded replacement layers.

The preferred pattern is:

~~~
observe legacy
→ introduce new contract
→ migrate one ownership boundary
→ verify
→ route production traffic
→ retain legacy fallback where safe
→ verify again
→ retire legacy ownership
~~~

Do not perform a single all-at-once rewrite of the repository.

---

# 16. Milestone Map

The implementation milestones are:

~~~
M0  Baseline and safety freeze
M1  Data foundation
M2  Durable workflow core
M3  BrowserGateway foundation
M4  Indeed production path
M5  Evidence and reconciliation
M6  AI gateway and model-role migration
M7  We Work Remotely production path
M8  Wellfound production path
M9  Continuous worker integration
M10 Operations, deployment, and observability
M11 Controlled production rollout
M12 Capacity and stability validation
~~~

Each milestone has an explicit entry gate and exit gate.

---

# 17. Dependency Graph

The critical dependency chain is:

~~~
M0
 ↓
M1
 ↓
M2
 ↓
M3
 ↓
M4
 ↓
M5
 ↓
M6
 ↓
M7
 ↓
M8
 ↓
M9
 ↓
M10
 ↓
M11
 ↓
M12
~~~

Certain work may run in parallel only when it cannot mutate the same ownership boundary.

Examples:

~~~
fixture creation
documentation cleanup
deterministic helper tests
model benchmarking
resource measurement
~~~

Parallel work must not create conflicting source-of-truth implementations.

---

# 18. M0 — Baseline and Safety Freeze

### Goal

Create a reproducible starting point before migration.

### Required actions

~~~
confirm branch = overhaul-2026-09-23
record baseline commit = f8a447e
record current test baseline
record Python/runtime versions
record Ollama/model availability
record browser availability
record database location and backup status
record profile/facts.md version
record current known live channels
~~~

### Exit gate

The team can recreate the baseline environment and identify exactly what is being replaced.

---

# 19. M0 — Legacy Inventory

Produce a migration inventory:

~~~
legacy module
current owner
target subsystem
tests
runtime dependency
replacement status
retirement condition
rollback path
~~~

At minimum include:

~~~
pipeline
apply
states
db
discover
score
tailor
answers
llm
Indeed
ATS
direct form
redirect
OTP
response watcher
cap enforcement
filters
geo
~~~

The inventory becomes the implementation tracking map.

---

# 20. M0 — Baseline Test Snapshot

Run the existing deterministic test suite before source mutation.

Record:

~~~
pass count
fail count
skipped count
known environment-dependent failures
live-only checks not executed locally
~~~

No new migration commit should hide unrelated baseline regressions.

---

# 21. M0 — Database Backup

Before schema work:

~~~
close unsafe writers
checkpoint WAL where appropriate
create verified backup
record backup identifier
restore-test the backup
~~~

The backup is for recovery.

It is not a license to use snapshot rollback as normal workflow recovery.

---

# 22. M0 — Resource Baseline

Measure the real laptop:

~~~
CPU topology
RAM available
idle system memory
Python RSS
browser RSS
Ollama RSS
SQLite latency
browser startup latency
model warmup latency
~~~

The host envelope remains:

~~~
Ryzen 7 7730U
16 GB RAM
Vega 8 iGPU
CPU-oriented inference
7–10 GB practical AI RAM budget
~~~

All optimization decisions later use observed measurements.

---

# 23. M0 Exit Gate

M0 is complete only when:

~~~
baseline commit recorded
backup verified
test baseline recorded
resource baseline recorded
legacy inventory recorded
profile facts verified
frozen docs available to implementers
~~~

No production migration begins before this gate.

---

# 24. M1 — Data Foundation

### Goal

Introduce the redesigned durable data model without losing legacy history.

Target entities:

~~~
opportunities
source_observations
application_attempts
channel_health
work_queue
responses
daily_limits
evaluation_history
~~~

---

# 25. M1 — Legacy-to-Target Mapping

Build a deterministic mapping from legacy jobs/state into target entities.

Minimum mapping:

~~~
legacy job identity
→ opportunity candidate identity

legacy source URL/report
→ source observation

legacy application history
→ application attempt

legacy score/tailoring decisions
→ evaluation history

legacy response information
→ response

legacy channel state
→ channel health
~~~

No historical record should disappear merely because its previous owner is retired.

---

# 26. M1 — Canonical Identity Resolver

Implement canonical identity resolution before broad queue migration.

Resolution priority:

~~~
reliable source job ID
→ reliable ATS/company posting ID
→ normalized stable composite identity
~~~

The resolver must be deterministic for equal inputs.

The system must retain source locators separately.

---

# 27. M1 — Observation Layer

Persist source observations independently from canonical opportunities.

Each observation should preserve enough provenance to answer:

~~~
which source
which source identifier
which source URL
when observed
what source reported
when refreshed
whether the report is current
~~~

A source outage must not delete the canonical opportunity.

---

# 28. M1 — Application Attempt Ledger

Introduce durable attempts with:

~~~
attempt_id
opportunity_id
channel
started_at
finished_at
attempt_number
lease metadata
outcome
error class
evidence reference
~~~

The attempt becomes the only authoritative record of real application execution.

---

# 29. M1 — Evaluation History

Move scoring and fit decisions into historical evaluation records.

Store enough metadata to identify:

~~~
model role
model version
prompt/schema version where applicable
input version
score
confidence
reasons
risk flags
created_at
~~~

Historical evaluations remain useful for regression and re-evaluation.

---

# 30. M1 — Queue Projection

Implement work_queue as a derived projection.

Rebuild input:

~~~
current opportunity truth
latest observation
latest evaluation
application history
channel health
retry timing
age
~~~

The queue may be deleted and deterministically rebuilt.

No canonical fact may exist only in the queue.

---

# 31. M1 — Daily Limit State

Daily limits must be derived from confirmed submission truth.

Counts must not include:

~~~
unconfirmed submissions
failed attempts
already-applied records
blocked channels
~~~

The cap must survive restart.

---

# 32. M1 — Data Migration Verification

Validate:

~~~
row counts
foreign keys
unique constraints
canonical identity collision rate
orphan rate
attempt history preservation
daily-count preservation
queue rebuild equivalence
~~~

For every detected mismatch, stop and reconcile before enabling application traffic.

---

# 33. M1 Exit Gate

M1 is complete when:

~~~
target schema exists
legacy history mapped
canonical identity works
attempt ledger works
queue rebuild is deterministic
daily counting is confirmed-only
backup restore is proven
~~~

Production browser traffic remains under the legacy path until M2–M5 prove the replacement.

---

# 34. M2 — Durable Workflow Core

### Goal

Replace batch-first orchestration with durable state transitions.

Required states:

~~~
OBSERVED
EVALUATING
READY
APPLYING
AWAITING_RECONCILIATION
COMPLETED
EXPIRED
MANUAL_REVIEW
~~~

Application outcomes:

~~~
SUBMITTED
ALREADY_APPLIED
SUBMISSION_UNCONFIRMED
RETRYABLE_FAILURE
CHANNEL_BLOCKED
UNSUPPORTED_CHANNEL
TERMINAL_FAILURE
~~~

---

# 35. M2 — Repository Boundary

Create explicit repositories/services for:

~~~
opportunity access
observation access
evaluation access
attempt access
queue access
response access
channel health
daily limits
~~~

The purpose is ownership clarity.

The new workflow must not call legacy SQL helpers with hidden semantics.

---

# 36. M2 — Atomic Claim

Implement claim using short SQLite transactions.

Conceptually:

~~~
BEGIN IMMEDIATE
→ select highest-priority eligible work
→ verify no live attempt
→ verify daily cap
→ establish lease
→ commit
~~~

Never hold the transaction open while the browser or model operates.

---

# 37. M2 — Strict Scheduler

Claim ordering:

~~~
0–3d
→ 4–7d
→ 8–14d
→ 15–21d
~~~

Within the selected band:

~~~
current hard eligibility
→ core/stretch policy
→ semantic fit/ranking
→ tie-breakers
~~~

A newly discovered fresh opportunity can preempt older work at the next claim.

---

# 38. M2 — Freshness Revalidation

Every claim must revalidate:

~~~
current age
current open/plausibly-open state
hard eligibility
prior-application state
channel availability
retry timing
~~~

The queue is a hint.

Canonical truth wins.

---

# 39. M2 — Lease and Recovery

Every real attempt requires a durable lease.

Recovery must distinguish:

~~~
never-started browser work
browser started before external mutation
external submission may have begun
confirmed submission
~~~

An expired lease alone never proves safe retry.

---

# 40. M2 — Retry Policy

Retry only typed retryable failures.

Maximum attempt policy remains bounded.

Do not auto-replay:

~~~
SUBMISSION_UNCONFIRMED
~~~

until legitimate reconciliation demonstrates that another submission is safe.

---

# 41. M2 — Queue Rebuild Test

Delete and rebuild work_queue.

Expected result:

~~~
same canonical actionable set
same age band assignment
same claim ordering
same retry eligibility
~~~

Differences must be explained before proceeding.

---

# 42. M2 Exit Gate

M2 is complete when:

~~~
durable states work
claims are atomic
leases survive restart
scheduler is fresh-first
daily cap is enforced
queue rebuild is deterministic
ambiguous submission blocks replay
legacy batch semantics no longer own production ordering
~~~

---

# 43. M3 — BrowserGateway Foundation

### Goal

Replace direct browser-library ownership with the approved gateway.

Required abstractions:

~~~
BrowserGateway
BrowserSession
BrowserContext
BrowserPage
BrowserState
BrowserAction
BrowserEvidence
BrowserError
~~~

Adapters:

~~~
Playwright
CDP
~~~

---

# 44. M3 — Browser State Contract

Structured state should expose, when available:

~~~
URL
title
frames
dialogs
visible text
interactive elements
roles
accessible names
labels
types
values
required state
checked/selected state
disabled state
safe element references
~~~

This becomes the normal decision surface.

---

# 45. M3 — Action Validator

Browser actions must follow:

~~~
observe
→ propose
→ validate
→ execute
→ observe again
~~~

The action vocabulary remains bounded.

Examples:

~~~
CLICK
TYPE_TEXT
SELECT
CHECK
UNCHECK
SCROLL
WAIT
DONE
BLOCKED
~~~

Models may propose.

Deterministic validation decides.

---

# 46. M3 — Authentication and Session Handling

Authenticated channels use persistent supported sessions.

Public routes may use isolated contexts when useful.

Do not make these universal:

~~~
new browser process per job
new context per application
incognito-only execution
~~~

Session lifetime is adaptive.

---

# 47. M3 — Browser Resource Policy

Preserve required:

~~~
HTML
JavaScript
XHR/fetch/JSON
form logic
~~~

Reduce resources only when measured safe.

Candidate reductions may include:

~~~
large images
video
analytics/tracking
non-essential fonts
~~~

No blanket CSS or JavaScript blocking.

---

# 48. M3 — Browser Security Boundary

On:

~~~
CAPTCHA
Turnstile
Cloudflare challenge
strong anti-bot barrier
security-account wall
~~~

the route is stopped and typed as blocked.

The implementation must not add stealth or bypass logic.

---

# 49. M3 — Browser Crash Recovery

Browser crashes must trigger:

~~~
capture current evidence
classify attempt stage
restart/recover browser as appropriate
preserve durable attempt
reconcile if needed
continue unrelated work if safe
~~~

Do not restore an old database snapshot merely because Chromium crashed.

---

# 50. M3 Exit Gate

M3 is complete when:

~~~
gateway controls browser access
structured state is available
actions are validator-gated
persistent sessions work where required
browser restart is recoverable
security blocks are explicit
resource behavior is measurable
~~~

---

# 51. M4 — Indeed Migration

Indeed is the first application channel because it has the strongest existing runtime evidence.

Migration order:

~~~
legacy Indeed observation
→ BrowserGateway observation
→ BrowserGateway field mapping
→ BrowserGateway application
→ evidence capture
→ attempt ledger
→ reconciliation
~~~

---

# 52. M4 — Indeed Read Path

First migrate non-mutating behavior:

~~~
open route
classify page
identify application control
inspect fields
inspect validation
detect auth/session state
~~~

Do not enable auto-submit until read-path verification is stable.

---

# 53. M4 — Indeed Form Mapping

Every field mapping must be derived from current structured state.

Validate:

~~~
name
label
role
type
required
options
current value
validation message
~~~

Stale selectors must not be treated as durable truth.

---

# 54. M4 — Indeed Screening

Screening flow:

~~~
observe question
→ classify question
→ derive allowed answer candidates from candidate facts/policy
→ choose truthful answer
→ validate
→ enter
→ re-observe
~~~

Unknown questions remain UNKNOWN.

The system must never fabricate an answer merely to continue.

---

# 55. M4 — Indeed OTP

Where OTP is required:

~~~
detect OTP requirement
→ invoke approved OTP resolver
→ retrieve only necessary code
→ enter through validated field
→ confirm transition
→ record evidence without persisting OTP content
~~~

The mailbox remains a sensitive source.

---

# 56. M4 — Indeed Submit Gate

Before Submit:

~~~
daily cap check
canonical application check
active attempt check
age revalidation
hard eligibility revalidation
channel health check
route check
resume availability check
required screening validation
~~~

Only then can the deterministic action validator permit submission.

---

# 57. M4 — Indeed Evidence

Confirmation evidence may include:

~~~
explicit application confirmation
application history
confirmation page
confirmation URL
confirmation email
screenshot
~~~

A local function returning successfully is not proof.

---

# 58. M4 — Indeed Controlled Live Test

Run a controlled real flow.

Record:

~~~
opportunity
channel
timestamps
browser path
external result
evidence
database outcome
resource usage
~~~

The daily production target is not relevant during channel verification.

Safety and evidence come first.

---

# 59. M4 Exit Gate

Indeed is production-eligible only after:

~~~
read path verified
field mapping verified
screening validated
OTP flow verified where applicable
submit evidence verified
ambiguous submit reconciliation verified
duplicate protection verified
restart recovery verified
resource envelope measured
~~~

Until then, Indeed remains a controlled test path.

---

# 60. M5 — Evidence and Reconciliation

### Goal

Make submission truth durable and conservative.

Implement evidence capture independent of individual channel code.

---

# 61. M5 — Evidence Hierarchy

Prefer strongest signals first:

~~~
explicit employer/ATS confirmation
→ durable application-history evidence
→ employer confirmation email
→ confirmation page/URL
→ screenshot/page evidence
→ browser/network signals as supporting evidence
~~~

When signals conflict, preserve the conflict.

---

# 62. M5 — Ambiguous Submission State

When submit may have occurred but confirmation is missing:

~~~
SUBMISSION_UNCONFIRMED
~~~

Then:

~~~
stop replay
→ preserve evidence
→ reconcile
→ resolve as submitted or safely retryable
~~~

Do not guess.

---

# 63. M5 — Reconciliation Sources

Legitimate reconciliation sources include:

~~~
current browser state
application history
confirmation page
confirmation URL
confirmation email
stored attempt evidence
~~~

Do not invent a private backend endpoint merely because it would simplify reconciliation.

---

# 64. M5 — Response Integration

Responses are separate from submission truth.

A response watcher may classify:

~~~
application acknowledgement
recruiter contact
assessment
interview request
rejection
other relevant employer communication
~~~

Response presence never changes a historical submission count.

---

# 65. M5 Exit Gate

M5 is complete when:

~~~
submission evidence is persisted
ambiguous states are durable
reconciliation is idempotent
duplicate replay is prevented
daily counts derive from confirmed truth
response records remain separate
~~~

---

# 66. M6 — AI Gateway

### Goal

Replace scattered legacy LLM calls with role-based local AI services.

Frozen roles:

~~~
embedding
semantic reranking
scoring/classification
generation
~~~

Baseline model families:

~~~
Nomic embedding model
BGE-class reranker
Phi-4-mini scoring/classification specialist
Qwen3.5-4B generation specialist
~~~

Exact checkpoint variants are selected by benchmark inside these role contracts.

---

# 67. M6 — AI Gateway Contract

All AI calls should pass through a common gateway exposing:

~~~
role
model version
request schema
response schema
timeout
fallback policy
resource metadata
prompt/schema version where applicable
~~~

Business logic should not directly depend on Ollama request details.

---

# 68. M6 — Embedding Migration

Use embeddings for semantic representation and candidate/job retrieval support.

Persist:

~~~
input fingerprint
embedding model/version
vector metadata
created_at
~~~

Invalidate caches when relevant source text or model version changes.

---

# 69. M6 — Reranking Migration

Rerank a bounded top-K candidate set.

The reranker is not a hard eligibility gate.

Hard eligibility remains deterministic.

The reranker improves ordering inside already-eligible work.

---

# 70. M6 — Scoring Migration

Scoring/classification output should include:

~~~
score
confidence
reasons
risk flags
model version
input version
~~~

A low score is not a permanent dead-letter state.

Historical evaluations may be superseded by newer evidence.

---

# 71. M6 — Generation Migration

Generation is used for:

~~~
tailoring
cover letters
screening wording
other bounded application prose
~~~

Generation occurs as late as practical.

Every generated result passes factual validation before browser mutation.

---

# 72. M6 — Truth Validator

Candidate-facing generated content must be checked against profile/facts.md.

The validator must reject claims that invent or inflate:

~~~
experience
employment
education
clients
technologies
certifications
salary
production ownership
~~~

The model controls language.

Deterministic policy controls allowed facts.

---

# 73. M6 — Screening Decision Policy

Question handling order:

~~~
deterministic exact match
→ deterministic candidate-fact answer
→ constrained model classification/generation
→ validation
→ UNKNOWN / safe stop when not supportable
~~~

Do not use a model as a substitute for missing candidate evidence.

---

# 74. M6 — Browser Decision Support

AI may support browser interpretation within a bounded contract.

It may:

~~~
classify
suggest
rank
interpret
~~~

It may not:

~~~
execute arbitrary browser code
bypass validator
invent selectors without state
change security policy
override candidate truth
~~~

---

# 75. M6 — AI Resource Scheduling

On the 16 GB laptop:

~~~
active browser work takes priority
one primary generative specialist normally resident
speculative bulk inference is bounded
models may be unloaded between phases
RSS is measured
~~~

Do not keep a large multi-model fleet resident simply because storage allows it.

---

# 76. M6 — AI Benchmark Gate

Benchmark role candidates using representative Hermes tasks.

Measure:

~~~
quality
grounding
latency
CPU load
RSS
warmup time
failure rate
structured-output validity
~~~

The benchmark must run on the real laptop.

Download size alone is not a performance metric.

---

# 77. M6 Exit Gate

M6 is complete when:

~~~
all four roles route through AI Gateway
structured outputs validate
candidate truth validation is enforced
legacy duplicate LLM ownership is retired
resource behavior is measured
benchmark records exist
~~~

---

# 78. M7 — We Work Remotely Migration

We Work Remotely is the next priority because it is the single easiest remaining platform to bring to production after Indeed, per the approved rollout order.

Migration sequence:

~~~
route resolution
→ page classification
→ form inspection
→ field mapping
→ OTP where needed
→ submission
→ evidence
→ reconciliation
~~~

Reuse the BrowserGateway rather than rebuilding a second browser stack.

---

# 79. M7 — We Work Remotely Variability

Support only the browser states actually observed.

Variations may include:

~~~
embedded forms
frames
dynamic fields
select controls
checkboxes
file uploads
validation messages
OTP steps
confirmation transitions
~~~

Do not build speculative selectors for pages never observed.

---

# 80. M7 Exit Gate

We Work Remotely becomes production-eligible only after:

~~~
controlled live submission
confirmation evidence
OTP verification where applicable
duplicate safety
ambiguous submit handling
restart recovery
resource measurements
~~~

---

# 81. M8 — Remaining Approved Channels

After Indeed and We Work Remotely are stable, proceed in controlled order:

~~~
Wellfound
→ direct forms (supported utility capability, not platform-specific)
→ redirect-resolved supported ATS/routes (supported utility capability, not platform-specific)
~~~

Greenhouse, Lever, and Ashby are not part of this active sequence. They are already implemented at the discovery/routing level, remain usable/preserved as-is, and are re-evaluated only per § 85 — M8 — Future Evaluation: Deferred Channels.

The order may change only from current runtime evidence, not convenience.

---

# 82. M8 — Wellfound

Treat Wellfound as unproven until live evidence exists.

Implement:

~~~
route resolution
structured inspection
field mapping
screening
resume upload
submission
confirmation
failure classification
~~~

A passing unit suite is not channel proof.

---

# 83. M8 — Direct Forms

Direct forms must be treated as a bounded capability, not an unrestricted form bot.

Support only fields/actions represented by the BrowserGateway contract.

Unknown or high-risk form semantics produce:

~~~
MANUAL_REVIEW
UNSUPPORTED_CHANNEL
or other typed safe outcome
~~~

depending on the observed condition.

---

# 84. M8 — Redirect Resolver

Redirect resolution may use legitimate public route discovery.

Rules:

~~~
resolve
classify destination
verify domain/purpose
continue only to supported route
record final route
~~~

Do not turn redirect resolution into generic private HTTP replay.

---

# 85. M8 — Future Evaluation: Deferred Channels (Greenhouse, Lever, Ashby)

Greenhouse, Lever, and Ashby are already implemented at the discovery/routing level in the existing codebase and remain usable/preserved as-is. They are not committed, actively-expanded milestones within M7/M8. Per the approved rollout order, they are re-evaluated only after Indeed, We Work Remotely, and Wellfound are stable in production. Do not modify their existing working code or existing channel-health handling as part of this deferral.

Ashby is additionally blocked by current platform anti-bot controls. Ashby is not a bypass project.

If current execution hits a security barrier on any deferred channel:

~~~
stop
record evidence
set channel health
do not escalate into stealth
~~~

The channel may remain unsupported until legitimate conditions change and are verified, and until the rollout rule allows re-evaluation.

---

# 86. M8 — Channel Health Integration

Every channel adapter must emit typed operational states.

Examples:

~~~
HEALTHY
AUTH_EXPIRED
RATE_LIMITED
FORM_SCHEMA_CHANGED
ACCOUNT_WALL
ANTIBOT_BLOCKED
NETWORK_UNAVAILABLE
UNSUPPORTED
PAUSED
~~~

Channel health controls route availability.

It does not falsify opportunity truth.

---

# 87. M8 Exit Gate

M8 is complete only when each enabled channel has:

~~~
route contract
health model
safe failure class
evidence path
retry policy
live verification record
rollback/disable path
~~~

Unsupported channels remain explicitly unsupported.

---

# 88. M9 — Continuous Worker Integration

### Goal

Replace the legacy scheduled batch loop with the durable worker.

Normal loop:

~~~
startup
→ recovery
→ bounded source refresh
→ evaluation
→ queue maintenance
→ claim
→ tailor
→ apply
→ verify
→ record
→ response maintenance
→ health maintenance
→ repeat
~~~

Each cycle remains bounded.

---

# 89. M9 — Discovery Plane

Discovery sources refresh independently of application execution.

The discovery plane must:

~~~
respect source limits
avoid aggressive polling
preserve existing opportunities
update observations
signal source health
trigger bounded normalization
~~~

A source outage must not stop unrelated healthy channels.

---

# 90. M9 — Evaluation Plane

Evaluation occurs only as needed.

Pipeline:

~~~
hard deterministic filters
→ embeddings
→ bounded reranking
→ scoring/classification
→ evaluation persistence
~~~

Evaluation must not block urgent browser work with unnecessary bulk inference.

---

# 91. M9 — Just-in-Time Tailoring

Tailoring occurs near application time so that:

~~~
job text is current
candidate facts are current
model version is known
output is not generated for stale inventory
~~~

Generated material is validated immediately before browser use.

---

# 92. M9 — Application Plane

Application execution must be a bounded orchestration:

~~~
claim
→ browser route
→ inspect
→ fill
→ validate
→ submit
→ observe
→ evidence
→ outcome
~~~

No step may silently assume the previous step succeeded.

---

# 93. M9 — Maintenance Plane

Maintenance includes:

~~~
expired lease recovery
channel cooldown transitions
queue rebuild when needed
stale-observation refresh
model cache maintenance
browser health checks
response polling
log rotation/retention
~~~

Maintenance work must not starve live applications.

---

# 94. M9 — Idle Behavior

When no claimable work exists:

~~~
diagnose scarcity
→ bounded source refresh
→ reevaluate eligible inventory
→ wait/backoff
→ retry
~~~

Do not busy-loop.

---

# 95. M9 — Supply Diagnosis

When confirmed throughput drops, determine whether the cause is:

~~~
inventory shortage
eligibility shortage
age shortage
AI bottleneck
browser bottleneck
channel health
network
source outage
daily cap
~~~

The first response is diagnosis, not more concurrency.

---

# 96. M9 Exit Gate

M9 is complete when the worker can remain running across normal cycles without depending on a legacy batch scheduler for production application order.

The worker must survive:

~~~
empty queue
source outage
model outage
browser restart
channel cooldown
ambiguous submission
process restart
~~~

---

# 97. M10 — Observability

Operational logs and metrics must answer:

~~~
what happened
where
when
why
what happens next
~~~

Minimum metrics:

~~~
opportunities discovered
observations refreshed
eligible count
ready reserve
claims
applications started
confirmed submissions
already applied
unconfirmed submissions
retryable failures
terminal failures
channel blocks
model latency
browser latency
browser RSS
model RSS
worker uptime
~~~

---

# 98. M10 — Sensitive Logging Rules

Never log:

~~~
passwords
OTP values
cookies
authorization headers
session tokens
private mailbox contents
unnecessary personal data
~~~

Store references to evidence rather than raw secrets.

---

# 99. M10 — Systemd Deployment

Run the worker under systemd with:

~~~
automatic restart where safe
graceful stop handling
resource controls based on measurement
structured logs
health/restart visibility
~~~

Do not copy an arbitrary fixed cgroup memory number without measurement.

---

# 100. M10 — Graceful Shutdown

Shutdown sequence:

~~~
stop new claims
→ finish or safely stop bounded step
→ persist evidence/outcome
→ release browser/resources
→ exit
~~~

If interrupted, next startup runs durable recovery.

---

# 101. M10 Exit Gate

Operations are production-eligible when:

~~~
logs are actionable
metrics expose bottlenecks
systemd lifecycle works
graceful shutdown works
restart recovery works
resource envelope is documented
sensitive data is protected
~~~

---

# 102. M11 — Test Pyramid

Testing follows:

~~~
Level 0 — syntax/type/import
Level 1 — unit
Level 2 — subsystem integration
Level 3 — local dry run
Level 4 — controlled live verification
Level 5 — continuous production observation
~~~

The level required depends on change risk.

---

# 103. M11 — Deterministic Unit Tests

High-value unit tests include:

~~~
canonical identity normalization
age bands
hard eligibility
geography
salary policy
core/stretch routing
queue ordering
daily cap
claim leases
retry classification
page classification
field mapping
browser action validation
AI schema parsing
candidate-fact validation
~~~

---

# 104. M11 — Integration Tests

Required integration coverage includes:

~~~
SQLite WAL behavior
atomic claim
queue rebuild
AI Gateway
model fallback
BrowserGateway
session handling
OTP path
evidence persistence
response persistence
worker recovery
~~~

---

# 105. M11 — Adversarial Tests

Retain and extend adversarial coverage for:

~~~
duplicate opportunities
duplicate submissions
stale queue rows
expired leases
ambiguous submit
malformed AI output
prompt injection
unexpected browser fields
security challenges
source outages
model outages
SQLite busy conditions
browser crashes
~~~

---

# 106. M11 — Restart and Recovery Tests

Exercise:

~~~
worker restart
browser restart
model restart
machine reboot where practical
interrupted shutdown
expired lease
mid-flow browser disconnect
~~~

The expected invariant is durable recovery without duplicate submission.

---

# 107. M11 — Regression Rule

Every migration must verify:

~~~
new behavior works
previously verified behavior still works
~~~

A migration is not green because the new test passes.

The old safety property must remain intact.

---

# 108. M11 — Controlled Canary

Production rollout begins with a constrained canary.

Start with:

~~~
one worker
one active application at a time
small confirmed volume
observability enabled
manual review readily available
~~~

Increase only after external and durable evidence support the next step.

---

# 109. M11 — Canary Evidence

For each canary application record:

~~~
opportunity identity
channel
age band
eligibility result
evaluation version
attempt ID
browser evidence
submission evidence
durable outcome
resource usage
~~~

The canary should produce an auditable chain from discovery to outcome.

---

# 110. M11 — Rollout Expansion

Expansion sequence:

~~~
canary
→ limited production
→ broader production
→ normal production
~~~

Do not jump directly from local tests to 100/day operation.

---

# 111. M11 — Rollback

Rollback is permitted when a change violates a critical invariant or makes a verified production path demonstrably less safe.

Rollback must preserve:

~~~
opportunity history
attempt history
submission evidence
response history
channel health evidence
~~~

Never erase application history to make a rollback appear clean.

---

# 112. M11 — Browser Rollback

If a browser migration regresses:

~~~
stop new claims for affected route
→ preserve active-attempt evidence
→ disable changed adapter
→ restore previous verified route if safe
→ reconcile ambiguous attempts
~~~

Do not replay uncertain submissions during rollback.

---

# 113. M11 — AI Rollback

If a model/prompt/version causes unsafe or ungrounded output:

~~~
disable changed version
→ restore previous verified version
→ invalidate unsafe generated artifacts
→ preserve evaluation history
~~~

Changing model output quality does not justify weakening truth validation.

---

# 114. M12 — Capacity Validation

The host is resource-constrained.

Measure actual:

~~~
CPU saturation
RAM pressure
swap behavior
browser RSS
model RSS
SQLite contention
application latency
queue refill latency
restart recovery time
~~~

Tune one bottleneck at a time.

---

# 115. M12 — Throughput Model

Measure the pipeline as:

~~~
eligible supply
×
claimability
×
channel success rate
×
confirmation rate
~~~

Do not equate discovered jobs with completed applications.

Do not equate submit clicks with confirmed submissions.

---

# 116. M12 — 100/Day Validation

The 100/day target is validated from confirmed submissions to qualified opportunities — not from raw submission volume.

A valid count is:

~~~
confirmed external submission
+ durable confirmation evidence
+ one counted daily event
+ opportunity passed hard eligibility (DATA_MODEL.md §5.7: opportunities.hard_eligibility_state = ELIGIBLE)
~~~

Invalid count sources include:

~~~
submit clicks
successful function returns
unconfirmed attempts
duplicate submissions
manual-review items
blocked attempts
submissions to opportunities that were not hard-eligible
~~~

---

# 117. M12 — 24/7 Stability Test

Before declaring long-running readiness, exercise a continuous window long enough to reveal:

~~~
memory growth
browser degradation
queue drift
source failures
model warm/cold imbalance
SQLite contention
recovery issues
channel cooldown behavior
~~~

The exact duration is determined by observed risk and available test opportunity; it must be recorded rather than assumed.

---

# 118. M12 — Daily Cap Stress Test

Artificially approach the cap in a safe test environment.

Verify:

~~~
99 confirmed, qualified → next allowed
100 confirmed, qualified → further application claims blocked
unconfirmed does not increment
restart does not reset count
midnight/date boundary rolls correctly
~~~

Never use fabricated production submissions to test the counter.

---

# 119. M12 — Truthfulness Audit

Before broad production, audit a representative set of generated materials.

Check:

~~~
years of experience
employment claims
education
technology claims
client claims
salary claims
location claims
project claims
screening answers
~~~

Any unsupported claim blocks rollout of the affected generation path until corrected.

---

# 120. M12 — Security Audit

Verify there is no operational path for:

~~~
CAPTCHA bypass
Turnstile bypass
Cloudflare challenge bypass
stealth fingerprints
credential fabrication
private endpoint replay
secret leakage
unvalidated model-driven browser actions
~~~

Security failures are deployment blockers.

---

# 121. M12 — Data Integrity Audit

Verify:

~~~
one canonical opportunity per intended identity
observations linked correctly
attempts linked correctly
no orphan attempts
no duplicate counted submission
queue rebuild stable
foreign keys valid
history preserved
~~~

Any unexplained integrity violation blocks promotion.

---

# 122. Production Readiness Definition

Hermes is production-ready only when all are true:

~~~
data model migrated
workflow engine owns production ordering
BrowserGateway owns browser execution
Indeed verified
We Work Remotely verified
remaining enabled channels individually verified
AI Gateway owns AI calls
candidate truth validation active
evidence/reconciliation active
daily cap confirmed-only
recovery tested
systemd lifecycle verified
resource envelope measured
security boundary verified
observability active
~~~

---

# 123. Architecture Drift Gate

Before every release, compare implementation against frozen architecture.

Reject changes that introduce:

~~~
new scheduler semantics
new canonical identity semantics
new AI role
new mandatory model
new browser abstraction
new security bypass
new platform scope
new database ownership model
~~~

Unless the formal architecture-change trigger has been met.

---

# 124. Definition of Ready — Implementation Task

A task is ready only when it has:

~~~
target subsystem
known current behavior
relevant parent document
affected source files
tests to run
runtime evidence required
rollback plan
resource impact
~~~

Tasks without an evidence plan are not implementation-ready.

---

# 125. Definition of Verified

A change may be called verified only with the appropriate evidence level.

Use precise status:

~~~
syntax-validated
unit-tested
integration-tested
dry-run verified
controlled-live verified
continuously observed
~~~

Do not use “works” as a substitute for evidence.

---

# 126. Agent Execution Order

Implementation agents should follow:

~~~
read parent contract
→ inspect current source
→ inspect relevant tests
→ establish current truth
→ implement smallest safe slice
→ test
→ inspect diff
→ commit
→ record verification
→ hand off
~~~

A coding agent must not redesign the architecture because an alternate implementation appears cleaner.

---

# 127. Agent Handoff Format

Every handoff must include:

~~~
CURRENT TRUTH
CHANGED FILES
IMPLEMENTED
TESTS
RUNTIME EVIDENCE
KNOWN FAILURES
NEXT SAFE ACTION
~~~

Do not hand off with “mostly done”.

---

# 128. Commit Slicing

Preferred commit groups:

~~~
data schema
data migration
repository boundary
workflow claim
scheduler
BrowserGateway
Indeed adapter
evidence/reconciliation
AI Gateway
model role
We Work Remotely adapter
remaining channel
worker
observability
deployment
~~~

Keep commits bisectable.

---

# 129. Safe Parallel Work

Parallel work is acceptable for independent artifacts such as:

~~~
unit fixtures
model benchmarks
documentation
read-only analysis
resource measurements
test harnesses
~~~

Do not parallelize two agents that mutate the same ownership boundary or create competing implementations.

---

# 130. Forbidden Implementation Pattern

Never:

~~~
add a second scheduler “temporarily”
add a second application ledger
bypass BrowserGateway for one channel
add a direct model call for convenience
use an old URL as universal identity
count submit click as success
retry ambiguous submit automatically
disable candidate-fact validation
~~~

Temporary exceptions become permanent architecture drift.

---

# 131. Legacy Retirement Rule

A legacy component may be retired only when:

~~~
replacement behavior exists
replacement tests pass
controlled live path passes where applicable
recovery passes
rollback exists
production traffic has migrated
no remaining callers depend on legacy semantics
~~~

Delete last.

---

# 132. Migration Safety Pattern

For risky cross-cutting changes:

~~~
introduce
→ mirror
→ compare
→ route
→ observe
→ retire
~~~

Do not cut over solely because the new implementation returns the same output on one fixture.

---

# 133. Final Implementation Order

The concrete coding order is:

~~~
1. baseline/preflight
2. target schema + migration
3. repositories + durable state
4. queue + scheduler + claim
5. BrowserGateway
6. Indeed read path
7. Indeed submit + evidence
8. reconciliation + recovery
9. AI Gateway
10. role migration + validation
11. We Work Remotely
12. Wellfound
13. direct forms/redirect resolver (supported utilities)
14. continuous worker
15. response/maintenance integration
16. observability
17. systemd/resource controls
18. canary
19. rollout
20. capacity/stability validation
~~~

This is the default critical path. Greenhouse, Lever, and Ashby are deferred until the Future Evaluation gate (§ 85) and are not part of this critical path.

---

# 134. First Coding Action After Roadmap

The first implementation task is not “rewrite the pipeline”.

It is:

~~~
M0 baseline capture
→ deterministic migration inventory
→ test baseline
→ verified DB backup
→ resource baseline
→ exact implementation task breakdown
~~~

Only after this is complete should schema migration begin.

---

# 135. First Production-Critical Path

The first production path to prove is:

~~~
discovery
→ opportunity identity
→ observation
→ hard eligibility
→ queue
→ claim
→ BrowserGateway
→ Indeed
→ evidence
→ confirmed submission
→ daily count
→ response
~~~

This path becomes the vertical integration spine for the rest of Hermes.

---

# 136. What Must Not Be Optimized Early

Do not optimize first:

~~~
100/day throughput
maximum concurrency
large batch AI inference
aggressive discovery polling
browser process churn
large UI
speculative platform breadth
~~~

Optimize first:

~~~
truth
safety
confirmation
recovery
durability
resource stability
~~~

---

# 137. What Gets Measured Later

After the vertical path is stable, optimize:

~~~
queue refill rate
AI cache hit rate
model warmup
browser reuse
route resolution latency
form completion latency
source refresh efficiency
channel throughput
memory fragmentation
~~~

Every optimization must preserve the frozen contracts.

---

# 138. Operational Failure Priority

When performance and safety conflict:

~~~
duplicate prevention
→ submission truth
→ data integrity
→ recoverability
→ channel safety
→ system stability
→ latency
→ throughput
~~~

A slower confirmed application is preferable to a fast ambiguous one.

---

# 139. Expansion Rule

The system expands only when evidence supports it.

Expansion can mean:

~~~
more verified opportunities
more verified channels
more stable worker time
more efficient model execution
~~~

It does not mean silently increasing concurrency.

---

# 140. Final Roadmap Exit Gate

The redesign project is complete only when:

~~~
all required parent contracts are implemented
legacy orchestration no longer owns production truth
canonical identity is durable
queue is derived
scheduler is strict fresh-first
daily count is confirmed-only
BrowserGateway is authoritative
Indeed is verified
We Work Remotely is verified
other enabled channels have individual evidence
AI Gateway is authoritative
candidate truth validation is enforced
ambiguous submission is reconciled safely
worker is continuous
recovery is restart-safe
security controls are respected
systemd operation is verified
resource envelope is measured
100/day target has been evaluated from confirmed evidence
~~~

---

# 141. Final Definition of Done

Hermes is done when it can run continuously on the real laptop and maintain this invariant:

~~~
discover legitimately
→ identify correctly
→ filter deterministically
→ rank intelligently
→ claim atomically
→ apply truthfully
→ verify externally
→ count only confirmed success
→ recover conservatively
→ keep running
~~~

The system is not complete because the code compiles.

It is complete when the durable state, browser evidence, external outcomes, recovery behavior, and resource envelope all agree with the frozen architecture.

---

# 142. Final Implementer Directive

Every implementation agent should operate under this rule:

~~~
Do not redesign.
Do not assume.
Do not guess.
Do not count unverified success.
Do not replay ambiguous applications.
Do not bypass security.
Do not inflate candidate facts.
Do not add hidden architecture.
Do not optimize before measuring.

Read the contract.
Inspect the current truth.
Change the smallest safe surface.
Verify at the correct level.
Preserve evidence.
Commit cleanly.
Leave the next agent a truthful handoff.
~~~

---

# Appendix A — Milestone Acceptance Matrix

| Milestone | Primary proof | Release consequence |
|---|---|---|
| M0 | Reproducible baseline | Allows schema work |
| M1 | Data integrity + deterministic queue rebuild | Allows workflow cutover |
| M2 | Atomic claims + recovery | Allows gateway integration |
| M3 | Gateway + validated browser actions | Allows channel migration |
| M4 | Indeed confirmed live flow | Allows first production channel |
| M5 | Evidence + reconciliation | Allows confirmed-only counting |
| M6 | AI Gateway + grounding + resource benchmark | Allows local AI production use |
| M7 | We Work Remotely confirmed live flow | Adds second verified channel |
| M8 | Wellfound confirmed live flow | Adds third verified channel |
| M9 | Continuous worker recovery | Allows continuous operation |
| M10 | Observability + systemd + resource envelope | Allows controlled rollout |
| M11 | Canary evidence | Allows broader production |
| M12 | Stability + integrity + security audit | Allows normal production posture |

---

# Appendix B — Critical Invariants Checklist

Before each production promotion verify:

~~~
[ ] canonical identity is deterministic
[ ] source observations are preserved
[ ] application history is durable
[ ] queue is rebuildable
[ ] age cascade is strict
[ ] hard eligibility is deterministic
[ ] core/stretch remains subordinate to hard gates
[ ] daily limit counts confirmed submissions only
[ ] leases are durable
[ ] ambiguous submit cannot replay automatically
[ ] BrowserGateway is the browser boundary
[ ] actions are validator-gated
[ ] security challenges stop the route
[ ] AI outputs are schema-validated
[ ] candidate facts are enforced
[ ] one primary generative specialist is normally resident
[ ] active browser work outranks speculative AI
[ ] SQLite writes stay short
[ ] worker restart is recoverable
[ ] evidence is retained without leaking secrets
[ ] channel health is separate from opportunity truth
[ ] no legacy path silently bypasses the new architecture
~~~

---

# Appendix C — The One-Sentence Operating Contract

Hermes continuously turns fresh, eligible, truthfully representable opportunities into confirmed applications through durable local state, verified browser execution, conservative reconciliation, and measured resource use — without bypassing platform security or sacrificing correctness for throughput.

