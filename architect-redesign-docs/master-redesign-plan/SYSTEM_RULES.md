# Hermes — System Rules

**Document ID:** HERMES-SYSTEM-RULES-2026-09-27  
**Status:** ACTIVE  
**Parent:** \`ARCHITECTURE_REDESIGN_FINAL-2026-09-27-FROZEN.md\` + \`MASTER_PLAN.md\`  
**Purpose:** Permanent behavioral and engineering rules for Hermes implementation and operation

> These rules sit below the frozen architecture and Master Plan. They constrain implementation; they do not redefine architecture.

---

# 1. Rule Precedence

When design or implementation documents conflict:

~~~
FROZEN ARCHITECTURE
        ↓
MASTER PLAN
        ↓
SYSTEM RULES
        ↓
DOMAIN DOCUMENTS
        ↓
SOURCE CODE
~~~

For current runtime truth, evidence strength is:

~~~
runtime execution evidence
→ external application / employer evidence
→ database evidence
→ application history / email evidence
→ logs
→ source code
→ tests
→ documentation
→ historical agent reports
~~~

Documentation describes intended behavior. It is not proof of production behavior.

Every important statement should be distinguishable as:

~~~
DESIRED
ARCHITECTURAL
IMPLEMENTED
RUNTIME
VERIFIED
~~~

---

# 2. Core Rules

1. Hermes is local-first.
2. Hermes must not require a recurring paid API or cloud inference service.
3. Hermes must preserve truthful candidate information.
4. Hermes must never blindly duplicate an application.
5. A submit click is not a confirmed submission.
6. No evidence means no confirmed submission.
7. Security controls are respected, not bypassed.
8. Canonical opportunity truth is separate from source observations, application attempts, and channel health.
9. Opportunity age priority is strict and fresh-first.
10. Durable state is preferred over assumptions during recovery.
11. A lower-level implementation failure must not silently become an architecture change.
12. Proven production paths must be preserved during migration until replacement behavior is verified.
13. Resource limits and optimization thresholds must be measured on the real laptop.
14. Safe explicit failure is preferable to a plausible but unverified success.

---

# 3. Candidate Truthfulness

\`profile/facts.md\` is the authoritative candidate fact source.

No model, prompt, config value, generated material, screening answer, or browser action may create a conflicting candidate profile.

Do not invent or inflate:

~~~
employment history
education
professional experience
client history
salary
production claims
job titles
certifications
technologies
locations
work authorization
availability
~~~

Preserve the distinction between:

~~~
hands-on software development
paid professional/client-facing work
formal employment
~~~

when forms ask for those concepts separately.

Numeric answers must use the truthful value represented by the candidate evidence. Project or coursework time must not be silently converted into fake professional years.

Generated application content may transform or emphasize verified facts, but may not invent facts.

Internal coding-agent names are not application material unless a form explicitly requires truthful disclosure.

---

# 4. Business Policy

Business policy values must be centrally configurable. Do not scatter duplicate magic numbers through unrelated source files.

Policy includes:

~~~
application target/day
India salary floor
global remote salary floor
normal office radius
night-shift office radius
21-day application horizon
age bands
core/stretch share
stretch constraints
source enablement
per-channel limits
retry limits
rate-control parameters
~~~

Current target values inherited from the Master Plan include:

~~~
100 confirmed, qualified applications/day
₹25,000/month India published salary floor
₹30,000/month global-remote published salary floor
20 km normal office/hybrid radius from Shahibaug
10 km night-shift office/hybrid radius
21-day application horizon
~70% core / ~30% stretch preference
~~~

Unknown salary must not be treated as zero.

A future UI may expose selected policy values, but the engine must not depend on a large dashboard.

Changing a policy value must not require changing canonical database semantics.

---

# 5. Canonical Opportunity Identity

A job URL is an observation locator, not the universal job identity.

Identity priority:

~~~
reliable source job ID
→ reliable ATS/company posting ID
→ normalized composite identity
~~~

A fallback identity must use enough stable fields to avoid obvious false merges.

Company + title alone is not a universal identity.

One canonical opportunity may have:

~~~
multiple source URLs
multiple observations
multiple historical states
multiple application attempts
multiple legitimate application channels
~~~

A previously seen URL must not become a permanent tombstone merely because it was seen before.

Confirmed prior submission is canonical application-history protection and prevents duplicate automatic submission.

Historical evaluation states such as filtered, skipped, or low-scoring must remain reevaluable unless a true terminal fact exists.

---

# 6. Source Observation Rules

Each discovery source must conceptually:

~~~
collect within legitimate limits
→ normalize
→ resolve canonical identity
→ store/update observation
→ refresh current state
→ evaluate policy
→ contribute actionable work when eligible
~~~

A source outage is not an opportunity deletion event.

Source observations preserve what the source reported at a point in time.

When a source offers a legitimate structured HTTP/API surface, Hermes may prefer it over browser discovery.

No source integration may be justified by a need to defeat security controls.

No uncontrolled high-frequency polling is permitted merely because reserve is low.

---

# 7. Age Rules

Automatic application eligibility ends at 21 days.

Only these application age bands exist:

~~~
0–3 days
4–7 days
8–14 days
15–21 days
~~~

At >21 days:

~~~
automatic application = forbidden
~~~

Age provenance should prefer:

~~~
verified posted_at
→ reliable source publication timestamp
→ first_seen_at only when reliable posted time is unavailable
~~~

Malformed or missing dates must not create immortal inventory.

Retry and recovery retain opportunity age semantics. They are overlays, not new age-priority queues.

---

# 8. Eligibility Rules

Hard eligibility is deterministic.

Hard gates may include:

~~~
unsupported geography
published salary below policy floor
clearly excluded role
clearly impossible experience requirement
older than 21 days
confirmed prior application
no supported legitimate application route
explicit security block
~~~

Missing evidence becomes explicit uncertainty.

Do not silently invent:

~~~
salary
location
experience
employment type
remote eligibility
~~~

Fit scoring is separate from hard eligibility.

A fit threshold must never permanently dead-letter a canonical opportunity merely because the opportunity was once scored below the threshold.

---

# 9. Core / Stretch Rules

The policy preference remains approximately:

~~~
~70% core
~30% stretch
~~~

This is not permission to violate hard eligibility.

Core/stretch preference must not invert the age cascade.

A stretch role may require stronger fit according to current policy, but Hermes must not fabricate experience to make a stretch opportunity eligible.

---

# 10. Scheduler Rules

The base scheduler is strict age cascade:

~~~
0–3d
→ 4–7d
→ 8–14d
→ 15–21d
~~~

Every claim reevaluates the cascade.

Within the selected age band, fit/ranking determines the candidate.

A newly discovered fresh opportunity can preempt an older candidate at the next claim.

WFQ is not the base scheduling model.

Retries, manual review, recovery, and channel cooldown do not create peer scheduler queues.

---

# 11. Reserve Rules

\`READY_RESERVE\` means currently actionable canonical opportunities.

It must exclude, at minimum:

~~~
expired opportunities
confirmed prior applications
live application attempts
opportunities blocked across all supported channels
non-actionable historical records
~~~

Planning target:

~~~
READY_RESERVE_TARGET = 300
~~~

This is a control buffer, not a guarantee of 300 successful applications.

Historical low-score records must not inflate actionable reserve.

When reserve is below target, refill may increase, but:

~~~
source polling remains bounded
backoff/cooldown is enforced
a low-reserve loop must not self-DOS the worker
~~~

Normal source refresh remains possible above target so inventory does not become stale.

---

# 12. Application Attempt Ledger

Every real application execution receives an attempt record.

The attempt record must answer:

~~~
what opportunity
which channel
when started
when finished
attempt number
what outcome
what evidence exists
what error class occurred
whether another attempt is safe
~~~

A durable lease must exist before browser work begins.

Do not hold SQLite write locks while the browser operates.

A process crash is not evidence of application failure.

An expired lease is not automatic permission to retry.

---

# 13. Submission Truth

Only a confirmed new submission counts toward the daily target.

~~~
submitted with valid evidence = +1
already_applied             = +0
submission_unconfirmed      = +0
failed                      = +0
blocked                     = +0
~~~

Evidence should be evaluated from the strongest available signals, such as:

~~~
explicit application/ATS confirmation
→ durable confirmation page or URL
→ legitimate application history
→ employer confirmation email
→ screenshot/page evidence
→ browser/network signals as supporting evidence
~~~

A successful local function return is not itself confirmation.

---

# 14. Submission-Unconfirmed Safety

\`submission_unconfirmed\` is a safety state.

When an outcome is ambiguous:

~~~
DO NOT immediately replay the application
~~~

Reconcile using legitimate evidence:

~~~
current page state
confirmation page / URL
application history
confirmation email
stored attempt evidence
~~~

Only evidence supporting non-submission permits another attempt.

Duplicate prevention has priority over optimistic retry.

---

# 15. Channel Health

Channel health is independent from opportunity truth.

Typical channel conditions:

~~~
HEALTHY
AUTH_EXPIRED
RATE_LIMITED
FORM_SCHEMA_CHANGED
ACCOUNT_WALL
ANTIBOT_BLOCKED
NETWORK_UNAVAILABLE
UNSUPPORTED
~~~

Repeated operational failures should affect channel health rather than permanently killing every opportunity associated with that route.

A channel may cool down while unrelated channels continue.

A channel is not production-proven because code exists or unit tests pass.

Production capability requires actual runtime evidence.

---

# 16. Aggregator Account Walls

Mandatory:

~~~
signup
register
account creation
~~~

is a channel limitation.

Hermes may resolve a legitimate direct or ATS route when known and supported.

Hermes must not:

~~~
fabricate an account
bypass the account wall
use fake identity data
~~~

---

# 17. BrowserGateway

All browser automation operates behind \`BrowserGateway\`.

The rest of Hermes must not depend directly on a specific browser library.

Browser adapters include:

~~~
CDP
Playwright
~~~

The gateway owns browser concerns such as:

~~~
navigation
session/context handling
frame discovery
structured DOM/ARIA state
shadow-root-aware inspection
readiness
field actions
button/link actions
file upload
screenshots/evidence
browser health
restart lifecycle
~~~

The browser subsystem is replaceable behind the gateway contract.

---

# 18. Browser State

Decision logic should consume structured state instead of unrestricted browser internals.

State should expose, when available:

~~~
URL
title
frames
dialogs
visible text
validation errors
interactive elements
role
accessible name
tag/type
value
placeholder
label
required
checked
selected
disabled
frame reference
safe element reference
~~~

Frames and supported shadow-root structures must be explicitly represented.

A missing top-level selector is not proof that an element does not exist.

Closed shadow DOM or platform restrictions must be classified as unsupported/fallback-required rather than guessed around.

---

# 19. Browser Actions

Browser execution follows:

~~~
structured state
→ candidate action
→ deterministic validator
→ CDP/Playwright execution
→ new structured state
~~~

Allowed action vocabulary should remain bounded, for example:

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

The decision layer may propose an action.

The deterministic validator decides whether it is legal.

No model receives unrestricted browser-code execution authority.

Stale selectors must not be blindly reused after page state changes.

---

# 20. Browser Readiness

Do not use a single \`networkIdle\` signal as universal readiness.

Actionable page state should consider:

~~~
navigation observed
URL/frame state stabilized
network behavior sufficiently quiet where meaningful
critical DOM/ARIA target exists
short state-stability window
~~~

Long-lived connections are not automatically failures.

---

# 21. Browser Sessions

Authenticated channels use persistent supported sessions where necessary.

Public/direct routes may use isolated contexts where useful.

Do not force incognito/new-context-per-job for authenticated workflows.

Do not require a new Chromium process for every application.

Browser restart is adaptive rather than tied to one universal page count or one universal time value.

Signals may include:

~~~
RSS growth
browser crash rate
renderer crash rate
protocol errors
page failure rate
session degradation
configured lifetime
~~~

---

# 22. Browser Resource Loading

Do not blindly block CSS or JavaScript.

The default must preserve:

~~~
HTML
JavaScript
required XHR/fetch/JSON
form logic
~~~

Only non-essential resources may be reduced when measured safe, such as:

~~~
large images
video/media
analytics/tracking
non-essential fonts
~~~

If resource reduction breaks a channel, narrow or disable it for that route.

---

# 23. Security Boundary

Hermes must not attempt to defeat:

~~~
CAPTCHA
Turnstile
Cloudflare bot challenges
fingerprinting defenses
rate limits
account verification
other platform security controls
~~~

A challenge produces a typed security-block outcome and channel-health update.

Human-like pacing is permitted only as ordinary operational rate control.

Security-evasion or stealth tooling is not part of the architecture.

---

# 24. Local AI Responsibilities

AI capabilities are separated:

~~~
semantic embeddings
semantic reranking
fit scoring
cover-letter tailoring
screening-answer generation
bounded browser decision support
~~~

Hard eligibility remains deterministic.

Final browser-action validation remains deterministic.

The current four-model baseline is:

~~~
Nomic embedding model
BGE-class reranker
Phi-4-mini scoring/classification specialist
Qwen3.5-4B generation specialist
~~~

Exact checkpoint variants remain benchmark-selected inside those role contracts.

Only one primary generative specialist should normally be resident on the 16 GB host.

Model storage size and parameter count are not substitutes for measured Linux/Ollama process RSS.

Before loading or reloading a generative/scoring model, check current browser process RSS (BROWSER_SYSTEM.md §81); before opening a new browser context mid-cycle, check current Ollama RSS. If combined measured RSS would exceed the safe ceiling established during IMPLEMENTATION_ROADMAP.md §22's resource baseline, the lower-priority operation defers per the existing priority order (AI_SYSTEM.md §74).

---

# 25. AI Output Validation

All generated application material must be validated against the candidate fact source.

The model must not invent:

~~~
employment
education
salary
professional-experience years
clients
production claims
unsupported technologies
~~~

Screening answers require fact/policy validation before browser submission.

The model controls wording.

Deterministic policy controls whether the factual claim is allowed.

---

# 26. SQLite Rules

SQLite remains the system of record.

Required:

~~~
WAL enabled
short write transactions
BEGIN IMMEDIATE for atomic claim where required
no browser-held write lock
~~~

\`SELECT ... FOR UPDATE\` is not part of Hermes.

Do not rewind the whole database to an old snapshot merely because a browser crashed.

Backups are disaster-recovery snapshots, not routine browser-crash undo points.

SQLite busy errors require bounded retry/backoff while preserving transaction discipline.

Checkpoint maintenance (reclaiming WAL pages back into the main database file) is owned by the existing periodic maintenance pass (WORKFLOW_ENGINE.md §76, "DB health") — it is not a separate worker or watchdog. If a long-lived reader blocks a checkpoint from completing, maintenance does not force-close that reader; it logs the condition and retries on the next pass. WAL file size is a monitored metric (§32) precisely so unbounded growth from a stuck checkpoint is visible rather than silent.

---

# 27. Lease and Recovery Rules

A claimed application must record enough durable information to recover after process death.

Minimum conceptual data:

~~~
claimed_at
lease_until
attempt_id
worker_id
last_attempt_at
~~~

Recovery:

~~~
find expired leases
→ inspect known outcome
→ reconcile ambiguous submissions
→ recover safely
~~~

Recovery must favor duplicate prevention over optimistic retry.

---

# 28. Failure Classification

Do not collapse typed failures into generic \`failed\` when the system can preserve the real class.

Conceptual behavior:

| Failure | Rule |
|---|---|
| Network timeout | bounded transient retry |
| Ollama unavailable | defer or deterministic fallback; do not crash worker |
| Form changed | re-inspect structured state; bounded retry |
| Unexpected field | re-read state; do not reuse stale selectors |
| Auth expired | channel pause / re-auth path |
| Account wall | alternate legitimate route or unsupported |
| CAPTCHA | security block |
| Turnstile/Cloudflare | security block |
| Rate limit | channel cooldown |
| Browser crash | restart browser; recover DB state normally |
| SQLite busy | bounded retry |
| DB corruption | stop worker; recover from verified backup |
| Ambiguous submit | reconcile before retry |
| >21 days | expire permanently for automatic application |

---

# 29. Continuous Worker

Production application execution is continuous.

Logical loop:

~~~
recover
→ discover / refresh
→ update reserve
→ hard eligibility
→ rank / score as needed
→ claim by age cascade
→ tailor just in time
→ resolve channel
→ apply
→ verify evidence
→ record attempt/outcome
→ health / maintenance
→ repeat
~~~

Source operations may remain periodic when source constraints require it.

The overall system must continuously replenish and consume actionable work.

Legacy large scheduled application batches are not the production engine.

---

# 30. Concurrency

Default application execution is:

~~~
1 application browser worker
1 active application page
bounded supporting work
~~~

Additional concurrency is a measured optimization, not a design requirement.

Do not add workers merely to reach a theoretical throughput number.

Before increasing concurrency, verify:

~~~
memory stability
browser stability
channel stability
confirmation safety
queue correctness
~~~

---

# 31. Response Monitoring

Gmail response monitoring is an independent support path.

A response watcher failure must not stop the application worker.

Email classification must use application-aware correlation.

Generic terms such as:

~~~
no-reply
recommended jobs
~~~

must not by themselves create an application acknowledgement.

Response monitoring state must remain distinct from submission confirmation.

Notifications travel the fixed path **Company → Platform → Gmail → Hermes → Telegram**. Every notification-worthy event must be classified into exactly one severity tier:

~~~
Ignore — no durable action, no record
Log — recorded for observability, not surfaced to the user
Telegram Notification — routine/operational, sent to the user's Telegram
High Priority Telegram Notification — affects a human-required decision (Section 22 of ARCHITECTURE_REDESIGN_FINAL-2026-09-27-FROZEN.md: interview decisions, salary negotiation, offer handling, contract handling, legal/identity document handling)
~~~

Only `Telegram Notification` and `High Priority Telegram Notification` reach the user; `Ignore` and `Log` do not.

---

# 32. Observability

The system must distinguish:

~~~
SUPPLY FAILURE
DECISION FAILURE
BROWSER FAILURE
CHANNEL FAILURE
CONFIRMATION FAILURE
~~~

Minimum operational metrics include:

~~~
open_reserve
eligible_reserve
ready_reserve
age-band depth
applications attempted today
applications confirmed today
confirmation rate
submission_unconfirmed count
retryable failure count
channel health
browser crash/restart count
process RSS
model latency/failure rate
DB busy/retry count
WAL size / checkpoint lag
source freshness
~~~

The daily application metric must count confirmed new submissions only.

---

# 33. Repository Change Discipline

Before modifying a load-bearing component:

~~~
read the governing documents
inspect the current implementation
identify actual runtime state
define the exact change boundary
~~~

Current load-bearing areas include:

~~~
src/pipeline.py
src/discover.py
src/score.py
src/tailor.py
src/apply.py
src/indeed_apply.py
src/ats_apply.py
src/direct_form.py
src/redirect_resolver.py
src/otp_resolver.py
src/db.py
src/states.py
src/filters.py
src/answers.py
src/response_watcher.py
config.yaml
profile/facts.md
~~~

Do not mix unrelated cleanup into an architecture implementation.

Do not delete a proven production path merely because a replacement abstraction is being introduced.

Migrate incrementally and preserve evidence-backed behavior until the replacement is verified.

---

# 34. Testing

Tests support implementation confidence but do not replace runtime proof.

Changes affecting:

~~~
identity
state transitions
claiming
submission handling
browser automation
routing
AI validation
recovery
~~~

require targeted tests.

Browser/channel validation should progress:

~~~
unit test
→ integration test
→ controlled runtime test
→ real production evidence where safe and legitimate
~~~

Mocked external-browser tests cannot be described as proof of production submission.

---

# 35. Documentation Discipline

Every lower-level planning document must state:

~~~
its parent documents
its owned scope
its inherited frozen decisions
its interfaces/dependencies
~~~

Do not duplicate the full architecture inside every document.

Do not create additional planning documents merely because a topic is interesting.

A new document is justified only when an existing document would otherwise become ambiguous or overloaded.

Lower-level documents add detail; they do not silently change frozen decisions.

---

# 36. AI-Agent Execution Contract

Every AI coding agent must:

~~~
READ governing documents
→ inspect repository evidence
→ establish current truth
→ identify exact change boundary
→ implement within scope
→ run targeted tests
→ run required runtime verification
→ compare results with acceptance criteria
→ report evidence and uncertainty
~~~

Agents must not:

~~~
invent repository state
invent candidate facts
silently change business policy
redesign architecture because implementation is difficult
replace missing evidence with assumptions
rewrite unrelated modules
claim production proof from tests alone
~~~

When implementation conflicts with architecture, surface the conflict.

Do not resolve it by silently changing architecture.

---

# 37. Forbidden Engineering Patterns

The following are forbidden unless an explicit architecture change is approved:

~~~
WFQ as the base scheduler
>21-day automatic application queue
URL-only permanent tombstones
generic replay of application submission POSTs
blind duplicate retry
SELECT ... FOR UPDATE
whole-database rollback after browser crash
incognito for every job
new Chromium process per job as a universal rule
blind CSS/JS blocking
unrestricted browser LLM control
security-evasion tooling
fake candidate data
fake accounts for platform bypass
large distributed service decomposition
large dashboard before engine proof
new candidate-facing platforms solely for architecture completeness
~~~

---

# 38. Production Safety Priority

When optimization conflicts with correctness, use this order:

~~~
truthfulness
→ duplicate safety
→ security boundary
→ durable state
→ correctness
→ channel stability
→ resource stability
→ throughput
~~~

Throughput is important, but it is never permission to weaken the layers above it.

---

# 39. Architecture-Change Boundary

The following changes require explicit architecture review:

~~~
canonical identity semantics
21-day application horizon
strict age cascade
submission confirmation semantics
BrowserGateway boundary
browser security boundary
SQLite system-of-record decision
continuous worker architecture
AI role boundaries
one-primary-generator residency rule
application attempt semantics
truthfulness constraints
~~~

Ordinary tuning does not automatically require architecture review:

~~~
selector changes
prompt wording
timeouts
batch sizes
context sizes
polling intervals
query tuning
logging
metric presentation
internal code organization
measured resource thresholds
~~~

A true architecture change must record:

~~~
existing decision
new decision
reason
evidence
impact
migration requirements
recovery considerations
~~~

No implementation prompt may smuggle an architecture change into ordinary coding work.

---

# 40. Definition of Done

An implementation is not complete because the code compiles or unit tests pass.

Completion requires alignment across:

~~~
architecture
→ implementation
→ runtime behavior
→ verification evidence
~~~

The overhaul must demonstrate:

~~~
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
~~~

The 100/day target is achieved only when real confirmed evidence supports it under legitimate supply and available supported channels.

---

# 41. Final Directive

Hermes optimizes this real funnel:

~~~
fresh supply
→ eligible supply
→ useful ranking
→ actionable queue
→ safe application
→ verified submission
~~~

When performance is below target:

1. measure the failing layer,
2. preserve truth and safety,
3. fix the measured bottleneck,
4. verify the change,
5. continue.

Do not compensate for a weak layer by weakening another layer.

