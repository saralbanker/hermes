# Hermes — Workflow Engine

**Document ID:** `HERMES-WORKFLOW-ENGINE-2026-09-27`  
**Status:** ACTIVE IMPLEMENTATION SPECIFICATION  
**Document:** 4/8  
**Parent:** `ARCHITECTURE_REDESIGN_FINAL-2026-09-27-FROZEN.md` + `MASTER_PLAN.md` + `SYSTEM_RULES.md` + `DATA_MODEL.md`  
**Repository:** `saralbanker/hermes`  
**Baseline branch:** `overhaul-2026-09-23`

> **Purpose:** Define how Hermes moves durable work through discovery, evaluation, scheduling, application, verification, recovery, and maintenance.
>
> This document owns workflow behavior and transition rules. It does not redefine canonical identity, entity ownership, browser implementation, or model selection.

---

# 1. Workflow Objective

Hermes moves from the current batch-oriented funnel to a continuously running, state-driven worker.

```text
SOURCE REFRESH
    ↓
CANONICAL OPPORTUNITY
    ↓
CURRENT STATE
    ↓
HARD ELIGIBILITY
    ↓
FIT / RERANK
    ↓
READY WORK
    ↓
STRICT AGE CASCADE
    ↓
CHANNEL RESOLUTION
    ↓
TAILOR JUST-IN-TIME
    ↓
APPLICATION ATTEMPT
    ↓
EVIDENCE VERIFICATION
    ↓
OUTCOME
    ↓
RECONCILIATION / RETRY / TERMINAL
    ↓
QUEUE UPDATE
    ↓
NEXT CLAIM
```

Core invariant:

```text
Durable state determines what happens next.
Volatile process memory never becomes the source of truth.
```

---

# 2. Scope

This document defines:

```text
workflow states
state transitions
claiming
leases
scheduler behavior
retry behavior
continuous worker behavior
queue participation
application orchestration
submission verification
reconciliation
failure routing
recovery
backpressure
workflow-level metrics
```

It does not define:

```text
canonical identity schema
SQL table ownership
browser/CDP/Playwright internals
model checkpoint selection
candidate facts
source-specific scraping implementation
```

Those are governed by the parent documents and later domain documents.

---

# 3. Workflow Vocabulary

```text
OPPORTUNITY
    canonical underlying job role

OBSERVATION
    one source's report of that opportunity

EVALUATION
    a current or historical decision about the opportunity

ATTEMPT
    one real application execution

CHANNEL
    a legitimate route used to apply

QUEUE
    derived projection of currently actionable opportunities

LEASE
    durable ownership of one live application attempt
```

One opportunity is not one URL, one observation, one attempt, or one channel.

---

# 4. State Dimensions

Workflow state is intentionally split.

## Opportunity processing state

```text
OBSERVED
EVALUATING
READY
APPLYING
AWAITING_RECONCILIATION
COMPLETED
EXPIRED
MANUAL_REVIEW
```

## Application outcome

```text
SUBMITTED
ALREADY_APPLIED
SUBMISSION_UNCONFIRMED
RETRYABLE_FAILURE
CHANNEL_BLOCKED
UNSUPPORTED_CHANNEL
TERMINAL_FAILURE
```

## Channel health

```text
HEALTHY
DEGRADED
AUTH_EXPIRED
RATE_LIMITED
FORM_SCHEMA_CHANGED
ACCOUNT_WALL
ANTIBOT_BLOCKED
NETWORK_UNAVAILABLE
PAUSED
```

No single overloaded status field may become the sole representation of all three dimensions.

---

# 5. Happy Path

```text
OBSERVATION
→ IDENTITY RESOLUTION
→ CURRENT STATE REFRESH
→ HARD ELIGIBILITY
→ FIT / RERANK
→ READY
→ CLAIM
→ TAILOR
→ ROUTE
→ APPLY
→ VERIFY
→ SUBMITTED
```

Every exception exits this path through a typed transition.

---

# 6. Discovery Workflow

Source data enters through a source adapter.

Required order:

```text
collect
→ normalize
→ source-level dedupe
→ canonical identity resolution
→ observation persistence
→ opportunity refresh
→ open-state evaluation
→ age evaluation
→ hard eligibility
→ queue projection
```

Raw source records are never direct application work.

---

# 7. Source Failure Isolation

Each source is an independent unit.

When one fails:

```text
record source failure
→ update health
→ continue other sources
```

A discovery failure must not terminate application work already present in the ready queue.

Record:

```text
source
failure class
failure code
timestamp
failure streak
cooldown
```

---

# 8. Discovery Modes

## Normal refresh

Used to:

```text
find new jobs
refresh observations
detect changes
refresh open state
refresh age information
```

## Refill

Activated when actionable reserve is below target.

Used to:

```text
restore actionable inventory
```

Both obey source-specific rate limits.

---

# 9. Reserve Control

Target:

```text
READY_RESERVE_TARGET = 300
```

Important reserve signals:

```text
open_reserve
eligible_reserve
ready_reserve
age_band_depth
channel_ready_reserve
source_freshness
```

Healthy reserve:

```text
continue application
continue lightweight refresh
avoid unnecessary expensive preparation
```

Low reserve:

```text
continue safe application
trigger bounded refill
recompute reserve
```

Repeated refill failure:

```text
record supply degradation
respect backoff
continue safe existing work
retry later
```

Never use a tight reserve-low polling loop.

---

# 10. Hard Eligibility

Hard eligibility is deterministic.

Possible gates:

```text
geography
published salary floor
role policy
experience policy
age
duplicate/application history
supported route
security block
```

Output must be explicit:

```text
ELIGIBLE
INELIGIBLE
UNCERTAIN / DEFERRED
```

Every rejection/defer reason must be explainable.

---

# 11. Uncertainty

Unknown data is not automatically false.

Examples:

```text
salary unknown
location ambiguous
experience unclear
posting time unreliable
remote eligibility unclear
```

Use explicit policy:

```text
accept with uncertainty
defer/enrich
reject when certainty is mandatory
```

Never invent missing values.

---

# 12. Age

Age basis:

```text
verified posted_at
→ reliable source timestamp
→ first_seen_at fallback
```

Bands (literal values as stored in `opportunities.age_band`, per DATA_MODEL.md §5.6/§27):

```text
0_3D  = 0–3 days
4_7D  = 4–7 days
8_14D = 8–14 days
15_21D = 15–21 days
```

At >21 days:

```text
EXPIRED
```

No automatic claim may begin after the boundary.

A live attempt that began before the boundary is governed by its attempt lifecycle and actual external result.

---

# 13. Fit Evaluation

Fit is a ranking signal.

Target:

```text
hard eligibility
→ deterministic prerank
→ Nomic embeddings
→ BGE top-k rerank
→ Phi-4-mini judgment
→ fit score / reasons / confidence
```

A low fit score is not an eternal dead-letter state.

A model failure preserves the opportunity and defers evaluation.

---

# 14. Core / Stretch

Current selection preference:

```text
~70% core
~30% stretch
```

This remains subordinate to:

```text
hard eligibility
age priority
application safety
```

No workflow transition may fabricate candidate experience.

---

# 15. Ready State

An opportunity is READY only when current data supports automatic action:

```text
open/plausibly open
AND within 21 days
AND hard eligible
AND not submitted
AND not already applied
AND not actively applying
AND has legitimate supported route
AND no permanent all-route block
AND retry due when applicable
```

`retry due when applicable` is: no attempt has yet failed for this opportunity, or its backoff has elapsed — exactly `work_queue.next_attempt_at IS NULL OR work_queue.next_attempt_at <= now()` (DATA_MODEL.md §26). This is the timing clause of the full retry-eligibility predicate; see Section 22 for the complete condition (attempt count, route availability) governing whether automatic retry is permitted at all.

READY is derived operational state.

---

# 16. Work Queue

The queue is a projection:

```text
work_queue
```

It is not canonical truth.

Queue rows may be removed and recreated.

Removing a queue row does not delete the opportunity.

---

# 17. Queue Rebuild

The implementation must be able to rebuild the queue from:

```text
opportunities
source_observations
evaluation_history
application_attempts
channel_health
current time
policy
```

Queue rebuild must not invent application history.

---

# 18. Scheduler

The scheduler is strict age cascade.

```text
0–3d
→ 4–7d
→ 8–14d
→ 15–21d
```

Within the selected band, use fit/rank and current route readiness.

WFQ is not the base scheduler.

---

# 19. Fresh Preemption

A new 0_3D opportunity can preempt older work at the next claim.

Example:

```text
current application = 5-day opportunity
new eligible job = 1-day opportunity
current attempt finishes
next claim can select the 1-day job
```

The worker must not blindly consume a large stale in-memory queue.

---

# 20. Scheduler Query Contract

Conceptually:

```text
for band in [0_3D, 4_7D, 8_14D, 15_21D]:
    candidate = best claimable candidate in band
    if candidate exists:
        claim atomically
        return candidate
return none
```

Observable ordering is mandatory even if the SQL implementation differs.

---

# 21. Retry Overlay

Retry is not a peer queue.

A retry retains the opportunity age band.

Example:

```text
Day 2
→ NETWORK_ERROR
→ retry later
→ remains 0_3D
```

The same opportunity changes age band naturally as time passes.

---

# 22. Retry Eligibility

This is the authoritative, opportunity-level retry-eligibility predicate. Automatic retry requires:

```text
opportunity.application_state = READY
AND most recent attempt's retry_eligible = 1 (DATA_MODEL.md §7.4 — the outcome/error_class
    fell in a bounded-retry row of Section 114's Retry Matrix)
AND attempts < 3
AND no confirmed submission
AND route is not permanently blocked
AND retry time is due (work_queue.next_attempt_at IS NULL OR next_attempt_at <= now — Section 15/DATA_MODEL.md §26)
AND opportunity remains within horizon
```

An attempt counts against `attempts < 3` above only if its `execution_phase` (DATA_MODEL.md §7.5) advanced past `NOT_STARTED` before finishing — i.e., some external browser/network action toward the target site began. A tailoring failure that never leaves `NOT_STARTED` does not consume a slot in this count, consistent with §30.

Current cap:

```text
MAX_ATTEMPTS = 3
```

Reaching `MAX_ATTEMPTS` with no confirmed submission is not silence: the opportunity is moved to `MANUAL_REVIEW` (Section 66), which removes it from `READY` and therefore from `READY_RESERVE` (DATA_MODEL.md §26) — it does not linger in `READY` as unclaimable dead inventory.

`application_state = READY` is listed explicitly above because this predicate is also evaluated at claim-time revalidation (Section 72, Candidate Revalidation), where an opportunity already in `APPLYING`, `AWAITING_RECONCILIATION`, or `MANUAL_REVIEW` must never be treated as retry-eligible regardless of its attempt history.

---

# 23. Retry Backoff

Conceptually:

```text
attempt 1
→ short delay

attempt 2
→ longer delay

attempt 3
→ no further automatic retry
```

Exact timing is configurable.

---

# 24. Claim Transaction

Claiming is the durable boundary before external application work.

Required:

```text
BEGIN IMMEDIATE
→ select claimable candidate
→ revalidate critical conditions
→ create attempt (new attempt_id)
→ create lease
→ mark opportunity APPLYING
→ set opportunities.current_attempt_id = new attempt_id
→ COMMIT
```

`current_attempt_id` is the fencing token consumed by Section 105.

No browser operation occurs in this transaction.

---

# 25. Lease

Minimum durable lease data:

```text
attempt_id
opportunity_id
worker_id
claimed_at
lease_until
```

A lease establishes ownership.

A lease does not prove non-submission after a crash.

---

# 26. Claim Race

If two workers compete:

```text
worker A = claim success
worker B = claim conflict
```

Worker B must request another candidate.

It must not perform browser work on an unowned candidate.

---

# 27. Daily Capacity Gate

Before every new claim:

```text
read current confirmed count
verify remaining capacity
claim only if capacity remains
```

Target:

```text
100 confirmed new qualified applications/day
```

The cap is not based on click count.

---

# 28. Daily Counting

```text
SUBMITTED with valid evidence = +1
ALREADY_APPLIED              = +0
SUBMISSION_UNCONFIRMED       = +0
FAILED                       = +0
BLOCKED                      = +0
```

Attempt counts and confirmed counts remain separate.

---

# 29. Tailoring

Tailoring occurs after an opportunity is selected.

Preferred:

```text
claim
→ latest context
→ resume selection
→ Qwen3.5-4B generation
→ fact validation
→ application
```

Avoid maintaining thousands of unused letters.

---

# 30. Tailoring Failure

Failure before external action:

```text
record model/tailoring failure
→ release/defer safely
→ preserve opportunity
```

Do not mark submitted.

Do not consume an application attempt unless actual external application work began.

Concretely, its `execution_phase` remains `NOT_STARTED`, which is what §22's retry-eligibility count excludes.

---

# 31. Resume Selection

Use approved resume variants.

Record the selected variant with the application context.

Selection must remain truthful.

---

# 32. Channel Resolution

A canonical opportunity can have:

```text
authenticated board route
ATS route
direct employer route
external redirect route
```

Resolve the route near application time.

The actual route used belongs in the attempt record.

LinkedIn is permanently unsupported: no route resolution, discovery source, or channel driver may target LinkedIn, and no workflow step may depend on LinkedIn being reachable or healthy.

---

# 33. Channel Health Gate

Before browser execution:

```text
HEALTHY → proceed
RATE_LIMITED → cooldown
AUTH_EXPIRED → pause
ANTIBOT_BLOCKED → stop route
ACCOUNT_WALL → alternate legitimate route or unsupported
UNSUPPORTED → alternate route or terminal route outcome
```

Channel health never becomes a substitute for opportunity truth.

---

# 34. Browser Start

At browser execution:

```text
attempt = STARTED
started_at = now
```

Browser operations go through BrowserGateway.

Workflow owns:

```text
attempt
lease
outcome
persistence
recovery
```

Browser owns:

```text
navigation
page state
actions
browser lifecycle
evidence capture
```

---

# 35. Browser Result Contract

Browser/application layer returns:

```text
outcome
detail
evidence
screenshot reference
meta
```

Workflow maps this result to persistent state.

Browser modules do not invent global workflow semantics.

---

# 36. Submission Verification

A submit click is not success.

Evidence preference:

```text
1. explicit ATS/application confirmation
2. durable confirmation page / URL / message
3. application-history evidence
4. employer confirmation email
5. screenshot/page evidence
6. browser/network supporting evidence
```

---

# 37. Submitted

Condition:

```text
sufficient confirmation evidence
```

Then:

```text
attempt = SUBMITTED
opportunity = COMPLETED
confirmed count += 1
queue row removed
lease cleared
```

---

# 38. Already Applied

Condition:

```text
credible prior application evidence
```

Then:

```text
attempt = ALREADY_APPLIED
opportunity protected from new submission
confirmed count += 0
queue row removed
```

---

# 39. Submission Unconfirmed

Condition:

```text
submit may have executed
confirmation insufficient
```

Then:

```text
attempt = SUBMISSION_UNCONFIRMED
opportunity = AWAITING_RECONCILIATION
confirmed count += 0
queue removed
```

Never immediately replay.

---

# 40. Reconciliation

Sequence:

```text
current page
→ application history
→ confirmation URL/page
→ email evidence
→ stored attempt evidence
→ definitive classification
```

Possible result:

```text
SUBMITTED
ALREADY_APPLIED
NOT_SUBMITTED / SAFE_RETRY
MANUAL_REVIEW
```

---

# 41. Crash During Submit

Danger:

```text
submit executes
→ process dies
→ final DB result not committed
```

Correct state:

```text
outcome unknown
→ preserve attempt
→ reconcile
→ no blind retry
```

Never treat a missing submitted row as proof that no submission occurred. Concretely: the attempt's persisted `execution_phase` (DATA_MODEL.md §7.5) is `SUBMIT_INTENT` — the crash happened at or after the irreversible boundary — regardless of whether `outcome` was ever written.

---

# 42. Browser Crash Before Submit

"Evidence proves the submit phase was not reached" means, concretely: the attempt's persisted `execution_phase` (DATA_MODEL.md §7.5) is `NOT_STARTED` or `EXTERNAL_WORK_STARTED`, never `SUBMIT_INTENT`.

```text
browser crash
→ classify failure
→ retry when safe
```

Respect attempt cap and age horizon.

---

# 43. Browser Crash After Possible Submit

"Submission may have occurred" means, concretely: the attempt's persisted `execution_phase` (DATA_MODEL.md §7.5) is `SUBMIT_INTENT` with no `outcome` yet recorded.

```text
browser crash
→ preserve attempt
→ SUBMISSION_UNCONFIRMED
→ reconcile
```

Never perform a database rewind merely because Chrome crashed.

---

# 44. Process Crash Recovery

Startup:

```text
DB health
→ active/expired lease inspection
→ attempt reconciliation
→ expiration sweep
→ queue rebuild
→ channel health
→ model health
→ browser health
→ source refresh
→ normal claims
```

Recovery is repeatable and idempotent.

---

# 45. Lease Recovery

This is a direct read of the expired lease's attempt: `execution_phase` (DATA_MODEL.md §7.5) selects the branch; `outcome`, if already written, overrides phase-based inference.

### No external action started (`execution_phase = NOT_STARTED`)

Release/requeue when durable state proves it.

### Browser started, submit not reached (`execution_phase = EXTERNAL_WORK_STARTED`)

Retry only when safe.

### Submit may have occurred (`execution_phase = SUBMIT_INTENT`, no `outcome` recorded)

Mark unconfirmed and reconcile.

### Confirmed submission (`outcome = SUBMITTED` already recorded)

Finalize submitted and never retry.

---

# 46. Worker Restart

Restart resumes from SQLite durable state.

It must not:

```text
reset attempts
reset daily count
forget ambiguous submissions
replay today's queue
```

The durable DB is the resume point.

---

# 47. Continuous Worker Loop

Production behavior:

```text
START
→ RECOVER
→ HEALTH CHECK
→ DISCOVER / REFRESH
→ UPDATE PROJECTIONS
→ CALCULATE RESERVE
→ EVALUATE AS NEEDED
→ CLAIM NEXT
→ TAILOR
→ RESOLVE CHANNEL
→ APPLY
→ VERIFY
→ PERSIST OUTCOME
→ UPDATE HEALTH
→ METRICS
→ MAINTENANCE
→ NEXT CLAIM
```

Expensive stages do not run unnecessarily when no work requires them.

---

# 48. Idle Worker

When no claimable opportunity exists:

```text
refresh due sources
→ diagnose reserve
→ bounded refill
→ maintenance
→ sleep
→ retry
```

No busy spin.

---

# 49. Supply-Empty Diagnosis

When ready reserve is zero, inspect:

```text
fresh source supply
canonical dedupe
hard eligibility
age expiration
model availability
route availability
channel health
queue projection
```

Classify the problem rather than weakening filters automatically.

---

# 50. Channel-Unavailable Opportunity

If all legitimate routes are unavailable:

```text
record channel-blocked/unsupported outcome
→ preserve opportunity
→ reevaluate later only if route returns and age permits
```

---

# 51. Channel Cooldown

Cooldown lives in channel health.

Triggers may include:

```text
rate limit
repeated network failure
auth failure
schema change
anti-bot block
```

Cooldown is not a scheduler age tier.

---

# 52. Security Challenge

CAPTCHA, Turnstile, Cloudflare challenge, or similar control:

```text
stop route
→ capture evidence
→ update channel health
→ continue other legitimate routes
```

No bypass.

---

# 53. Anti-Bot Rejection

Server-side anti-bot rejection:

```text
record attempt
→ record attempt outcome = CHANNEL_BLOCKED; set channel_health.status = ANTIBOT_BLOCKED
→ channel health update
→ no evasion
→ alternate supported route if one exists
```

---

# 54. Form Change

Unexpected form structure:

```text
FORM_SCHEMA_CHANGED
→ capture evidence
→ bounded reinspection when safe
→ channel metric
→ retry/defer according to policy
```

Never blindly reuse stale selectors.

---

# 55. Authentication Failure

Expired session:

```text
AUTH_EXPIRED
→ pause route
→ preserve opportunity
→ resume after valid session recovery
```

Other channels continue.

---

# 56. Model Failure

Ollama or model failure:

```text
runtime unavailable / timeout
→ preserve opportunity
→ defer model-dependent work
→ bounded retry
```

Do not corrupt application history.

---

# 57. Database Failure

SQLite busy:

```text
bounded retry
→ backoff
→ retry transaction
```

Database corruption:

```text
stop new claims
→ preserve incident evidence
→ recover from verified backup
```

---

# 58. Source Failure

Source outage:

```text
record
→ cooldown
→ continue other sources
→ continue existing ready applications
```

Do not create source-wide single point of failure.

---

# 59. Completion

Automatic application completion:

```text
SUBMITTED
ALREADY_APPLIED
EXPIRED
```

History remains durable.

---

# 60. Manual Review

Use for:

```text
ambiguous submission
conflicting identity
unsafe unknown form
uncertain candidate answer
security-sensitive edge case
interview request received (human decision required — AI_SYSTEM.md §28)
salary/offer discussion or offer received (human decision required — AI_SYSTEM.md §28)
contract or legal/identity document request (human decision required — AI_SYSTEM.md §28)
```

Manual review is an exception state, not an age queue.

---

# 61. Response Monitoring

Response monitoring is a supporting workflow and can operate independently.

```text
Gmail ingestion
→ message dedupe
→ classify
→ correlate
→ persist
→ update metadata
→ notify when required
```

The operator-facing communication path for every email-derived signal is fixed: Company → Platform → Gmail → Hermes → Telegram. Every "notify when required" step above travels this path; Hermes never contacts the operator through any other channel.

"Notify when required" means classifying the event against one of four notification levels. This is the one definition of the model; every other reference in this document and in EXECUTION_PROTOCOL.md names a level rather than restating it:

```text
Ignore                                — no durable record, no operator signal (routine/expected internal state, e.g. a healthy claim or an age-band roll-forward)
Log                                   — persisted for audit/debugging, no operator interruption
Telegram Notification                 — sent to the operator via the path above, routine attention, not time-critical
High Priority Telegram Notification   — sent via the same path, flagged for immediate operator attention
```

Section 62 maps response classification to a level; Section 68's Transition Table lists the level for each application-attempt event; EXECUTION_PROTOCOL.md §§41-45 and §74 tag the level for each operational/recovery event.

Failure of the watcher must not stop application processing.

---

# 62. Response Correlation

Prefer strong signals:

```text
employer identity
role title
application identifier
ATS/provider marker
known sender
timestamp relationship
```

Generic phrases are not proof of application or interview status.

Classification routes the message to the correct next state and notification level (Section 61), bounded by the automation boundary (AI_SYSTEM.md §28, Generation Role):

```text
screening-adjacent follow-up (resume/portfolio/GitHub request, project info)
    → automatable; Notification: Log
interview / salary / offer / contract / legal-identity-document signal
    → human-required; MANUAL_REVIEW (Section 60); Notification: High Priority Telegram Notification
rejection
    → terminal, no action; Notification: Log
ambiguous/unclassifiable
    → human-required; MANUAL_REVIEW (Section 60); Notification: Telegram Notification
acknowledgement (automated "application received" / no-action receipt)
    → terminal, no action; Notification: Ignore
```

A forbidden-category message is a workflow signal, not merely an AI constraint: the workflow must route it to MANUAL_REVIEW rather than silently falling through to automated handling.

---

# 63. Idempotency

Safe-to-repeat:

```text
source observation update
open-state refresh
eligibility evaluation
fit evaluation
queue rebuild
response ingestion by message_id
startup recovery
health refresh
```

Application submission is not treated as idempotent.

---

# 64. Duplicate Prevention

Before claim:

```text
check canonical application history
```

Submitted:

```text
do not claim
```

Already applied:

```text
do not claim
```

Unconfirmed:

```text
reconcile first
```

Never use URL-only duplicate protection.

---

# 65. One Attempt Per Claim

One claim creates one attempt context.

Multiple browser pages or form steps remain part of that attempt.

Do not create a new attempt per form field or page step.

---

# 66. Attempt Number

```text
1 = first execution
2 = second safe retry
3 = final allowed automatic execution
```

After 3 unsuccessful automatic attempts:

```text
no automatic retry
```

"No automatic retry" is a state transition, not a stall: the opportunity moves from `READY` to `MANUAL_REVIEW` (Section 68) in the same transaction that records the third attempt's outcome. It does not remain `READY` — a `READY` opportunity with no further eligible attempt would be unclaimable dead inventory that still passed the `READY_RESERVE` derivation (DATA_MODEL.md §26). An operator may resolve a `MANUAL_REVIEW` item and, if warranted, trigger a further attempt manually (EXECUTION_PROTOCOL.md §74.2); this is a human decision outside the automatic scheduler, not a fourth automatic attempt.

---

# 67. Attempt Terminality

An attempt terminates with one of the outcome values defined in Section 4 ("Application outcome"):

```text
SUBMITTED
ALREADY_APPLIED
SUBMISSION_UNCONFIRMED
RETRYABLE_FAILURE
CHANNEL_BLOCKED
UNSUPPORTED_CHANNEL
TERMINAL_FAILURE
```

`CHANNEL_BLOCKED` is the attempt-outcome value for this dimension; it is distinct from `channel_health.status = ANTIBOT_BLOCKED` (Section 4, "Channel health"), which describes the route's operational condition independently of any single attempt. The two are never the same field.

A terminal attempt does not automatically make every other legitimate route terminal.

---

# 68. Transition Table

| Event | Opportunity | Attempt | Queue | Notification (Section 61) |
|---|---|---|---|---|
| observation created | OBSERVED/EVALUATING | — | no | Ignore |
| eligible | READY | — | add | Ignore |
| claim success | APPLYING | CLAIMED | remove | Ignore |
| browser starts | APPLYING | STARTED | absent | Ignore |
| confirmed | COMPLETED | SUBMITTED | remove | Log |
| duplicate | COMPLETED | ALREADY_APPLIED | remove | Log |
| ambiguous submit | AWAITING_RECONCILIATION | SUBMISSION_UNCONFIRMED | remove | Telegram Notification |
| retryable failure (attempts < MAX_ATTEMPTS) | READY | RETRYABLE_FAILURE | delayed | Log |
| retryable failure (attempts = MAX_ATTEMPTS) | MANUAL_REVIEW | RETRYABLE_FAILURE | remove | High Priority Telegram Notification |
| channel blocked | route-dependent | CHANNEL_BLOCKED | route-dependent | Log (escalates per §51/EXECUTION_PROTOCOL.md §74.6 if persistent) |
| unsupported | history/route-dependent | UNSUPPORTED_CHANNEL | no same-route retry | Log |
| >21d | EXPIRED | — | remove | Ignore |
| manual review | MANUAL_REVIEW | appropriate | remove | High Priority Telegram Notification |

The Opportunity column uses only the canonical `opportunities.application_state` values defined in DATA_MODEL.md §5.9. Retry timing is tracked by `work_queue.next_attempt_at` (DATA_MODEL.md §9.2), not by a separate opportunity-level literal. "Confirmed" and "duplicate" are Log rather than Telegram Notification because, at a 100/day target, a per-submission push would be noise; operator-facing progress is read from the funnel metrics (Section 81), not a message per event.

---

# 69. Forbidden Transitions

Never:

```text
SUBMITTED → READY
SUBMISSION_UNCONFIRMED → SUBMITTED without evidence
SUBMISSION_UNCONFIRMED → retry without reconciliation
EXPIRED → READY through ordinary rediscovery
CHANNEL_BLOCKED → bypass execution
APPLYING → disappear without attempt outcome
```

---

# 70. Smallest Safe Unit

Preferred execution unit:

```text
one durable claim
→ one application attempt
→ one verified outcome
→ next claim
```

This maximizes recoverability and keeps priority fresh.

---

# 71. Batching

Batching is allowed for:

```text
source collection
normalization
embeddings
reranking
non-browser metadata
```

Application selection remains per opportunity.

Batching cannot change age-cascade semantics.

---

# 72. Candidate Revalidation

Immediately before external application, revalidate:

```text
not submitted
not already applied
within 21 days (age_band recomputed live from age_reference_at, not read from the cached column — DATA_MODEL.md §27.1)
still eligible
claim still owned
daily capacity remains
route still usable
```

If any fails, do not apply.

---

# 73. Browser Worker Ownership

Base architecture:

```text
1 application worker
1 active application page
bounded supporting work
```

That worker owns the current attempt.

---

# 74. Failure Isolation

Normal job failure:

```text
classify
→ persist
→ cleanup
→ continue
```

Critical failures may stop claims:

```text
DB corruption
irrecoverable critical configuration
unrecoverable process environment
```

---

# 75. Browser Cleanup

After attempt:

```text
close page/context where appropriate
release temporary resources
preserve evidence
persist outcome
```

Cleanup errors must not erase captured outcome.

---

# 76. Maintenance

Periodic maintenance:

```text
lease sweep
age-band recomputation sweep
queue consistency
expiration
channel cooldown
source health
DB health
temporary artifacts
metrics
response watcher
```

The age-band recomputation sweep refreshes the cached `opportunities.age_band` column (DATA_MODEL.md §27.1) for all non-expired opportunities so it does not drift across a band boundary between claims. This is distinct from per-claim revalidation, which recomputes the live value at claim time regardless of sweep cadence.

`DB health` includes WAL checkpoint maintenance: the same maintenance pass issues a passive checkpoint attempt (SQLite's `PRAGMA wal_checkpoint`) and records the resulting WAL file size as one of the metrics in SYSTEM_RULES.md §32. If a checkpoint cannot complete — SQLite's own semantics are that a long-lived open reader blocks a checkpoint from reclaiming WAL pages behind it — maintenance does not force-close the blocking reader and does not fall back to a different concurrency model; it logs the condition and lets the next scheduled pass retry. Unbounded WAL growth across repeated passes is a `DECISION FAILURE`-adjacent observability signal (SYSTEM_RULES.md §32), not a new failure class, and is surfaced through existing metrics rather than a new worker or watchdog.

Maintenance must not starve application claims.

---

# 77. Expiration Sweep

Find:

```text
age >21 days
```

Then:

```text
EXPIRED
→ remove from automatic work
```

---

# 78. Lease Sweep

Find:

```text
unfinished attempt
AND lease_until < now
```

Route through safe recovery.

Do not blindly requeue every expired lease.

---

# 79. Channel Health Sweep

Refresh:

```text
cooldown
failure streak
success streak
recent error
auth state where observable
```

---

# 80. Source Health Sweep

Distinguish:

```text
source unavailable
zero jobs
only known jobs
fresh jobs
fresh eligible jobs
```

These are different operational outcomes.

---

# 81. Funnel Metrics

Measure:

```text
fresh observations
canonical opportunities
hard eligible
fit evaluated
ready
claimed
attempted
submitted
already applied
unconfirmed
retryable failures
blocked
unsupported
expired
```

Provide source/channel attribution.

---

# 82. Timing Metrics

Measure:

```text
discovery → ready
ready → claim
tailoring latency
browser duration
verification latency
confirmed applications/hour
```

Use measurements to locate the actual throughput bottleneck.

---

# 83. Throughput Target

Target:

```text
100 confirmed qualified applications/day
```

Equivalent average:

```text
4.17 confirmed/hour
1 every 14.4 minutes
```

This is a validation target, not an assumption about available supply.

---

# 84. Backpressure

When reserve is high:

```text
reduce unnecessary expensive preparation
```

When reserve is low:

```text
increase bounded discovery/refill
```

When a channel degrades:

```text
reduce/pause affected route
```

No new queue class is introduced.

---

# 85. Model Backpressure

Do not pre-generate unlimited application material.

Prefer:

```text
select
→ tailor
→ apply
```

---

# 86. Queue Starvation Diagnosis

Use this order:

```text
1. fresh source supply
2. canonical dedupe collapse
3. hard eligibility loss
4. age expiration
5. model availability
6. route availability
7. channel health
8. queue projection
```

---

# 87. Source Expansion Gate

New sources are justified only when evidence shows:

```text
fresh actionable supply is insufficient for the operating buffer
```

New source work must remain:

```text
cheap/free
legitimate
measurably useful
```

---

# 88. HTTP/API-First

When a legitimate public structured endpoint exists:

```text
HTTP/API
→ normalize
→ persist observation
```

This is an efficiency decision, not permission to evade access controls.

---

# 89. Browser Boundary

Workflow requests:

```text
prepare
apply
verify
```

The workflow does not implement:

```text
CDP internals
Playwright internals
selectors
frame traversal
shadow-root mechanics
Chrome process management
```

---

# 90. AI Boundary

Workflow requests:

```text
embedding
reranking
fit judgment
tailoring
screening answer
```

AI returns structured results.

Workflow decides whether those results can affect state.

---

# 91. Candidate Fact Boundary

Workflow never mutates candidate facts.

Unknown candidate information becomes explicit safe handling.

Generated letters/answers are derived artifacts.

---

# 92. Policy Boundary

Policy/configuration includes:

```text
salary floor
office radius
night radius
daily target
core/stretch share
role exclusions
polling values
retry timing
```

Workflow semantics include:

```text
claim
lease
age cascade
reconciliation
submission truth
```

Changing workflow semantics requires review; tuning values do not automatically constitute architecture changes.

---

# 93. Configuration Snapshot

Attempts may store:

```text
policy_version
config_hash
```

This preserves historical reproducibility.

---

# 94. Determinism

Same durable state + same policy should yield the same allowed transition class.

Randomness may affect:

```text
pacing
model wording
explicitly permitted tie-breaking
```

Never allow randomness to weaken hard invariants.

---

# 95. Tie-Breaking

Within one age band, equal-ranked candidates should use stable ordering such as:

```text
updated_at
opportunity_id
```

Avoid unnecessary random tie-breaking.

---

# 96. Source Distribution

No equal source quotas are required.

Contribution is driven by:

```text
freshness
eligibility
fit
age
route readiness
```

---

# 97. No Hidden Queue

Do not introduce durable shadow queues:

```text
retry queue
browser queue
model queue
shadow scheduler
```

Temporary batches are allowed only when reconstructible.

---

# 98. Crash During Discovery

Already committed observations remain.

Unprocessed work continues next cycle.

Application state does not depend on finishing the complete discovery batch.

---

# 99. Crash During Scoring

Committed evaluations remain.

Unprocessed opportunities remain available.

No need to rerun all scores after a restart.

---

# 100. Crash During Tailoring

If no external action started:

```text
discard/regenerate material
```

If an application attempt started:

```text
attempt history governs
```

---

# 101. Crash During Verification

If confirmation committed:

```text
SUBMITTED
```

If submit may have occurred but confirmation did not commit:

```text
SUBMISSION_UNCONFIRMED
```

---

# 102. Crash During Notification

Notification failure does not alter application truth.

---

# 103. Late Browser Result

If a browser result arrives after lease expiry:

```text
verify attempt_id
verify worker identity
verify lease state
verify current opportunity state
```

Do not allow a stale worker to overwrite a newer decision.

---

# 104. Late Success vs Retry

Danger sequence:

```text
attempt 1 expires
→ attempt 2 starts
→ attempt 1 later reports success
```

The workflow must reconcile attempt 1 when possible and fence late writes.

No duplicate success state may be created.

---

# 105. Worker Fencing

`opportunities.current_attempt_id` is the durable fencing token (DATA_MODEL.md §5.2, §19.1). It is set only inside the atomic claim transaction and never reused across a retry, since every retry mints a new `attempt_id` (Section 24; DATA_MODEL.md §7.3).

Result writes are **required** — not optional — to be conditioned on still owning the lease:

```text
UPDATE opportunities
SET application_state = ...
WHERE opportunity_id = :opportunity_id
  AND current_attempt_id = :attempt_id
```

Zero rows affected means a newer attempt already owns the opportunity; the write must be discarded and routed to reconciliation (Section 40) rather than applied. No separate token table or generation counter is introduced; `attempt_id` itself is the fencing value because it is already guaranteed unique per attempt.

---

# 106. Channel-Scoped Retry

A failure on channel A is not evidence that channel B failed.

Healthy legitimate alternatives may be preferred.

---

# 107. Route Fallback

Allowed:

```text
aggregator
→ employer direct
→ supported ATS
```

Forbidden:

```text
security block
→ bypass route
```

---

# 108. Daily Target vs Channel Health

Never perform unhealthy route attempts solely to hit a daily distribution target.

Use healthy supported routes.

---

# 109. Route Change During Attempt

If a route redirects to another legitimate supported destination:

```text
resolve
→ record route change
→ continue when safe
```

If it becomes an account wall, security challenge, or unsupported form:

```text
stop
→ classify
```

---

# 110. Claim-to-Apply Timeout

A claimed opportunity must not remain indefinitely in preparation.

Use bounded preparation timeout.

Recovery depends on whether external application action began.

---

# 111. Tailoring Timeout

Bounded generation timeout.

On timeout:

```text
MODEL_TIMEOUT
→ no external application
→ defer/retry
```

---

# 112. Browser Action Timeout

On browser timeout:

```text
capture evidence
→ classify outcome
→ recover
```

A submit timeout is not automatically a failed submission.

---

# 113. Verification Timeout

When confirmation cannot be established:

```text
SUBMISSION_UNCONFIRMED
```

rather than false success.

---

# 114. Retry Matrix

| Condition | Automatic action |
|---|---|
| network timeout before external action | bounded retry |
| model unavailable before external action | defer/retry |
| form changed | bounded reinspection |
| authentication expired | wait for channel recovery |
| rate limit | channel cooldown |
| CAPTCHA | stop route; no bypass |
| anti-bot block | stop same-route retry |
| ambiguous submit | reconcile first |
| confirmed submit | no retry |
| already applied | no retry |
| >21 days | no claim |

---

# 115. Startup Recovery Priority

```text
1. DB health
2. lease/attempt reconciliation
3. expiration
4. queue rebuild
5. channel health
6. model health
7. browser health
8. source refresh
9. normal claims
```

---

# 116. Application Priority

```text
1. duplicate safety
2. daily cap
3. channel readiness
4. age cascade
5. fit/rank
6. throughput
```

---

# 117. Graceful Daily Cap

At 100 confirmed submissions:

```text
stop new application claims
```

The service may continue:

```text
response monitoring
source refresh
maintenance
expiration
metrics
```

---

# 118. Systemd Integration

Production application execution belongs to:

```text
hermes-continuous.service
```

Legacy timers may remain for maintenance/diagnostics but are not the application engine.

Systemd restart triggers durable recovery.

---

# 119. Resource Containment

Arch Linux is the deployment baseline.

Systemd/cgroup containment may bound:

```text
CPU
memory
child-process resources
```

Exact numeric limits are tuning parameters derived from measurement.

---

# 120. Single-Worker Baseline

```text
1 application worker
1 active application page
bounded supporting work
```

Additional concurrency requires measured evidence.

---

# 121. Multi-Worker Compatibility

If future workers are added:

```text
atomic claims
leases
canonical duplicate protection
daily-cap safety
```

remain authoritative.

---

# 122. Legacy Pipeline Migration

Current pipeline exposes:

```text
pipeline.py
discover
score
tailor
apply
```

and a legacy continuous mode using batch stages and old reserve counts.

This is migration input, not target semantics.

Target:

```text
canonical state
→ actionable reserve
→ one durable claim
→ one attempt
→ one verified outcome
→ next claim
```

---

# 123. Legacy apply.py Migration

Current apply logic combines:

```text
queue construction
tier allocation
duplicate checking
claiming
routing
ApplyResult handling
daily increment
```

Target decomposition:

```text
workflow
→ scheduler
→ claim
→ route
→ browser
→ verification
→ persistence
```

Reuse proven appliers during migration.

---

# 124. Legacy states.py Migration

Current central result contract should remain the shared boundary:

```text
ApplyResult
retryable states
MAX_ATTEMPTS
channel identifiers
tier identifiers
```

Do not let individual appliers invent persistent workflow strings.

---

# 125. Legacy db.py Migration

Existing persistence contains:

```text
WAL
foreign keys
URL-based mutation
dedupe_key
claim_job
daily limits
```

Target persistence increasingly uses:

```text
opportunity_id
observation_id
attempt_id
```

rather than URL-centric updates.

---

# 126. Persistence Boundary

Workflow coordinator owns coordinated cross-entity transitions.

```text
source collector → observation
AI module → evaluation/generation result
browser module → application result
workflow → durable transition
```

No subsystem silently becomes a second workflow authority.

---

# 127. Recommended Workflow Functions

Prefer narrow operations:

```text
evaluate_opportunity()
derive_ready()
claim_next()
start_attempt()
finish_attempt()
schedule_retry()
reconcile_submission()
expire_opportunities()
rebuild_queue()
recover_expired_attempt()
update_channel_health()
```

Avoid one monolithic pipeline function containing every domain rule.

---

# 128. Persistence Helpers

Recommended:

```text
claim_opportunity()
create_attempt()
record_attempt_started()
record_attempt_result()
record_submission_confirmed()
record_submission_unconfirmed()
schedule_retry()
release_claim()
recover_expired_attempt()
```

Exact names may differ.

---

# 129. Workflow Errors

Useful classes:

```text
SupplyError
EligibilityError
ClaimConflict
ModelError
TailoringError
RouteError
BrowserError
SubmissionAmbiguous
ChannelBlocked
PersistenceError
```

Convert these into controlled workflow transitions.

---

# 130. No Silent Failure

Every failure must be:

```text
thrown
logged
persisted
or explicitly absorbed
```

No attempt may remain in unknowable state.

---

# 131. Transition Logging

Log important events:

```text
claim created
attempt started
route selected
browser started
submit reached
confirmation detected
attempt finished
retry scheduled
lease recovered
channel cooldown changed
```

Never log credentials or secrets.

---

# 132. Evidence Traceability

Every external action traces through:

```text
opportunity_id
attempt_id
channel
timestamp
```

Durable chain:

```text
opportunity
→ attempt
→ action
→ evidence
→ outcome
```

---

# 133. Production Verification Levels

Operational confidence can distinguish:

```text
IMPLEMENTED
INTEGRATION_TESTED
RUNTIME_TESTED
PRODUCTION_VERIFIED
BLOCKED
UNSUPPORTED
```

Do not call something production-verified from source code or unit tests alone.

---

# 134. Proven Channel Preservation

During migration, preserve proven paths:

```text
Indeed
Greenhouse
```

Do not remove them merely because a new abstraction is being introduced.

---

# 135. Greenhouse Workflow

Known proven pattern:

```text
claim
→ tailor
→ open application
→ retrieve OTP when required
→ submit
→ verify evidence
→ persist
```

OTP failure never authorizes blind duplicate retry.

---

# 136. Indeed Workflow

Known historically proven pattern:

```text
authenticated session
→ application form
→ submit
→ evidence
```

External company-site routes may resolve to ATS/direct flows.

Browser lifecycle defects are handled by the Browser System document.

---

# 137. Lever Workflow

Current status:

```text
implemented
unproven
```

Support the route but do not label it production-verified without actual evidence.

---

# 138. Direct Form Workflow

Common controls:

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

Unknown control:

```text
stop safely
→ FORM_CHANGED / MANUAL_REVIEW
```

---

# 139. Ashby Workflow

Current status:

```text
anti-bot blocked
```

Route behavior:

```text
record attempt outcome = CHANNEL_BLOCKED; set channel_health.status = ANTIBOT_BLOCKED
→ channel health
→ no bypass
```

---

# 140. Aggregator Workflow

```text
listing
→ canonical opportunity
→ legitimate redirect resolution
→ destination classification
→ supported route
```

Account wall:

```text
unsupported
```

Direct employer form:

```text
DIRECT
```

---

# 141. Browser Crash vs DB Crash

Browser crash:

```text
recover browser
preserve DB
```

DB corruption:

```text
stop worker
recover DB
```

They are different failure domains.

---

# 142. Queue Projection Recovery

If attempt outcome commits but queue update fails:

```text
startup/maintenance rebuilds queue
```

Do not replay the external application.

---

# 143. Partial External Action

If browser action occurred but outcome did not commit:

```text
attempt lease
+
evidence
+
reconciliation
```

No inference of non-submission from missing DB outcome.

---

# 144. Daily Quota Recovery

Quota state must correspond to durable confirmed submission outcomes.

Startup may reconcile projection/count inconsistencies.

Never count an attempt merely because it started.

---

# 145. Liveness vs Readiness

Liveness:

```text
worker process is alive
```

Readiness:

```text
worker can safely perform application work
```

The worker may be alive while browser, model, channel, or reserve is degraded.

---

# 146. Notification Failure

Notification failure cannot change application truth.

Example:

```text
SUBMITTED
+ notification failure
= SUBMITTED
```

---

# 147. Scheduler Correctness Test

Given eligible candidates in all bands:

```text
0_3D before 4_7D
4_7D before 8_14D
8_14D before 15_21D
```

New 0_3D arrival must be selectable at the next claim.

---

# 148. Retry Correctness Test

Prove:

```text
retryable 0_3D
→ remains 0_3D
```

No separate retry age queue exists.

---

# 149. Duplicate Safety Test

Prove:

```text
same canonical opportunity
different URL
→ no second application

same canonical opportunity
different source
→ no second application
```

---

# 150. Ambiguous Submit Test

Prove:

```text
submit may have executed
DB final outcome missing
→ unconfirmed state retained
→ no immediate duplicate submission
```

---

# 151. Browser Crash Test

Prove:

```text
browser crash
→ worker recovers
→ DB intact
→ ambiguous state reconcilable
→ unrelated opportunities intact
```

---

# 152. Queue Rebuild Test

Prove:

```text
clear queue projection
→ rebuild
→ actionable work restored
→ submitted/expired/ineligible work excluded
```

---

# 153. Source Failure Test

Prove:

```text
source A fails
→ source B continues
→ ready applications continue
```

---

# 154. Model Failure Test

Prove:

```text
Ollama unavailable
→ worker stays alive
→ model-dependent work defers
→ application history remains intact
```

---

# 155. Daily Cap Test

Prove:

```text
99 confirmed
→ claim may proceed

100 confirmed
→ no new application claim

unconfirmed attempt
→ count unchanged
```

---

# 156. Expiration Test

Prove:

```text
within 21 days
→ may remain eligible

>21 days
→ claim forbidden
```

---

# 157. Channel Cooldown Test

Prove:

```text
rate-limited channel
→ not selected during cooldown
→ eligible after cooldown
```

---

# 158. Recovery Idempotency Test

Run startup recovery twice.

No:

```text
duplicate attempt
duplicate submission
duplicate response
```

---

# 159. Definition of Workflow Done

The workflow layer is complete when Hermes demonstrates:

```text
continuous discovery/refresh
canonical current-state evaluation
strict fresh-first scheduling
durable claim and lease
just-in-time preparation
legitimate route selection
browser execution
evidence verification
safe retry/reconciliation
queue reconstruction
accurate confirmed accounting
```

under ordinary worker, browser, source, model, and DB failures.

---

# 160. Implementation Order

Use:

```text
1. transition primitives
2. atomic claim + lease
3. actionable reserve query
4. strict age-cascade claim
5. retry scheduling
6. continuous worker
7. submission verification
8. ambiguous-submit reconciliation
9. crash recovery
10. channel health
11. bounded discovery refill
12. queue rebuild
13. maintenance
14. metrics
15. soak/throughput validation
```

Do not build continuous execution on unsafe claim/recovery semantics.

---

# 161. Final Workflow Reference

```text
                         +-------------------+
                         |    SOURCE FAN-IN  |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | OPPORTUNITY +     |
                         | OBSERVATIONS      |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | HARD ELIGIBILITY |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | FIT / RERANK      |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | READY PROJECTION  |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | AGE CASCADE CLAIM |
                         | 0–3 → 4–7 →      |
                         | 8–14 → 15–21      |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | JUST-IN-TIME      |
                         | PREPARATION       |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | CHANNEL ROUTER    |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | BROWSER GATEWAY   |
                         +---------+---------+
                                   |
                                   v
                         +-------------------+
                         | ATTEMPT + EVIDENCE|
                         +---------+---------+
                                   |
              +-------------------+-------------------+
              |                   |                   |
              v                   v                   v
          SUBMITTED          UNCONFIRMED        FAILURE/BLOCK
              |                   |                   |
              v                   v                   v
          COMPLETE           RECONCILE        RETRY/CHANNEL
                                                       |
                                                       v
                                               QUEUE / TERMINAL
                                                       |
                                                       +→ NEXT CLAIM
```

---

# 162. Final Directive

The workflow engine exists to maintain one durable, truthful loop:

```text
discover
→ evaluate
→ prioritize
→ claim
→ prepare
→ apply
→ verify
→ reconcile
→ persist
→ continue
```

Its purpose is not to maximize clicks.

Its purpose is to maximize verified, legitimate, qualified applications while preserving:

```text
candidate truth
duplicate safety
security boundaries
durable state
channel isolation
resource discipline
```

This is the operational execution layer beneath the frozen Hermes architecture.
