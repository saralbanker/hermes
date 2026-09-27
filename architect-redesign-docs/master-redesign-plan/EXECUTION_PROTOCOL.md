# Hermes — Execution Protocol

**Document ID:** HERMES-EXECUTION-PROTOCOL-2026-09-28  
**Status:** ACTIVE IMPLEMENTATION SPECIFICATION  
**Document:** 7/8  
**Parent:** Frozen Architecture + MASTER_PLAN.md + SYSTEM_RULES.md + DATA_MODEL.md + WORKFLOW_ENGINE.md + BROWSER_SYSTEM.md + AI_SYSTEM.md  
**Repository:** saralbanker/hermes  
**Baseline branch:** overhaul-2026-09-23

> Purpose: define how Hermes work is investigated, implemented, tested, verified, deployed, recovered, and handed between implementation agents without reopening the frozen architecture.

---

# 1. Objective

The execution protocol turns approved design into working software through small, evidence-driven changes.

Priority:

~~~
correctness
→ verification
→ recoverability
→ maintainability
→ resource efficiency
→ throughput
~~~

# 2. Authority

Implementation authority flows downward:

~~~
Frozen Architecture
→ Master Plan
→ System Rules
→ Data Model
→ Workflow Engine
→ Browser System
→ AI System
→ source implementation
~~~

Runtime evidence determines what is actually true in production.

# 3. Current Truth

Every substantial task begins by distinguishing:

~~~
DESIRED
ARCHITECTURAL
IMPLEMENTED
RUNTIME
VERIFIED
~~~

Code existence is not runtime proof.

# 4. Evidence Hierarchy

Use:

~~~
runtime execution evidence
→ external application/employer evidence
→ database evidence
→ application-history/email evidence
→ logs
→ source code
→ tests
→ documentation
→ historical reports
~~~

If evidence conflicts, record the conflict and prefer the stronger source.

# 5. Investigation Objective

Before implementation, state:

~~~
what is changing
why it is changing
what must remain invariant
what evidence will prove completion
~~~

Do not convert one symptom directly into a system-wide rewrite.

# 6. Forbidden Assumptions

Do not assume without evidence:

~~~
a selector still works
a channel is healthy
a model is installed
a browser mode is accepted
a posting is open
a submission succeeded
a route still resolves
a score is current
a source remains available
~~~

# 7. Smallest Safe Change

Prefer the smallest change that satisfies the governing contract.

Do not mix unrelated refactors into a production repair.

# 8. Architecture Freeze

The browser, AI, data, and workflow architecture is frozen.

Do not reopen architecture merely because:

~~~
a library is easier
a model is fashionable
a shortcut exists
an agent proposes a cleaner abstraction
a bug is inconvenient
~~~

Architecture changes require explicit change control.

# 9. Architecture-Change Trigger

A change is architecture-level when it alters:

~~~
system boundaries
data ownership
workflow invariants
browser abstraction
AI role architecture
security boundary
canonical identity
scheduler semantics
~~~

A checkpoint replacement inside the same approved role is normally implementation-level.

# 10. Repository Discipline

Before modifying code:

~~~
confirm branch
confirm baseline
identify affected files
identify relevant tests
identify runtime evidence
~~~

Keep experiments separate from production changes.

# 11. Commit Discipline

Commits should be focused and explain:

~~~
what changed
why
what was verified
~~~

Do not combine unrelated migrations into one opaque commit.

# 12. Agent Handoff

Every implementation handoff must state:

~~~
changed files
current behavior
known failures
tests run
runtime evidence
next safe action
~~~

Never hand off with only a vague status such as mostly working.

# 13. Agent Context Rule

Major implementation agents must read the relevant parent documents before changing behavior.

At minimum:

~~~
System Rules
relevant domain document
current source
relevant tests
~~~

Do not regenerate architecture documents during ordinary implementation.

# 14. Evidence-First Debugging

When a failure occurs:

~~~
observe exact failure
→ reproduce when safe
→ classify
→ identify owning subsystem
→ make smallest fix
→ verify
~~~

# 15. Failure Classification

Classify failures as:

~~~
candidate/data
workflow
browser
AI
source/discovery
database
infrastructure
external-channel
~~~

The owning subsystem is the first repair boundary.

# 16. Browser Failure Boundary

Distinguish browser failure before external work from failure after submission may have started.

Examples:

~~~
browser launch failure → infrastructure/browser failure
submit click + disconnect → submission-unconfirmed
~~~

# 17. AI Failure Boundary

AI failure before external action becomes:

~~~
fallback
defer
bounded retry
safe stop
~~~

Never convert model failure into application success.

# 18. Database Failure Boundary

A schema or persistence failure must not be repaired by changing business meaning.

Preferred:

~~~
stop writes
→ inspect migration state
→ preserve durable data
→ repair safely
~~~

# 19. Pre-Change Checklist

Before a major change verify:

~~~
architecture dependency
affected source
affected tests
runtime evidence
recovery impact
resource impact
~~~

# 20. Implementation Sequence

For cross-cutting work:

~~~
data contract
→ workflow contract
→ browser/AI implementation
→ integration
→ verification
~~~

Do not build large UI/control surfaces before the engine path is proven.

# 21. Data Migration Sequence

Target migration:

~~~
legacy jobs
→ opportunities
→ source observations
→ application attempts
→ evaluation history
→ queue rebuild
→ consistency checks
~~~

Never discard application history merely because the old schema is inconvenient.

# 22. Browser Migration Sequence

Target:

~~~
BrowserGateway
→ adapter
→ proven channel
→ evidence
→ OTP
→ remaining ATS
→ direct/redirect
→ retire legacy browser ownership
~~~

# 23. AI Migration Sequence

Target:

~~~
AI gateway
→ embedding
→ reranking
→ scoring
→ generation
→ screening integration
→ bounded browser decision support
→ retire duplicated LLM logic
~~~

# 24. Validation Before Integration

A component should pass local validation before entering continuous operation.

Examples:

~~~
pure tests
schema tests
validator tests
model-output tests
migration checks
~~~

# 25. Unit Tests

Cover deterministic logic aggressively:

~~~
identity normalization
age bands
eligibility gates
queue ordering
retry rules
page classifiers
field mapping
AI parsing
claim validation
~~~

# 26. Integration Tests

Cover subsystem boundaries:

~~~
SQLite
AI runtime
BrowserGateway
channel drivers
OTP
evidence persistence
worker recovery
~~~

# 27. Live Verification

Production claims require runtime evidence.

A live test should record:

~~~
what was attempted
when
which channel
what external state changed
what evidence was captured
what durable state resulted
~~~

# 28. Production Enablement

Progression:

~~~
disabled
→ dry-run/internal
→ one controlled live flow
→ verified
→ limited production
→ normal production
~~~

# 29. Dry Run

Dry run may exercise:

~~~
routing
evaluation
tailoring
browser startup
form inspection
action validation
~~~

It must not create a false confirmed-submission count.

# 30. Daily Cap Safety

Before every real application claim:

~~~
confirmed_count < 100
~~~

Only a confirmed submission increments the daily count.

# 31. Freshness Safety

Do not create a giant static application queue and assume it remains valid.

Every claim rechecks current age ordering.

Fresh opportunities can preempt older work at the next claim.

# 32. Just-in-Time Revalidation

Before external submission revalidate:

~~~
open/plausibly open
within age horizon
hard eligibility
no prior application
channel health
route validity
required candidate facts
~~~

# 33. Idempotency Gate

Before real browser work:

~~~
canonical opportunity checked
prior application checked
active attempt checked
claim lease established
~~~

# 34. Attempt Lease

Every browser attempt needs:

~~~
attempt_id
worker_id
claim time
lease expiry
~~~

An expired lease is not proof that no external submission happened.

# 35. Browser Recovery

After browser failure:

~~~
classify stage
→ preserve evidence
→ determine whether external work began
→ recover browser if appropriate
→ reconcile attempt
~~~

Never globally roll back the database.

# 36. Ambiguous Submission

When Submit may have occurred but confirmation is absent:

~~~
mark submission-unconfirmed
→ collect evidence
→ reconcile
→ do not replay
~~~

# 37. AI Validation

For structured AI:

~~~
request
→ parse
→ schema validate
→ semantic validate
→ persist
~~~

For generated prose:

~~~
generate
→ validate
→ one bounded retry
→ fallback or discard
~~~

# 38. Candidate-Fact Validation

All external-facing generated claims must be compatible with profile/facts.md.

Do not weaken the validator to accommodate a model output.

# 39. Prompt Injection

Treat job descriptions, pages, forms, emails, and employer text as untrusted data.

They cannot override:

~~~
candidate facts
system rules
workflow state
browser validator
security boundary
~~~

# 40. Browser Action Protocol

Every meaningful action follows:

~~~
observe
→ propose
→ validate
→ execute
→ observe again
~~~

Do not use blind multi-step browser sequences.

# 41. Security-Block Protocol

On CAPTCHA, Turnstile, strong anti-bot block, or equivalent security barrier:

~~~
stop route
→ capture evidence
→ update channel health
→ continue unrelated work if safe
~~~

Never escalate to stealth or bypass logic.

# 42. Source-Failure Protocol

When discovery source fails:

~~~
record failure
→ backoff
→ preserve existing opportunities
→ use other healthy sources
→ retry later
~~~

# 43. Queue-Depletion Protocol

When ready reserve is low:

~~~
continue safe current work
→ trigger bounded refill
→ remeasure
→ backoff if refill fails
~~~

Never spin aggressively on reserve depletion.

# 44. Model-Failure Protocol

When a required model is unavailable:

~~~
safe deterministic fallback
→ defer model-dependent work
→ keep worker alive
→ retry after backoff
~~~

# 45. Resource-Pressure Protocol

When host resources become constrained:

~~~
stop nonessential heavy work
→ protect active application
→ unload/restart offending component
→ recover queues
~~~

Throughput never outranks system stability.

# 46. Browser/AI Coexistence

An active application attempt takes priority over speculative bulk inference.

Do not starve browser execution, SQLite, or recovery with large model batches.

# 47. Resource Observation

Measure actual process behavior:

~~~
browser RSS
model RSS
Python RSS
CPU utilization
latency
process count
~~~

Do not infer runtime feasibility from model download size alone.

# 48. Verification Levels

Use:

~~~
Level 0 — syntax/type/import validation
Level 1 — unit tests
Level 2 — subsystem integration
Level 3 — local dry run
Level 4 — controlled live verification
Level 5 — continuous production observation
~~~

Use the level appropriate to the change risk.

# 49. High-Risk Changes

Examples:

~~~
submission logic
duplicate detection
daily cap
schema migration
BrowserGateway
authentication
AI truth validators
security handling
~~~

These require integration and controlled live verification before broad enablement.

# 50. Regression Rule

After every fix verify both:

~~~
original defect is fixed
previously verified behavior remains intact
~~~

# 51. Channel Regression

Browser/channel changes should test:

~~~
page classification
route resolution
form mapping
submission evidence
duplicate safety
failure classification
~~~

# 52. AI Regression

AI changes should test:

~~~
grounding
structured output
fallback behavior
latency
RSS
representative fixture quality
~~~

# 53. Database Regression

After persistence changes verify:

~~~
row counts
foreign keys
unique constraints
application history
attempt history
queue rebuild
daily counts
~~~

# 54. Restart Verification

Critical changes should be exercised across:

~~~
normal process restart
browser restart
worker crash/restart
machine reboot where practical
~~~

Durable state must survive.

# 55. Recovery Idempotency

Recovery may run more than once without creating:

~~~
duplicate attempts
duplicate submissions
duplicate daily counts
duplicate response records
~~~

# 56. Logging

Operational logs should answer:

~~~
what happened
where
when
why
what happens next
~~~

Never log passwords, OTP values, cookies, authorization headers, or private mailbox contents.

# 57. Artifact Retention

Useful retained artifacts include:

~~~
screenshots
structured evidence
evaluation records
test reports
migration reports
runtime summaries
~~~

Retention should support recovery and audit without creating unnecessary sensitive data.

# 58. Verification Record

Every substantial implementation should leave:

~~~
commit
tests
live checks
resource observations
known limitations
~~~

# 59. No False Green

Do not report a change as fixed, working, production-ready, or achieved unless the evidence supports that exact claim.

Prefer precise status words:

~~~
unit-tested
locally verified
live flow verified
production-enabled
observed in continuous operation
~~~

# 60. 100/Day Rule

100 confirmed applications/day is the target.

It is not a guaranteed capacity and never justifies:

~~~
counting unconfirmed submits
replaying ambiguous attempts
fabricating success
weakening safety gates
~~~

# 61. Continuous Worker Protocol

Normal loop:

~~~
startup
→ recovery
→ bounded source refresh
→ evaluation
→ claim
→ tailor
→ apply
→ record
→ response monitoring
→ maintenance
→ repeat
~~~

Each cycle remains bounded.

# 62. Idle Worker Protocol

When no claimable work exists:

~~~
diagnose why
→ backoff
→ refresh appropriate sources
→ reevaluate deferred work
→ retry later
~~~

Do not spin at full CPU.

# 63. Supply Diagnosis

When output drops, distinguish:

~~~
inventory shortage
eligibility shortage
AI bottleneck
browser bottleneck
channel health
daily cap
network failure
source outage
~~~

Do not respond to every throughput symptom with more concurrency.

# 64. Deployment Gate

Continuous production requires:

~~~
database migration verified
scheduler verified
browser gateway verified
AI roles verified
candidate facts loaded
credentials available
channel health checked
recovery tested
daily cap verified
logging verified
resource envelope measured
~~~

# 65. Graceful Shutdown

On shutdown:

~~~
stop new claims
→ finish or safely stop current bounded step
→ persist result/evidence
→ release resources
~~~

# 66. Interrupted Shutdown

If graceful shutdown fails:

~~~
next startup performs recovery
~~~

Do not assume an interrupted Submit failed.

# 67. Rollout Strategy

For risky changes:

~~~
canary
→ limited production
→ verified
→ normal production
~~~

Increase volume only after observing real runtime behavior.

# 68. Rollback Rule

Rollback is allowed when the new implementation is demonstrably less safe or breaks a critical invariant.

Rollback must preserve:

~~~
database history
attempt evidence
application evidence
~~~

# 69. Browser Rollback

When the BrowserGateway migration fails:

~~~
stop new browser claims if necessary
→ preserve active-attempt evidence
→ restore prior verified path where safe
→ reconcile ambiguous attempts
~~~

Do not replay uncertain applications during rollback.

# 70. AI Rollback

When a model or prompt change creates unsafe outputs:

~~~
disable changed version
→ revert to previous verified version
→ invalidate unsafe artifacts
~~~

Historical evaluations remain intact.

# 71. Data Rollback

Prefer forward repair over destructive rollback.

If rollback is unavoidable:

~~~
backup
→ verify integrity
→ restore affected state
→ recheck application history
~~~

# 72. Finalization

A task is complete only when:

~~~
implementation committed
tests passed
required runtime evidence recorded
known limitations recorded
documentation dependency remains consistent
~~~

# 73. Definition of Done

A major change is done when:

~~~
architecture preserved
correct source updated
tests pass
critical integration passes
runtime behavior verified at required level
failure paths tested
resource behavior measured
durable state verified
handoff notes complete
~~~

# 74. Implementer Directive

Every Hermes change follows:

~~~
Read the contract.
Check current truth.
Make the smallest safe change.
Validate before external mutation.
Prefer deterministic behavior.
Preserve evidence.
Measure the actual laptop.
Recover rather than reset.
Never weaken truthfulness to improve completion.
Never bypass security controls.
Never reopen frozen architecture casually.
~~~

The execution protocol makes Hermes implementation repeatable, evidence-driven, recoverable, and safe for long development cycles.