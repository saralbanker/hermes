# Hermes — Final Architecture Redesign Baseline

**Document ID:** HERMES-ARCH-FINAL-2026-09-27  
**Status:** FROZEN ARCHITECTURE BASELINE  
**Purpose:** Authoritative architecture baseline for all subsequent implementation/planning documents  
**Target:** 100 truthful, confirmed job applications/day  
**Runtime:** Local-first, no recurring paid API/service dependency  
**Operating system:** Arch Linux  
**Hardware target:** ASUS VivoBook 17X, Ryzen 7 7730U, 16 GB RAM, Vega 8 iGPU, CPU-only local inference, no NVIDIA/CUDA dependency  
**Practical AI RAM budget:** 7–10 GB  
**Model storage budget:** 5–8 GB target  
**Primary runtime model host:** Ollama; ONNX Runtime / llama.cpp may be used for non-generative specialist models  
**Database:** SQLite/WAL  
**Browser:** Local Chrome/Chromium controlled through a Browser Gateway with CDP + Playwright adapters  
**Operating mode:** Continuous 24/7 worker while the machine is available

> **Architecture lock:** This document defines the final architecture, boundaries, state semantics, and non-negotiable design decisions. Subsequent implementation documents must implement this architecture rather than redefine it. Any future architectural change must be recorded explicitly as an architecture-change decision; it must not be introduced silently inside implementation work.

---

## 1. Executive Architecture Decision

Hermes will be redesigned from a **linear batch funnel** into a **continuous, stateful, evidence-driven opportunity-to-application system**.

The final architecture is:

```text
SOURCE FAN-IN
    |
    v
SOURCE OBSERVATIONS
    |
    v
CANONICAL OPPORTUNITY
    |
    v
CURRENT OPEN STATE
    |
    v
HARD ELIGIBILITY
    |        (geo / salary / role / experience / age / policy)
    v
FIT + RERANK
    |
    v
STRICT AGE CASCADE
    |        0–3d -> 4–7d -> 8–14d -> 15–21d
    v
APPLICATION CHANNEL ROUTER
    |
    v
BROWSER GATEWAY
    |        structured DOM/ARIA state + validated actions
    |        CDP for state/control; Playwright retained as proven adapter
    v
VERIFIED APPLICATION ATTEMPT
    |
    +--> SUBMITTED (confirmed evidence)
    +--> ALREADY_APPLIED
    +--> SUBMISSION_UNCONFIRMED (never blindly replay)
    +--> RETRYABLE_FAILURE
    +--> CHANNEL_BLOCKED / UNSUPPORTED_CHANNEL
    +--> EXPIRED (>21d)
```

The architecture has six core changes:

1. **URL is no longer the identity of a job opportunity.** Hermes stores canonical opportunities plus source observations and their changing state.
2. **Previously seen but not-submitted opportunities are not permanent tombstones.** They can be re-observed and re-evaluated while still valid.
3. **Scoring is a ranking signal, not a dead-end state.** Hard eligibility is deterministic; fit is continuously rankable.
4. **Scheduling uses a strict age cascade rather than WFQ.** At every claim, Hermes checks `0–3d`, then `4–7d`, then `8–14d`, then `15–21d`. A freshly discovered eligible job can therefore preempt an older one before the next claim.
5. **Application execution is continuous and single-worker by default.** Memory stability and correctness take precedence over speculative browser parallelism.
6. **Browser automation becomes state-aware rather than selector-fragile.** CDP provides structured browser/page state; a bounded decision layer may choose actions; deterministic code remains the final authority over what is executed.

---

# 2. Current Truth State the Redesign Must Fix

The architecture is based on the existing Hermes implementation and the latest audit evidence available before this baseline was written.

### 2.1 Measured database state

The audited database contained **8,688 rows** with the following major state distribution:

| State | Count | Architectural interpretation |
|---|---:|---|
| `filtered` | 5,571 | Historical evaluation results; not a permanent identity tombstone |
| `expired` | 1,436 | Terminal because posting age exceeded policy |
| `scored` | 795 | Mixed state; currently includes many effectively dead/under-threshold candidates |
| `skipped` | 728 | Historical pipeline disposition; must not permanently poison rediscovery |
| `submitted` | 50 | Confirmed application history |
| `unsupported_channel` | 48 | Channel problem, not necessarily an opportunity-level terminal state |
| `form_changed` | 42 | Recoverable/inspectable application failure class |
| `submission_unconfirmed` | 9 | Ambiguous outcome requiring evidence-led reconciliation |
| `failed` | 4 | Historical failure state requiring typed failure semantics |
| `blocked_antibot` | 3 | Security boundary state; never bypassed |
| `captcha_required` | 1 | Security boundary state; never bypassed |
| `tailored` | 1 | Ready-to-apply legacy inventory |

### 2.2 Proven bottlenecks

The current funnel exhibits these architectural defects:

- URL-level historical dedupe creates a permanent tombstone effect.
- A large number of `scored` jobs are frozen below tailoring thresholds instead of remaining rankable.
- Continuous reserve accounting counts inactive scored jobs as available inventory.
- Three daily batch runs are structurally incompatible with a continuous 100/day objective.
- Strict geographic filtering removes a very large fraction of raw listings; this remains an intentional eligibility policy, not something the redesign should bypass.
- Aggregator account walls create channel failures that should not be confused with an opportunity being invalid.
- Application failures are currently represented too heavily by a single job status model instead of separate opportunity, channel, and attempt histories.

### 2.3 Measured throughput truth

The latest audit does **not** prove 100 confirmed applications/day. Historical evidence included a 23/day peak and a more typical 10–15/day range under the existing batch-oriented architecture.

Therefore this redesign treats **100/day as the operating target, not an already-proven capability**.

Mathematically:

```text
100 confirmed applications / 24 h
= 4.17 confirmed applications / hour
= 1 confirmed application every 14.4 minutes on average
```

That is the throughput requirement the continuous worker must ultimately sustain when sufficient eligible supply exists. It is not a guarantee that 100/day is achievable on every day regardless of job supply, channel availability, ATS behavior, or account state.

---

# 3. Architecture Invariants — Non-Negotiable

These decisions are frozen and are not to be weakened during implementation.

### 3.1 Truth and identity

- A **job URL is an observation locator, not a permanent job identity**.
- A canonical opportunity may have many source URLs and many observations.
- A successfully submitted opportunity is permanently protected against duplicate application at the canonical-opportunity level.
- `already_applied` is also canonical-history state, not a URL tombstone.
- `unsupported_channel` and `blocked_antibot` are primarily **channel/destination states**, not automatic opportunity death.
- Application attempts are first-class historical records.

### 3.2 Age policy

The application eligibility horizon is exactly **21 days**.

The only application age bands are:

```text
BAND 0: 0–3 days     (0–72 hours)
BAND 1: 4–7 days     (>72–168 hours)
BAND 2: 8–14 days    (>168–336 hours)
BAND 3: 15–21 days   (>336–504 hours)
```

At `>21 days`, the opportunity is expired for automatic application and cannot enter the application queue.

There is **no >21-day application tier**.

Retry, recovery, manual review, and channel problems are **overlays/states**, not additional age bands.

### 3.3 Scheduling

The scheduler is **strict age-priority cascade**, not Weighted Fair Queuing.

At every job claim:

```text
search eligible 0–3d
  if available -> take highest-ranked candidate
else search 4–7d
  if available -> take highest-ranked candidate
else search 8–14d
  if available -> take highest-ranked candidate
else search 15–21d
  if available -> take highest-ranked candidate
else -> queue is empty
```

A job discovered during the current loop is eligible to preempt an older job at the next claim.

### 3.4 Browser safety boundary

Hermes will **not** bypass or defeat CAPTCHA, Cloudflare Turnstile, bot challenges, security controls, account verification, rate limits, or similar access controls.

A security challenge produces a typed blocked outcome and channel-health update. The system may legitimately try another already-supported application route when one exists, but it may not use evasion techniques to defeat the protection.

### 3.5 Database safety

SQLite remains the system of record.

- WAL mode remains enabled.
- Atomic state claims use short write transactions, with `BEGIN IMMEDIATE` where an immediate write lock is required.
- SQLite's concurrency model is respected: WAL permits readers and a writer to operate concurrently, but SQLite still serializes writers. citeturn393058search0turn138076search3
- **`SELECT ... FOR UPDATE` is not part of the architecture.**
- A browser crash must not cause a database rollback to an earlier arbitrary snapshot.
- Online backups are for disaster recovery/snapshots, not routine browser-crash recovery. citeturn393058search1turn393058search2

### 3.6 AI execution

- Embeddings are separate from generation models.
- At most **one primary generative specialist model** is resident during normal operation on the 16 GB machine.
- Model identity is selected through local benchmark gates; the **model role/interface is frozen even if the exact checkpoint changes**.
- No cloud inference or paid recurring AI API is required by the architecture.

---

# 4. Canonical Domain Model

The fundamental redesign is to separate concepts that the current `jobs` table conflates.

## 4.1 `opportunities`

Represents the canonical job opportunity.

Conceptual fields:

```text
opportunity_id
canonical_key
company_normalized
company_display
title_normalized
title_display
location_normalized
employment_type
first_seen_at
first_posted_at
last_observed_at
last_verified_open_at
current_open_state
age_basis
age_band
hard_eligibility_state
fit_state
fit_score
fit_reasons
core_or_stretch
application_state
terminal_reason
created_at
updated_at
```

The exact SQL schema is an implementation concern, but the semantic separation is architectural.

## 4.2 Canonical identity

Identity selection is hierarchical:

```text
1. Reliable source-specific job ID
2. Reliable ATS/company posting ID
3. Normalized composite identity
```

Fallback composite identity should include enough fields to avoid false merges, at minimum:

```text
normalized company
+ normalized title
+ normalized location
+ relevant employment type / posting discriminator
```

**Company + title alone is not sufficient as the universal canonical identity.**

URLs may change, tracking parameters may change, aggregator links may change, and the same posting may appear on several sources. Canonical identity must therefore survive URL churn.

## 4.3 `source_observations`

Represents what a specific source reported about an opportunity.

Conceptual fields:

```text
observation_id
opportunity_id
source
source_job_id
source_url
observed_at
posted_at
open_state
salary_raw
location_raw
description_hash
apply_url(s)
raw_metadata
observation_status
```

Every discovery pass can update an observation without creating a duplicate canonical opportunity.

This solves the current tombstone problem while preserving historical evidence.

## 4.4 `application_attempts`

Every real application execution receives an attempt record.

Conceptual fields:

```text
attempt_id
opportunity_id
channel
started_at
finished_at
attempt_number
outcome
http_or_browser_signals
confirmation_url
confirmation_text
account_history_signal
screenshot_evidence
email_evidence
error_code
error_class
execution_phase
retry_eligible
```

The attempt ledger is the authoritative explanation of **what Hermes actually did**.

## 4.5 `channel_health`

Represents channel-level operational health independently of job identity.

Examples:

```text
Indeed       AUTHENTICATED / HEALTHY
Greenhouse   HEALTHY
Lever        HEALTHY
Ashby        BLOCKED_ANTIBOT
Aggregator X UNSUPPORTED_ACCOUNT_WALL
```

A bad channel should not corrupt the truth about otherwise valid opportunities.

## 4.6 `work_queue` / scheduling projection

A durable scheduling projection may be used for efficient claiming, but it is **not a second source of truth**.

The queue contains only derived work state, such as:

```text
opportunity_id
ready_state
age_band
priority_score
next_attempt_at
lease_until
channel_candidate
updated_at
```

If the queue is rebuilt, it must be derivable from the canonical opportunity/application state.

---

# 5. Lifecycle and State Semantics

The new state model separates opportunity truth from processing state.

## 5.1 Opportunity lifecycle

```text
OBSERVED
  |
  v
OPEN
  |
  v
HARD-ELIGIBLE
  |
  v
RANKED
  |
  v
READY
  |
  v
APPLICATION IN PROGRESS
  |
  +--> SUBMITTED
  +--> ALREADY_APPLIED
  +--> SUBMISSION_UNCONFIRMED
  +--> RETRYABLE_FAILURE
  +--> CHANNEL_BLOCKED
  +--> MANUAL_REVIEW
  +--> EXPIRED
  +--> SKIPPED_BY_POLICY
```

These states must not be collapsed into a single overloaded `status` field when doing so destroys the distinction between opportunity, application, and channel state.

## 5.2 Filtering is an evaluation, not necessarily terminal history

A previous decision such as:

```text
filtered because salary unavailable
filtered because geography failed
filtered because score was low
```

must be retained as historical evaluation evidence, but it must not automatically prevent a newer observation from being evaluated again.

The exception is a **true canonical terminal fact**, such as a confirmed prior submission or a verified permanent duplicate.

## 5.3 Age provenance

Every opportunity needs a defensible age basis:

```text
age_basis = verified posted_at
        OR reliable source publication timestamp
        OR first_seen_at when no reliable posted time exists
```

Malformed/missing dates must not create immortal inventory.

Once the fallback age clock reaches 21 days, automatic application eligibility ends.

---

# 6. Discovery Architecture

Hermes becomes a continuously refreshed **source fan-in** system.

Current source families remain the starting point:

```text
Indeed / existing candidate-facing boards
Public ATS sources: Greenhouse / Lever / Ashby
WWR
Arbeitnow
RemoteOK
Remotive
Himalayas
Existing supported direct/ATS routes
```

The architecture does not require adding new candidate-facing platforms merely to increase source count.

## 6.1 Discovery behavior

Discovery is **HTTP/API-first where a source exposes a legitimate public/structured read path**, with browser automation reserved for sources and flows that actually require browser state.

Each discovery cycle:

1. Queries supported sources within their legitimate limits.
2. Uses normal HTTP/API retrieval where sufficient; otherwise uses the browser layer.
3. Normalizes records.
4. Resolves canonical identity.
5. Creates or updates source observations.
6. Re-evaluates current open state.
7. Runs hard eligibility.
8. Updates the derived ready reserve.
9. Makes the opportunity available for ranking/scheduling if eligible.

HTTP-first discovery is a performance and reliability optimization, **not an anti-bot bypass strategy**. Hermes does not use TLS impersonation, fingerprint evasion, or similar techniques to defeat access controls.

## 6.2 Tombstone elimination

The old rule:

```text
seen URL before -> discard forever
```

is removed.

The new rule is:

```text
seen opportunity before
    -> update observation
    -> refresh current state
    -> re-evaluate policy
```

Permanent application-history protection is based on canonical application state, not historical URL presence.

## 6.3 Discovery freshness

Discovery is no longer a once-or-three-times-per-day event.

The continuous worker performs lightweight refreshes continuously, with deeper refill behavior when actionable reserve falls below target.

The exact source polling cadence belongs in implementation configuration because different sources have different rate limits and failure behavior. The architecture requires **continuous replenishment**, not a fixed universal polling interval.

Reserve-driven refill must use bounded backoff and source-health awareness. A permanently low reserve must **not** cause an unbounded tight polling loop against the same unhealthy source.

---

# 7. Hard Eligibility vs Fit Ranking

This is a critical architectural separation.

## 7.1 Hard gates are deterministic

A candidate is rejected from automatic application only for documented hard constraints such as:

```text
unsupported geography
salary below policy floor when reliably known
clearly disallowed role
age > 21 days
required experience clearly impossible under policy
known duplicate / already applied
no supported legitimate application path
explicit safety/security block
```

When evidence is missing, the implementation must use explicit uncertainty semantics rather than silently inventing a value.

## 7.2 Fit is probabilistic/ranked

After hard eligibility, Hermes computes fit using:

```text
deterministic fit signals
       +
semantic embedding similarity
       +
local specialist SLM judgment
```

The resulting score is a ranking feature.

A score must **not** create another dead-letter pool like the current `scored < threshold` backlog.

## 7.3 Core vs stretch

The existing goal of roughly:

```text
~70% core
~30% stretch
```

is retained as a **selection preference**, not as a hard age-priority override.

Core/stretch classification is therefore secondary to:

1. hard eligibility,
2. opportunity age band,
3. application safety/channel availability.

Within the same age band, fit and core/stretch policy can influence ranking.

## 7.4 Threshold policy

Numerical thresholds remain configuration rather than database semantics.

The architecture intentionally avoids:

```text
score < X -> permanently trapped
```

A future threshold change must immediately affect ranking because the opportunity remains canonical and reevaluable.

---

# 8. Reserve Architecture

The redesign replaces the current flawed `discovered + scored + tailored` reserve formula with actionable reserve metrics.

## 8.1 Primary reserve

```text
READY_RESERVE = count of canonical opportunities that are:

- currently open or plausibly open
- within 21 days
- hard-eligible
- not already applied/submitted
- not currently in a live application attempt
- not permanently blocked across all supported channels
- available for ranking or application
```

A sub-threshold historical `scored` record does not inflate this value.

## 8.2 Reserve target

The planning target remains:

```text
READY_RESERVE_TARGET = 300
```

This is approximately three days of theoretical 100/day demand and provides a control buffer.

It is not a promise of three days of guaranteed successful submissions.

## 8.3 Reserve trigger

Discovery/refill should be activated when:

```text
ready_reserve < 300
```

but normal source refresh continues even above 300 so the system does not become stale again.

When reserve remains below target because a source or channel is unhealthy, refill attempts use bounded backoff, cooldown, and source/channel health signals rather than spinning continuously.

A secondary reserve health model may track:

```text
OPEN_RESERVE
ELIGIBLE_RESERVE
RANKED_RESERVE
TAILORED_RESERVE
CHANNEL_READY_RESERVE
```

This makes upstream starvation visible instead of hiding it in one integer.

---

# 9. Final Scheduler — Strict Cascading Age Priority

The scheduler is deliberately simpler than the proposed WFQ design.

## 9.1 Why WFQ is not the final choice

Weighted Fair Queuing would solve a different problem: mathematically fair service between peer queues.

Hermes has a stronger business rule:

> **Newer eligible opportunities must be attempted before older eligible opportunities.**

Therefore Hermes uses strict age ordering with fit ranking inside each age band.

## 9.2 Scheduler ordering

The canonical claim order is:

```text
AGE BAND 0: 0–3d
    |
    +-- highest fit/rank first
    |
    v
AGE BAND 1: 4–7d
    |
    +-- highest fit/rank first
    |
    v
AGE BAND 2: 8–14d
    |
    +-- highest fit/rank first
    |
    v
AGE BAND 3: 15–21d
    |
    +-- highest fit/rank first
```

Every claim re-evaluates the cascade.

A new 1-day-old opportunity arriving during a processing loop does not wait behind the rest of a previously computed 7-day queue; it can be selected at the next claim.

## 9.3 Retry overlay

Retries do not create a new peer queue.

A retryable opportunity retains its age band.

Example:

```text
Day 2 job
  -> form_changed
  -> retry becomes due later
  -> it remains in the 0–3d age band
```

This avoids mixing time priority with failure priority.

## 9.4 Backlog safety

There is no permanent stale queue.

At `>21 days`:

```text
OPEN opportunity -> EXPIRED
```

Historical information is preserved for analytics, but it cannot consume automatic application capacity.

---

# 10. Application Channel Architecture

Hermes separates **opportunity discovery** from **application route resolution**.

## 10.1 Channel resolution order

A canonical opportunity may expose several legitimate routes:

```text
existing direct employer form
-> supported ATS
-> supported authenticated board/application flow
-> supported direct redirect
-> unsupported/account-wall/blocked
```

The resolver chooses a supported route without bypassing security controls.

No single source or ATS is architecturally guaranteed to provide the majority of daily capacity. The system must continue operating through healthy alternate supported routes when a particular channel degrades.

## 10.2 Channel health

Repeated failures should affect the channel, not poison every opportunity.

Examples:

```text
AUTH_EXPIRED
RATE_LIMITED
FORM_SCHEMA_CHANGED
ACCOUNT_WALL
ANTIBOT_BLOCKED
NETWORK_UNAVAILABLE
HEALTHY
```

A temporarily unhealthy channel can pause while the rest of Hermes continues.

Repeated typed failures should be able to trigger a channel cooldown/circuit-breaker state. Exact thresholds and cooldown durations are tuning parameters, not architectural constants.

## 10.3 Unsupported aggregator account walls

A redirect to `/signup`, `/register`, or an equivalent mandatory account wall is a channel limitation.

Hermes should:

```text
try legitimate direct/ATS resolution if known
       |
       +--> success -> continue
       +--> no valid route -> channel unsupported
```

It must not fabricate an account or bypass the wall.

---

# 11. Final Browser Architecture

The browser redesign is **CDP-primary for structured state**, but it does not discard proven Playwright execution.

CDP is a low-level control protocol, not inherently a magic reliability layer. The architectural improvement comes from **structured browser state + bounded deterministic actions + validation**, not merely replacing one API with another.

## 11.1 Browser Gateway

All browser operations should go through a single Hermes abstraction:

```text
BrowserGateway
    |
    +-- PlaywrightAdapter
    |
    +-- CDPAdapter
```

The rest of Hermes must not hard-code itself to one browser library.

This makes incremental migration possible.

## 11.2 Responsibilities

The gateway owns:

```text
navigation
session/context management
frame discovery
DOM state extraction
ARIA/accessibility state
shadow-root-aware inspection
network/page events
wait/readiness state
field actions
button/link actions
file upload
screenshots/evidence
browser health
restart lifecycle
```

Chrome DevTools Protocol exposes structured accessibility operations such as AX-tree retrieval and querying by accessible name/role, which is suitable input for this architecture. citeturn138076search2

## 11.3 Structured page state

The page should be represented to decision logic as structured state, conceptually:

```text
PAGE
  url
  title
  frames[]
  dialogs[]
  validation_errors[]
  visible_text
  interactive_elements[
      index
      role
      accessible_name
      tag
      type
      value
      placeholder
      label
      required
      checked
      selected
      disabled
      frame_id
      selector/reference
  ]
```

The decision layer must never receive unrestricted authority to execute arbitrary browser code.

## 11.4 Dynamic SPA readiness

A single `networkIdle` event is insufficient as a universal readiness guarantee.

The final readiness model is:

```text
navigation observed
      +
URL/frame state stabilized
      +
network activity sufficiently quiet
      +
critical DOM/ARIA target exists
      +
short DOM/state stability window
      = ACTIONABLE PAGE STATE
```

This handles long-lived connections and SPAs more reliably than using one event as a universal completion signal.

## 11.5 Shadow DOM and frames

The browser state layer must explicitly model:

```text
main document
open shadow roots
iframes / child frames
form controls inside frames
```

A DOM object not visible through a naive top-level selector must not be treated as proof that the form element does not exist.

Closed shadow DOM and security-restricted content remain browser/platform limitations; Hermes must classify such situations as unsupported or fallback-required rather than inventing selectors.

## 11.6 Action execution rule

The frozen base architecture does **not require a browser-agent LLM**.

The execution model is:

```text
structured state
      |
      v
deterministic candidate actions
      |
      v
ACTION VALIDATOR
      |
      v
Playwright/CDP execution
      |
      v
new structured state
```

The validator is mandatory.

The action vocabulary is deliberately bounded:

```text
CLICK(index)
TYPE_TEXT(index, safe_text)
SELECT(index, option)
CHECK(index)
UNCHECK(index)
SCROLL(direction)
WAIT(condition)
DONE
BLOCKED
```

Hermes code decides whether an action is legal for the current state. Browser control remains deterministic and policy-validated.

A future browser decision model would require explicit architecture-change review; it is not part of this frozen baseline.

---

# 12. Browser Context and Session Model

The Qwen proposal to use an incognito context for every job is **not universal architecture** because authenticated boards require durable sessions.

Playwright supports isolated browser contexts, including non-persistent contexts, but persistent authenticated state is a separate operational requirement. citeturn138076search0

Final model:

```text
AUTHENTICATED BOARD
    -> persistent supported browser profile/session

PUBLIC/DIRECT OPPORTUNITY
    -> disposable isolated context where useful
```

Examples:

```text
Indeed -> persistent authenticated profile
ATS/public page -> isolated context may be used
Direct company form -> isolated context is preferred unless channel requires session continuity
```

The architecture does not mandate launching a new Chromium process per job.

---

# 13. Resource and Browser Lifecycle Policy

The laptop has 16 GB RAM, so memory discipline is an architecture requirement.

## 13.1 Concurrency

Default application execution:

```text
1 application browser worker
1 active primary application page at a time
bounded supporting background work
```

Parallel browser submissions are not part of the base architecture.

If concurrency is later introduced, it is a measured optimization and must not change queue semantics.

## 13.2 Resource loading

Hermes should **not** blindly block CSS or JavaScript.

JavaScript is frequently required by React/Vue/Angular applications, and CSS can affect visibility/layout-dependent interaction.

Resource policy:

```text
MUST PRESERVE:
HTML
JavaScript
XHR/fetch/JSON required by the application
form/page logic

OPTIONALLY REDUCE WHEN MEASURED SAFE:
large images
video/media
third-party analytics
tracking payloads
non-essential fonts
```

Any resource-block rule that causes functional failures must be disabled for that channel.

## 13.3 Browser restart

Browser restart is **adaptive**, not hard-coded as an architectural guarantee of exactly 100 pages or exactly 60 minutes.

Restart signals may include:

```text
RSS/memory growth
browser crash count
renderer crash count
page failure rate
persistent protocol errors
long-term session degradation
configured maximum lifetime
```

An initial implementation may use conservative render/time thresholds, but those are tuning parameters rather than architecture.

## 13.4 Browser crash recovery

On browser crash:

```text
browser process -> restart
worker state -> recover from SQLite
APP IN PROGRESS lease -> reconcile
queue -> continue
```

The system does not restore the whole database to an old checkpoint merely because Chrome crashed.

SQLite WAL is explicitly designed for transactional durability/recovery, while backups are separate snapshot mechanisms. citeturn393058search0turn393058search1

---

# 14. Final Local AI Architecture

Hermes will use **specialized sequential local models** under a strict resource budget.

The architecture freezes the model **roles and baseline four-model set** below. Local benchmarking may tune quantization, context size, batching, residency, and task prompts. Replacing a baseline model with a materially different model is an architecture-change decision, not an incidental implementation tweak.

## 14.1 Baseline model set and roles

| Model | Runtime | Frozen architecture role |
|---|---|---|
| `qwen3.5:4b` | Ollama | Primary generation specialist for tailoring and difficult screening-answer reasoning |
| `phi4-mini:3.8b` | Ollama | Lightweight scoring/classification specialist for fit judgment and other bounded text decisions |
| `nomic-embed-text:v1.5` | Ollama | Semantic embeddings / cheap pre-ranking |
| `BAAI/bge-reranker-base` | ONNX Runtime / local CPU path | Top-k semantic reranking after embedding retrieval |

These four models are sufficient for the base architecture. No fifth generative model and no browser-agent model is required for the frozen design.

The four-model package set is intended to stay within the project's 5–8 GB model-storage objective; exact on-disk size depends on runtime packaging and quantization.

The current Ollama registry exposes `qwen3.5:4b` at about 3.4 GB and `phi4-mini:3.8b` at about 2.5 GB in their listed Q4 variants; Ollama also lists `nomic-embed-text:v1.5` at about 274 MB. These published package sizes are references, not substitutes for measured process RSS on Hermes' target laptop. citeturn821580search1turn821580search0turn578528search0

## 14.2 Memory contract

On a 16 GB host:

```text
Nomic embedding model may remain resident if measured safe.
Only one generative model should normally remain resident.
Qwen3.5-4B and Phi-4-mini are loaded sequentially, not simultaneously.
Reranking should run only on top-k survivors.
Model switching must release unnecessary generation memory.
Browser memory is budgeted explicitly.
Practical AI RAM budget remains 7–10 GB.
```

The architecture does not assume that theoretical model-size calculations equal actual RSS on Linux/Chrome/Ollama.

## 14.3 Hybrid fit pipeline

Final scoring flow:

```text
Hard eligibility
      |
      v
Deterministic fit/prerank
      |
      v
Embedding similarity
      |
      v
BGE reranker on top-k survivors
      |
      v
Phi-4-mini specialist judgment
      |
      v
fit score + reasons + confidence
```

Pure keyword scoring is insufficient for nuanced semantic relevance, so it remains a cheap floor/ranking layer rather than the sole judge.

## 14.4 Tailoring

Cover letters are generated by `qwen3.5:4b` from verified candidate facts.

The model may transform or emphasize facts but must not invent:

```text
employment
education
salary
years of professional experience
production claims
clients
technologies not supported by the resume/project evidence
```

The final output should remain short enough for reliable browser entry and should not mention private/internal coding agents.

## 14.5 ATS screening questions

Text questions are handled as a separate reasoning task from browser action selection.

Architecture:

```text
question text
  + candidate fact set
  + role context
        |
        v
qwen3.5:4b
        |
        v
fact validator
        |
        v
answer
```

Phi-4-mini may handle a bounded classification/answering task when implementation benchmarks establish that it is faster without materially reducing truthfulness or answer quality.

The browser layer should not invent an answer simply because a field exists.

---

# 15. Application Verification and Evidence

The goal is not “clicked Submit.”

The goal is **truthful confirmed application state**.

## 15.1 Confirmation hierarchy

Evidence should be strongest when multiple signals agree:

```text
1. Explicit ATS/application confirmation state
2. Durable confirmation URL/page/message
3. Account/application-history confirmation
4. Confirmation email where supported
5. Screenshot/page evidence
6. Browser/network signals as supporting evidence
```

A click without confirmation is not a confirmed submission.

## 15.2 Submission states

### `submitted`

Use only when sufficient evidence exists.

Counts toward the 100/day confirmed target.

### `submission_unconfirmed`

Use when the submit action may have succeeded but confirmation is ambiguous.

Do **not** immediately replay the application.

The reconciliation path is:

```text
inspect current page
-> inspect account/application history when legitimately available
-> inspect confirmation URL/email if supported
-> determine outcome
-> only retry when evidence supports that no application was submitted
```

### `already_applied`

A confirmed prior application stops further submission to that canonical opportunity.

It does not necessarily mean the source URL should disappear from all discovery/history.

---

# 16. Failure Architecture

Failures are typed because different failures require different state transitions.

| Failure | Classification | Required behavior |
|---|---|---|
| Network timeout | Transient | Retry with bounded backoff |
| Ollama unavailable | Infrastructure | Deterministic fallback / defer generation; do not crash worker |
| `form_changed` | Recoverable | Re-inspect structured state; bounded retry |
| Field unexpected | Recoverable | Re-read DOM/ARIA state; do not blindly reuse old selector |
| Login/session expired | Channel | Pause/re-auth path; protect opportunity state |
| Aggregator account wall | Channel | Resolve direct route if known; otherwise channel unsupported |
| CAPTCHA | Security block | Stop that route; no bypass |
| Turnstile/Cloudflare challenge | Security block | Stop that route; no bypass |
| Rate limit | Channel health | Back off and pause channel |
| Browser crash | Infrastructure | Restart browser; recover DB state normally |
| SQLite busy | Infrastructure | Short retry/backoff; preserve transaction discipline |
| DB corruption | Critical | Stop worker; recover from verified backup/snapshot |
| Submission ambiguous | Safety/ambiguity | Reconcile before any duplicate retry |
| >21 days | Terminal policy | Expire; never queue for automatic application |

---

# 17. SQLite Concurrency and Persistence Model

SQLite is retained because the target workload is local, single-host, and strongly stateful.

## 17.1 Transaction model

For a job claim:

```text
BEGIN IMMEDIATE
    select highest-priority claimable opportunity
    mark lease / application state
COMMIT
```

The transaction should be as short as possible.

Do not hold SQLite write locks while a browser is operating.

The browser work occurs **after** the claim transaction commits.

## 17.2 Lease model

An application worker must write enough information to recover from process death:

```text
claimed_at
lease_until
attempt_id
worker_id
last_attempt_at
```

On startup:

```text
find expired leases
-> classify by known outcome
-> recover safely
```

An expired lease is not automatically a safe retry when submission may have occurred.

If recovery detects that the attempt reached a submit-triggered or post-submit-uncertain phase, the opportunity must enter reconciliation / `submission_unconfirmed` handling rather than being blindly returned to `READY`.

## 17.3 WAL

WAL remains enabled. It provides the desired reader/writer concurrency for the local workload while preserving durable transaction semantics. SQLite still permits only one active writer in ordinary WAL operation, which fits the architecture's bounded write concurrency. citeturn393058search0

## 17.4 Backups

Periodic SQLite backups remain valuable for disaster recovery.

They are not checkpoints to rewind state after every browser crash.

A backup is a snapshot/recovery artifact; normal process/browser failure should rely on transactional state and leases. SQLite's Online Backup API is explicitly intended for producing consistent database snapshots. citeturn393058search1turn393058search6

---

# 18. Caching Policy

Caching must be selective.

## 18.1 Allowed cache

Useful cache targets include safe discovery reads:

```text
public job-search GETs
source responses
normalized observations
static metadata
```

## 18.2 Forbidden assumption

Hermes must not treat an HTTP cache as a universal replay system for application submissions.

Application requests are stateful browser interactions. A cached POST cannot be blindly replayed after a crash without risking duplicate submission.

Therefore the system persists **application state and evidence**, not a generic replayable network transcript.

---

# 19. Continuous Worker Architecture

The service becomes continuously running rather than timer-driven.

Conceptual loop:

```text
START
 |
 v
RECOVER STATE
 |
 v
DISCOVER / REFRESH
 |
 v
UPDATE RESERVE
 |
 v
HARD ELIGIBILITY
 |
 v
RANK / SCORE AS NEEDED
 |
 v
SELECT BY AGE CASCADE
 |
 v
TAILOR JUST-IN-TIME
 |
 v
RESOLVE CHANNEL
 |
 v
BROWSER APPLY
 |
 v
VERIFY EVIDENCE
 |
 v
RECORD ATTEMPT + OUTCOME
 |
 v
HEALTH CHECK / MAINTENANCE
 |
 `------> REPEAT
```

## 19.1 Just-in-time tailoring

Tailoring should occur close to application time rather than generating thousands of letters prematurely.

Benefits:

```text
less wasted model work
less stale content
smaller memory pressure
better alignment with the current opportunity
```

## 19.2 Daily target accounting

Daily quota counts **confirmed new submissions only**.

```text
submitted_with_valid_evidence -> +1
already_applied               -> +0
submission_unconfirmed        -> +0
failed                        -> +0
blocked                       -> +0
```

This preserves the truthfulness of the 100/day metric.

---

# 20. Observability and Control Plane

The worker must expose enough state to answer, at any moment:

```text
How much supply exists?
How much is eligible?
How much is ready?
How old is the supply?
How many applications were attempted?
How many were confirmed?
Which channels are healthy?
Where are failures concentrated?
Is the browser leaking memory?
Is Ollama available?
Is the database healthy?
```

Minimum metrics:

```text
open_reserve
eligible_reserve
ready_reserve
age_band_depth[0..3]
core_count
stretch_count
applications_confirmed_today
applications_attempted_today
confirmation_rate
submission_unconfirmed_count
retryable_failure_count
manual_review_count
channel_health
form_changed_rate
antibot_block_count
captcha_block_count
browser_restart_count
browser_crash_count
process_RSS
LLM latency by task
LLM failure rate
DB busy/retry count
source freshness
```

The important distinction is between:

```text
SUPPLY FAILURE
vs
DECISION FAILURE
vs
BROWSER FAILURE
vs
CHANNEL FAILURE
vs
CONFIRMATION FAILURE
```

The system should no longer hide all five inside one pipeline status.

---

# 21. Deployment Model

## 21.1 Legacy timers

The old scheduled batch architecture is not the production execution model.

The final production model is:

```text
hermes-continuous.service
    -> enabled
    -> restart on process failure
    -> one controlled worker
    -> systemd/cgroup containment
```

Legacy timers may remain available for diagnostic/maintenance jobs, but they must not be the main application engine.

## 21.2 Resource containment

Arch Linux is the deployment baseline.

Systemd/cgroup controls may be used to bound the Hermes service and its child browser processes so runaway memory/CPU use cannot consume the entire laptop.

The architecture requires **resource containment**, but does not freeze an arbitrary fixed memory number such as 800 MB. Exact CPU/memory limits, browser subprocess policy, and OOM behavior are tuning/verification parameters derived from measured RSS.

## 21.3 Startup behavior

On startup:

```text
1. verify DB integrity/access
2. recover expired leases
3. verify model availability
4. verify browser/session health
5. refresh source observations
6. compute reserve
7. enter continuous loop
```

## 21.4 Shutdown behavior

A controlled shutdown must:

```text
stop taking new claims
finish or safely close current browser action
commit final state
close browser
close DB connection
```

Forced termination relies on lease recovery rather than assuming a clean shutdown.

---

# 22. Security and Truthfulness Boundary

Hermes is a job application automation system, not a security-evasion system.

The following are explicitly outside architecture scope:

```text
CAPTCHA solving/bypass
Turnstile bypass
Cloudflare evasion
fingerprint spoofing intended to defeat detection
fake identity
fake work history
fake education
fake salary claims
fake years of professional experience
mass fake accounts
fabricated application confirmations
blind duplicate re-submission
```

Human-like pacing is allowed as an operational rate-control mechanism, but it must not be combined with security-evasion techniques.

The system's purpose is to **automate legitimate applications faster and more reliably**, not to defeat website security controls.

---

# 23. Architecture Rejections — Final Decisions

The following proposals were specifically considered and are **not part of the final architecture**.

| Proposal | Final decision | Reason |
|---|---|---|
| WFQ with eight peer queues | **Rejected** | Conflicts with strict fresh-first age cascade and adds unnecessary scheduler complexity |
| >21-day application queue | **Rejected** | Violates the fixed 21-day application horizon |
| Retry/recovery/manual as age-priority tiers | **Rejected** | These are state overlays, not opportunity age |
| `SELECT ... FOR UPDATE` in SQLite | **Rejected** | Not SQLite's transaction model; use transaction-based atomic claim with `BEGIN IMMEDIATE` |
| Restore DB to last checkpoint after browser crash | **Rejected** | Browser crash should not rewind unrelated durable application state |
| Generic HTTP replay cache for application POSTs | **Rejected** | Risks duplicate submissions and stale/invalid replays |
| Incognito context for every job | **Rejected** | Conflicts with persistent authenticated sessions for supported boards |
| Blind CSS/JS blocking | **Rejected** | Modern SPAs depend on JS and sometimes layout/CSS for functional interaction |
| Hard browser restart exactly every 100 renders/60 min | **Rejected as invariant** | Restart should be adaptive; those can be tuning values |
| Score threshold as permanent terminal gate | **Rejected** | Creates dead-letter inventory and prevents adaptive reranking |
| Company+title alone as universal dedupe key | **Rejected** | Can merge legitimately distinct postings |
| LLM with unrestricted browser authority | **Rejected** | Actions must pass deterministic state/policy validation |
| Laya/browser-agent model in the base architecture | **Rejected / deferred** | Deterministic structured-state control is sufficient for the frozen baseline; extra browser-model complexity was not justified by the completed research |
| Security/evasion tooling | **Rejected** | Outside system purpose and safety boundary |

---

# 24. Final Reference Architecture by Layer

```text
+------------------------------------------------------------------+
|                        HERMES CONTROL PLANE                      |
|                                                                  |
| Daily quota | metrics | worker lifecycle | maintenance          |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                       OPPORTUNITY DOMAIN                         |
|                                                                  |
| opportunities | source_observations | age | open state           |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                     ELIGIBILITY + FIT                            |
|                                                                  |
| hard gates | embeddings | specialist SLM | core/stretch          |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                   STRICT AGE-CASCADE SCHEDULER                   |
|                                                                  |
| 0–3d -> 4–7d -> 8–14d -> 15–21d                                |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                       CHANNEL ROUTER                             |
|                                                                  |
| direct | ATS | authenticated board | channel health             |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                        BROWSER GATEWAY                           |
|                                                                  |
| structured state | CDP | Playwright | sessions | evidence       |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                       DECISION LAYER                             |
|                                                                  |
| deterministic state -> bounded action -> validator -> action    |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                     VERIFIED ATTEMPT LEDGER                      |
|                                                                  |
| submitted | already applied | unconfirmed | retry | blocked      |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                         SQLITE / WAL                             |
|                                                                  |
| canonical truth | leases | attempts | observations | backups     |
+------------------------------------------------------------------+
```

---

# 25. Architecture-to-Implementation Contract

Every implementation plan must preserve these boundaries.

The architecture defines **implementation workstreams**, not a mandatory number of files. A Master Plan may combine these workstreams, and an AI Protocol may govern all of them, without creating documentation sprawl.

## Implementation workstream 1 — Data and Opportunity Lifecycle

Must implement:

```text
canonical opportunity identity
source observations
age provenance
open-state refresh
application attempt ledger
channel state separation
migration of current 8,688-row historical database
```

No browser redesign should begin by rewriting these semantics incorrectly.

## Implementation workstream 2 — Discovery and Reserve

Must implement:

```text
HTTP/API-first discovery where legitimately available
no URL tombstones except canonical application-history protection
continuous source refresh
actionable reserve metrics
300 ready-reserve target
re-evaluation of prior filtered/skipped opportunities
21-day expiration
bounded refill backoff / source health protection
```

## Implementation workstream 3 — Scheduler and Pipeline

Must implement:

```text
strict age cascade
fresh job preemption on next claim
retry overlays
just-in-time tailoring
70/30 core/stretch preference without age inversion
atomic leases
continuous worker
```

## Implementation workstream 4 — Browser Gateway / CDP

Must implement:

```text
BrowserGateway
PlaywrightAdapter
CDPAdapter
structured page state
AX/DOM/frame/shadow-root inspection
SPA readiness
validated action execution
persistent authenticated profiles
isolated public contexts
adaptive browser lifecycle
no required browser-agent LLM
```

## Implementation workstream 5 — Local AI Runtime

Must implement:

```text
four-model baseline set
model router
Nomic embedding path
BGE reranking path
Phi-4-mini scoring/classification path
Qwen3.5-4B tailoring/screening path
memory-aware residency
local benchmark harness
fact validation
```

## Implementation workstream 6 — Application Reliability

Must implement:

```text
channel health
attempt classification
submission evidence
unconfirmed reconciliation
submit-phase crash recovery
form-change recovery
security-block handling
rate-limit handling
channel cooldown/circuit breaking
```

## Implementation workstream 7 — Continuous Deployment / Validation

Must implement:

```text
systemd service
cgroup/resource containment
legacy timer demotion
startup recovery
health monitoring
metrics
backup/restore drills
24/7 soak testing
load/throughput validation
```

These workstreams are implementation plans beneath this architecture. They are not allowed to redefine its core decisions silently.

A full dashboard is **not** a prerequisite for implementing the engine. Policy values should be configuration-backed and observable; a UI can be built later without changing the architecture.

---

# 26. Final Acceptance Criteria

The redesign is architecturally complete only when all of the following are true.

### Identity and supply

```text
[ ] Previously seen URL can reappear as an updated observation.
[ ] Canonical opportunity identity survives URL changes.
[ ] Confirmed prior submissions prevent duplicate applications.
[ ] Historical filtered/scored/skipped rows no longer poison reserve.
[ ] Opportunities older than 21 days cannot enter automatic application.
```

### Scheduling

```text
[ ] 0–3d is always checked before 4–7d.
[ ] 4–7d is checked before 8–14d.
[ ] 8–14d is checked before 15–21d.
[ ] A new fresh opportunity can preempt an older candidate at the next claim.
[ ] Retry state does not create a separate age queue.
```

### Database

```text
[ ] Claims are atomic.
[ ] No SELECT FOR UPDATE is used.
[ ] Browser actions do not hold DB write locks.
[ ] Expired leases can be recovered.
[ ] Browser crashes do not trigger arbitrary DB rollback.
[ ] Verified backups can restore the system after genuine DB failure.
```

### Browser

```text
[ ] Existing proven flows remain usable during migration.
[ ] CDP structured state is available.
[ ] SPA readiness does not depend on a single networkIdle signal.
[ ] Frames and supported shadow DOM structures are inspectable.
[ ] Actions pass deterministic validation.
[ ] CAPTCHA/Turnstile/antibot states stop safely.
[ ] Authenticated profiles survive between runs where required.
```

### AI

```text
[ ] Embedding is separate from generation.
[ ] Only one primary generation specialist is normally resident.
[ ] Scoring does not create permanent dead-letter inventory.
[ ] Tailoring is fact-validated.
[ ] Browser actions are bounded and deterministically validated.
[ ] The four-model baseline is locally benchmarked for latency/resource settings before production.
```

### Application truth

```text
[ ] Confirmed submission requires evidence.
[ ] Already-applied does not count as a new submission.
[ ] Unconfirmed submission is never blindly replayed.
[ ] Every application execution has an attempt record.
[ ] Channel failures are separable from opportunity validity.
```

### Operations

```text
[ ] Continuous worker is the production engine.
[ ] Reserve is actionable rather than status-count based.
[ ] 100/day is measured as confirmed applications, not clicks/attempts.
[ ] The system exposes supply, throughput, failure, channel and memory metrics.
```

---

# 27. What This Architecture Guarantees vs What It Does Not

## It guarantees architecturally

- No permanent URL-tombstone discovery design.
- No permanent sub-threshold scoring dead zone.
- No >21-day automatic application pool.
- Fresh-first scheduling semantics.
- Durable application attempt history.
- Evidence-based confirmation semantics.
- No reliance on `SELECT FOR UPDATE`.
- No database rewind on ordinary browser crash.
- Browser security challenges are blocked rather than bypassed.
- Browser automation is abstracted from the rest of the application.
- Public discovery may use HTTP/API-first retrieval where legitimately available.
- Local model roles are separated from browser execution.
- No browser-agent LLM is required by the frozen baseline.
- The continuous worker can replenish its own actionable supply without unbounded refill spinning.
- Deployment can use systemd/cgroup containment without freezing arbitrary resource limits.

## It does not guarantee by architecture alone

- 100 confirmed applications every calendar day regardless of job supply.
- Any specific ATS remaining unchanged.
- Any specific LLM quality/latency without local benchmarking.
- Any specific browser memory consumption.
- Successful operation during source/channel outages when no legitimate route exists.
- Successful applications on channels protected by CAPTCHA/Turnstile/security controls.
- A fixed confirmation rate across all sources.

Those are **verification outcomes**, not architectural assumptions.

---

# 28. Final Architecture Decision

Hermes' final architecture is therefore:

```text
SOURCE FAN-IN
    -> CANONICAL OPPORTUNITY
    -> CURRENT OBSERVED STATE
    -> HARD ELIGIBILITY
    -> SEMANTIC FIT/RERANK
    -> STRICT AGE CASCADE
    -> CHANNEL ROUTER
    -> BROWSER GATEWAY
    -> STRUCTURED STATE
    -> BOUNDED DETERMINISTIC ACTION
    -> DETERMINISTIC VALIDATOR
    -> BROWSER ACTION
    -> VERIFIED APPLICATION ATTEMPT
    -> EVIDENCE + STATE
    -> CONTINUOUS FEEDBACK LOOP
```

The architectural center of gravity is **not CDP, SQLite, Ollama, or any individual model**.

The center of gravity is the **canonical opportunity lifecycle plus continuous state-driven scheduling and verified application execution**.

CDP, Playwright, Ollama, Nomic, BGE reranking, SQLite/WAL, ATS adapters, and source adapters are replaceable implementation components behind those contracts.

This is the final baseline for the Hermes overhaul.

**Implementation documents must now work downward from this architecture, not sideways into another redesign.**

---

## 29. Evidence Basis and Technical Verification Notes

Primary source basis for the architectural reconciliation:

- Latest Hermes repository/audit truth state and implementation evidence from the current project context.
- Qwen deep-research redesign report supplied for this review (`The Hermes Overhaul: A Blueprint for a 100-Application Daily Pipeline on 16GB RAM Hardware`).
- SQLite transaction/WAL/backup documentation reviewed while finalizing this baseline. SQLite documents `BEGIN IMMEDIATE` as an immediate write transaction; WAL permits concurrent readers with a writer but still serializes writers; the Online Backup API provides consistent database snapshots. citeturn138076search3turn393058search0turn393058search1
- Playwright BrowserContext documentation reviewed for persistent-vs-isolated session semantics. citeturn138076search0
- Chrome DevTools Protocol Accessibility documentation reviewed for structured AX-tree state. citeturn138076search2
- Ollama model registry reviewed for the frozen Qwen3.5-4B, Phi-4-mini, and Nomic embedding packages. citeturn821580search1turn821580search0turn578528search0
- Microsoft Phi-4-mini model card reviewed for the local 3.8B instruct model and license/runtime characteristics. citeturn578528search1
- BGE reranker documentation reviewed for the two-stage embedding + cross-encoder reranking pattern. citeturn578528search7turn578528search11
- Qwen3.5-4B model card reviewed for the current local multimodal 4B checkpoint. citeturn578528search3
- Model selection remains benchmark-gated for quantization, latency, context, and RSS; published package sizes should not be substituted for measured Ollama/Linux/Chrome RSS on the target laptop.

**Revision status:** Final frozen baseline — 2026-09-27  
**Freeze rule:** This architecture is now the parent specification for all subsequent Hermes implementation/planning documents. No further architecture redesign is expected during the implementation phase; any genuine architectural deviation requires an explicit architecture-change decision rather than an informal modification inside a downstream report.
