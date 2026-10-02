# Hermes — Data Model

**Document ID:** \`HERMES-DATA-MODEL-2026-09-27\`  
**Status:** ACTIVE IMPLEMENTATION SPECIFICATION  
**Document:** 3/8  
**Parent:** \`ARCHITECTURE_REDESIGN_FINAL-2026-09-27-FROZEN.md\` + \`MASTER_PLAN.md\` + \`SYSTEM_RULES.md\`  
**Repository:** \`saralbanker/hermes\`  
**Baseline branch:** \`overhaul-2026-09-23\`

> **Purpose:** Define the durable data semantics, ownership boundaries, relationships, invariants, indexes, migration shape, and persistence contracts required by the frozen Hermes architecture.
>
> This document adds data-level implementation detail. It does **not** redefine the frozen architecture, scheduler, browser architecture, or AI architecture.

---

# 1. Data-Model Objective

Hermes must move from one overloaded \`jobs\` record to a small set of durable entities with distinct meanings.

The target model is:

\`\`\`text
                         +----------------------+
                         |      OPPORTUNITIES    |
                         | canonical job truth   |
                         +----------+-----------+
                                    |
                  +-----------------+-----------------+
                  |                                   |
                  v                                   v
       +----------------------+             +----------------------+
       | SOURCE_OBSERVATIONS  |             | APPLICATION_ATTEMPTS |
       | what sources report  |             | what Hermes actually |
       | and when             |             | attempted            |
       +----------------------+             +----------+-----------+
                                                       |
                                                       v
                                            +----------------------+
                                            | EVIDENCE / OUTCOME   |
                                            | submission truth     |
                                            +----------------------+

       +----------------------+             +----------------------+
       |    CHANNEL_HEALTH    |             |      RESPONSES       |
       | route health         |             | employer messages    |
       +----------------------+             +----------------------+

       +----------------------+
       |     WORK_QUEUE       |
       | derived scheduling  |
       | projection           |
       +----------------------+
\`\`\`

The central rule is:

\`\`\`text
One canonical opportunity
≠ one URL
≠ one source observation
≠ one application attempt
≠ one channel
≠ one employer response
\`\`\`

---

# 2. Data Ownership Principles

Every persistent fact must have one owning entity.

| Fact | Owner |
|---|---|
| Canonical identity of a role | \`opportunities\` |
| Source-specific URL / posting ID | \`source_observations\` |
| Source-reported posting time | \`source_observations\` |
| Current inferred open state | \`opportunities\` |
| Age basis / age band | \`opportunities\` |
| Deterministic eligibility decision | \`opportunities\` + evaluation history |
| Current fit/ranking result | \`opportunities\` + evaluation history |
| Application execution attempt | \`application_attempts\` |
| Submit evidence | \`application_attempts\` |
| Channel operational health | \`channel_health\` |
| Employer email/response | \`responses\` |
| Daily application counts | \`daily_limits\` / quota projection |
| Derived schedulable work | \`work_queue\` |
| Candidate facts | \`profile/facts.md\` outside the application DB |

No entity may silently become the owner of another entity's truth merely because it is convenient.

---

# 3. System of Record

SQLite remains the authoritative persistent store.

\`\`\`text
Database:
    db/applications.db

Journal mode:
    WAL

Foreign keys:
    ON
\`\`\`

## 3.1 Schema Version

The database tracks its own schema generation using SQLite's built-in \`PRAGMA user_version\`.

\`\`\`text
PRAGMA user_version = <integer schema generation>
\`\`\`

Every schema migration step (Section 24) increments this value as part of the same migration transaction that applies the corresponding structural change.

Before any write path runs, the worker must read \`PRAGMA user_version\` and refuse to start if it does not match the schema generation the running code expects. This is a compatibility check using an existing SQLite mechanism, not a new persistence mechanism; no additional table is introduced.

\`PRAGMA user_version\` versions exactly one axis: the structural shape of this database (tables/columns/indexes). It is independent of, and must never substitute for:

\`\`\`text
identity_version      -- canonical-identity algorithm generation (§5.3/§5.4, opportunities row)
policy_version         -- eligibility/scoring policy generation (§10.2, evaluation_history row)
model_version          -- AI model identifier/generation (§10.2, evaluation_history row; AI_SYSTEM.md §25)
prompt/output-schema version  -- AI prompt + structured-output-schema generation (recorded in evaluation_history.metadata, §10.2; AI_SYSTEM.md §25)
\`\`\`

A mismatch on any one of these axes does not imply a mismatch on another: a database schema upgrade does not require re-scoring existing evaluations, and a model/prompt change does not require a database migration. Each axis is read and compared independently by the subsystem that owns it.

The database must persist enough state to reconstruct the actionable system after process death.

A derived queue may be rebuilt.

A model cache may be regenerated.

Browser state may be restarted.

Canonical opportunity, application attempt, outcome, and evidence history must not depend on volatile process memory.

---

# 4. Required Entity Set

The target model contains these logical entities:

\`\`\`text
opportunities
source_observations
application_attempts
channel_health
work_queue
responses
daily_limits
evaluation_history
\`\`\`

\`evaluation_history\` is included because filtering/ranking decisions are historical evidence rather than canonical identity. An implementation may initially embed some evaluation history in an existing audit/event structure, but the semantic requirement remains: historical decisions must not become the only source of current opportunity truth.

---

# 5. \`opportunities\`

## 5.1 Purpose

\`opportunities\` represents the canonical job opportunity itself.

It survives source URL changes, source changes, and repeated observations.

It is the principal entity used by eligibility, ranking, scheduling, and application history.

## 5.2 Conceptual schema

\`\`\`text
opportunity_id              INTEGER PRIMARY KEY
canonical_key               TEXT UNIQUE NOT NULL
identity_version            INTEGER NOT NULL
company_normalized          TEXT NOT NULL
company_display             TEXT
company_domain              TEXT
job_title_normalized        TEXT NOT NULL
job_title_display           TEXT
location_normalized         TEXT
location_display            TEXT
employment_type             TEXT
work_mode                   TEXT
salary_min                  INTEGER
salary_max                  INTEGER
salary_currency             TEXT
salary_basis                TEXT
first_seen_at               DATETIME NOT NULL
first_posted_at             DATETIME
last_observed_at            DATETIME NOT NULL
last_verified_open_at       DATETIME
current_open_state          TEXT NOT NULL
age_basis                   TEXT NOT NULL
age_reference_at            DATETIME NOT NULL
age_band                    TEXT
hard_eligibility_state      TEXT NOT NULL
hard_eligibility_reason     TEXT
fit_state                   TEXT
fit_score                   REAL
fit_confidence              REAL
fit_reasons                 TEXT
core_or_stretch             TEXT
application_state           TEXT NOT NULL
current_attempt_id          INTEGER REFERENCES application_attempts
terminal_reason             TEXT
selected_resume_variant     TEXT
current_cover_letter_ref    TEXT
latest_description_hash     TEXT
latest_application_route    TEXT
created_at                  DATETIME NOT NULL
updated_at                  DATETIME NOT NULL
\`\`\`

The actual implementation may normalize some of these values into reference tables, but it must not collapse the semantics.

## 5.3 Identity fields

\`opportunity_id\` is an internal immutable database identifier.

\`canonical_key\` is the durable identity key used for cross-source identity resolution.

\`identity_version\` allows the identity algorithm to evolve without silently changing the meaning of old records.

The canonical identity hierarchy is:

\`\`\`text
1. reliable source-specific job ID
2. reliable ATS/company posting ID
3. normalized composite identity
\`\`\`

The fallback composite must include enough discriminating information to avoid obvious false merges. At minimum:

\`\`\`text
normalized company
+ normalized title
+ normalized location
+ relevant employment/posting discriminator
\`\`\`

Company + title alone is not sufficient as the universal canonical key.

## 5.4 Identity invariants

\`\`\`text
canonical_key is unique
opportunity_id never changes
canonical identity does not equal source URL
source URLs may change without creating a new opportunity
multiple source observations may reference one opportunity
\`\`\`

A canonical identity should not be created from an unstable tracking URL.

Tracking parameters must not cause a new canonical opportunity when the underlying posting is the same.

## 5.5 Open-state semantics

\`current_open_state\` represents the best current system understanding of whether the opportunity remains actionable from the available observations.

Possible conceptual values:

\`\`\`text
OPEN
CLOSED
UNKNOWN
EXPIRED
\`\`\`

\`UNKNOWN\` is not the same as \`CLOSED\`.

A source disappearing must not automatically prove that a role is closed.

An explicit source close signal is stronger evidence of closure.

## 5.6 Age semantics

\`age_basis\` records why Hermes believes the opportunity has a particular age.

Allowed conceptual precedence:

\`\`\`text
VERIFIED_POSTED_AT
SOURCE_PUBLICATION_TIMESTAMP
FIRST_SEEN_AT_FALLBACK
\`\`\`

\`age_reference_at\` stores the timestamp used by the age calculation.

\`age_band\` is a derived policy field:

\`\`\`text
0_3D
4_7D
8_14D
15_21D
EXPIRED
\`\`\`

At \`>21 days\`, the opportunity may retain its historical record but must not re-enter the automatic application queue.

## 5.7 Eligibility semantics

\`hard_eligibility_state\` must distinguish at least:

\`\`\`text
UNKNOWN
ELIGIBLE
INELIGIBLE
\`\`\`

The state is deterministic and derives from documented policy inputs.

The reason must be explainable, for example:

\`\`\`text
GEO_OUTSIDE_RADIUS
SALARY_BELOW_FLOOR
ROLE_EXCLUDED
EXPERIENCE_GAP
AGE_EXPIRED
NO_SUPPORTED_ROUTE
SECURITY_BLOCK
ALREADY_APPLIED
\`\`\`

Missing evidence must not silently become a false known value.

## 5.8 Fit semantics

\`fit_score\` is a ranking value, not a permanent lifecycle gate.

\`fit_state\` should distinguish whether a current fit result exists, for example:

\`\`\`text
NOT_EVALUATED
EVALUATED
STALE
FAILED
\`\`\`

A low historical score does not make the opportunity a permanent tombstone.

## 5.9 Application state

\`application_state\` describes the opportunity's current position in the processing lifecycle — the dimension WORKFLOW_ENGINE.md §4 calls "opportunity processing state." It is deliberately narrow.

It must **not** be used to store:

\`\`\`text
raw browser errors
source-specific observation state
application outcome (owned by application_attempts.outcome)
channel operational health (owned by channel_health.status)
\`\`\`

The authoritative value set — identical to WORKFLOW_ENGINE.md §4 and IMPLEMENTATION_ROADMAP.md §34 — is:

\`\`\`text
OBSERVED
EVALUATING
READY
APPLYING
AWAITING_RECONCILIATION
COMPLETED
EXPIRED
MANUAL_REVIEW
\`\`\`

Mapping notes:

\`\`\`text
a confirmed submission or a confirmed prior application
    → opportunity moves to COMPLETED
    (application_attempts.outcome distinguishes SUBMITTED vs ALREADY_APPLIED)

an ambiguous submit
    → opportunity moves to AWAITING_RECONCILIATION
    (application_attempts.outcome = SUBMISSION_UNCONFIRMED)

a retryable failure
    → opportunity returns to READY
    (retry timing lives in work_queue.next_attempt_at, not in this field)

a channel block or unsupported route
    → opportunity remains READY, EXPIRED, or MANUAL_REVIEW depending on whether
      another legitimate route exists
    (application_attempts.outcome and channel_health.status carry the detail)
\`\`\`

This field carries no attempt-outcome or channel-health literal. Those dimensions are never collapsed into it, consistent with ARCHITECTURE_REDESIGN_FINAL.md §5.1 ("These states must not be collapsed into a single overloaded status field...").

Exact workflow transitions are owned by Doc 4 (\`WORKFLOW_ENGINE.md\`); this document defines the data meaning only.

---

# 6. \`source_observations\`

## 6.1 Purpose

\`source_observations\` stores what an individual source reported about a canonical opportunity at a particular observation time.

The same opportunity may have many observations from one source or multiple sources.

## 6.2 Conceptual schema

\`\`\`text
observation_id              INTEGER PRIMARY KEY
opportunity_id              INTEGER NOT NULL REFERENCES opportunities
source_name                 TEXT NOT NULL
source_job_id               TEXT
source_url                  TEXT
apply_url                   TEXT
observed_at                 DATETIME NOT NULL
posted_at                   DATETIME
open_state                  TEXT
company_raw                 TEXT
title_raw                   TEXT
location_raw                TEXT
employment_type_raw         TEXT
work_mode_raw               TEXT
salary_min_raw              TEXT
salary_max_raw              TEXT
salary_currency_raw         TEXT
description_hash            TEXT
description_ref             TEXT
raw_metadata                TEXT
observation_status          TEXT NOT NULL
failure_reason              TEXT
created_at                  DATETIME NOT NULL
\`\`\`

## 6.3 Observation identity

The observation identity is source-scoped.

Preferred stable key:

\`\`\`text
source_name + source_job_id
\`\`\`

When a source does not expose a stable job ID, the implementation may use an appropriate source-scoped normalized locator plus observation history.

A source observation key must never be treated as the canonical opportunity identity.

## 6.4 Observation states

Conceptual values:

\`\`\`text
ACTIVE
STALE
CLOSED
INVALID
FETCH_FAILED
\`\`\`

A failed refresh is not the same as a confirmed closed posting.

## 6.5 Re-observation rule

When Hermes encounters a previously known role:

\`\`\`text
resolve canonical opportunity
→ append/update source observation
→ refresh current open state
→ refresh relevant evidence
→ re-evaluate current policy
\`\`\`

The old behavior:

\`\`\`text
URL already in DB → discard forever
\`\`\`

is forbidden.

---

# 7. \`application_attempts\`

## 7.1 Purpose

\`application_attempts\` records what Hermes actually attempted to do.

It is the authoritative history for execution and recovery.

One opportunity may have multiple attempts.

One attempt belongs to exactly one canonical opportunity and one resolved application channel.

## 7.2 Conceptual schema

\`\`\`text
attempt_id                  INTEGER PRIMARY KEY
opportunity_id              INTEGER NOT NULL REFERENCES opportunities
channel                     TEXT NOT NULL
attempt_number              INTEGER NOT NULL
worker_id                   TEXT
claimed_at                  DATETIME NOT NULL
lease_until                 DATETIME
started_at                  DATETIME
finished_at                 DATETIME
attempt_state               TEXT NOT NULL
execution_phase              TEXT NOT NULL DEFAULT 'NOT_STARTED'
outcome                     TEXT
error_code                  TEXT
error_class                 TEXT
retry_eligible              INTEGER NOT NULL DEFAULT 0
resolved_apply_url          TEXT
confirmation_url            TEXT
confirmation_text           TEXT
authenticated_session_ref   TEXT
evidence_json               TEXT
screenshot_ref              TEXT
email_evidence_ref          TEXT
browser_signals             TEXT
network_signals             TEXT
request_trace_ref           TEXT
notes                       TEXT
created_at                  DATETIME NOT NULL
updated_at                  DATETIME NOT NULL
\`\`\`

## 7.3 Attempt number

\`attempt_number\` is monotonically increasing for the canonical opportunity/application history.

The current policy maximum is:

\`\`\`text
MAX_ATTEMPTS = 3
\`\`\`

The database must not allow ordinary application logic to create an unbounded retry loop.

## 7.4 Attempt lifecycle

Conceptually:

\`\`\`text
CLAIMED
→ STARTED
→ FINISHED
\`\`\`

Outcome then classifies the attempt:

\`\`\`text
SUBMITTED
ALREADY_APPLIED
SUBMISSION_UNCONFIRMED
RETRYABLE_FAILURE
CHANNEL_BLOCKED
UNSUPPORTED_CHANNEL
TERMINAL_FAILURE
\`\`\`

\`application_attempts.retry_eligible\` (§7.2) is the attempt-level classification of that outcome, set once when the attempt finishes:

\`\`\`text
owner: DATA_MODEL.md (this section)
inputs: this attempt's own outcome and error_class
exact truth condition: retry_eligible = 1 if and only if outcome/error_class falls in the "bounded retry" /
        "bounded reinspection" / "channel cooldown" rows of WORKFLOW_ENGINE.md §114 (Retry Matrix);
        0 for SUBMITTED, ALREADY_APPLIED, SUBMISSION_UNCONFIRMED (reconciliation-gated, not auto-retry),
        UNSUPPORTED_CHANNEL, and TERMINAL_FAILURE
evaluation moment: written in the same transaction that records the attempt's outcome (WORKFLOW_ENGINE.md §68)
persisted, not derived; not cacheable (single write, read-only after)
consumers: WORKFLOW_ENGINE.md §22 (Retry Eligibility) reads this attempt-level bit as its "retryable outcome"
        input; it is one input among several, not the full opportunity-level retry-eligibility predicate
\`\`\`

This bit answers "was this attempt's own result the kind that permits automatic retry" — a fact about one attempt. It is not the same question as "is this opportunity retry-eligible right now" (WORKFLOW_ENGINE.md §22), which additionally depends on attempt count, confirmed-submission history, route availability, and retry timing.

Exact workflow transition ownership belongs to Doc 4.

## 7.5 Execution phase

\`execution_phase\` is the field ARCHITECTURE_REDESIGN_FINAL.md §4.4 names but does not itself schema-define; this section is that definition, and it is the single authoritative source WORKFLOW_ENGINE.md §41-§45 and BROWSER_SYSTEM.md §70/§72 must read/write.

It exists to answer the one question crash recovery cannot answer from \`attempt_state\` (CLAIMED/STARTED/FINISHED) alone: **did external, possibly-irreversible work begin before the process died?**

\`\`\`text
NOT_STARTED             -- attempt claimed; no browser/network action toward the target site has begun
EXTERNAL_WORK_STARTED   -- browser navigation/form-fill toward the target site is in progress; the Submit control has not been invoked
SUBMIT_INTENT           -- the Submit control has been invoked; an external mutation may have occurred; this is the irreversible boundary
OBSERVED                -- post-submit observation (BROWSER_SYSTEM.md §61) has completed and evidence has been collected; \`outcome\` then classifies the result
\`\`\`

Contract:

\`\`\`text
owner: DATA_MODEL.md (this section)
inputs: browser-driver progress signal (BROWSER_SYSTEM.md §70's external_work_started marker maps to
        NOT_STARTED -> EXTERNAL_WORK_STARTED; BROWSER_SYSTEM.md §72's "submit-stage marker" maps to
        EXTERNAL_WORK_STARTED -> SUBMIT_INTENT); post-submit observation completion maps to
        SUBMIT_INTENT -> OBSERVED
exact truth condition: monotonic forward-only progression through the four values above; set by the
        same transaction/write that performs the corresponding browser action, never inferred after the fact
evaluation moment: written synchronously as the browser layer crosses each boundary, not batch-recomputed
persisted, not derived: yes -- this is precisely the field lease recovery needs to survive process death
cacheable: no
consumers: WORKFLOW_ENGINE.md §41-§45 (crash classification), §103-§105 (late-result fencing)
\`\`\`

Lease-recovery classification (WORKFLOW_ENGINE.md §45) reads directly off this field:

\`\`\`text
execution_phase = NOT_STARTED             -> "No external action started"    -> release/requeue
execution_phase = EXTERNAL_WORK_STARTED   -> "Browser started, submit not reached" -> retry only when safe
execution_phase = SUBMIT_INTENT           -> "Submit may have occurred"      -> mark unconfirmed, reconcile
execution_phase = OBSERVED                -> outcome already classified; recovery defers to outcome, not phase
\`\`\`

A crash never rewrites \`execution_phase\` backward. If the process dies at \`SUBMIT_INTENT\`, that value is what recovery inspects — it is proof of "submit may have occurred" and is the concrete durable state WORKFLOW_ENGINE.md §42/§43 mean by "when evidence proves the submit phase was not reached" and "when submission may have occurred."

## 7.6 Attempt evidence

The attempt ledger must preserve evidence needed to explain an outcome.

Evidence may include:

\`\`\`text
confirmation page text
confirmation URL
application-history signal
email reference
screenshot reference
browser/network supporting signal
\`\`\`

Do not store secrets such as Gmail app passwords, session cookies, access tokens, or passwords in the attempt record.

## 7.7 Submission invariant

\`\`\`text
SUBMITTED requires sufficient evidence.
\`\`\`

An attempt returning a local success code without evidence must not promote the opportunity to confirmed submission.

---

# 8. \`channel_health\`

## 8.1 Purpose

\`channel_health\` describes the operational condition of an application route independently of opportunity validity.

Examples:

\`\`\`text
Indeed
Greenhouse
Lever
Ashby
Direct
\`\`\`

LinkedIn is permanently unsupported: Hermes must not automate LinkedIn and must not depend on LinkedIn, so no \`channel_key\` may represent it and no \`channel_health\` row may ever be created for it.

The same channel can have different health states over time.

## 8.2 Conceptual schema

\`\`\`text
channel_id                  INTEGER PRIMARY KEY
channel_key                 TEXT UNIQUE NOT NULL
scope                       TEXT NOT NULL
provider                    TEXT
status                      TEXT NOT NULL
failure_streak              INTEGER NOT NULL DEFAULT 0
success_count               INTEGER NOT NULL DEFAULT 0
blocked_count               INTEGER NOT NULL DEFAULT 0
rate_limit_count            INTEGER NOT NULL DEFAULT 0
last_success_at             DATETIME
last_failure_at             DATETIME
cooldown_until              DATETIME
last_error_class            TEXT
last_error_code             TEXT
health_reason               TEXT
capability_version          TEXT
updated_at                  DATETIME NOT NULL
\`\`\`

\`scope\` distinguishes a broad channel from a narrower route when required.

Examples:

\`\`\`text
provider: greenhouse
scope: global

provider: indeed
scope: authenticated-account
\`\`\`

The implementation should not create hundreds of duplicate channel-health rows for individual jobs.

## 8.3 Channel status examples

\`\`\`text
HEALTHY
DEGRADED
AUTH_EXPIRED
RATE_LIMITED
FORM_SCHEMA_CHANGED
ACCOUNT_WALL
ANTIBOT_BLOCKED
NETWORK_UNAVAILABLE
UNSUPPORTED
PAUSED
\`\`\`

## 8.4 Separation rule

A channel health failure must not mutate the canonical opportunity into a false invalid state unless the opportunity itself is independently invalid.

Example:

\`\`\`text
Greenhouse unhealthy
≠ job invalid
\`\`\`

---

# 9. \`work_queue\`

## 9.1 Purpose

\`work_queue\` is a derived scheduling projection.

It exists for efficient claiming; it is not canonical truth.

It may be deleted and rebuilt from canonical state.

## 9.2 Conceptual schema

\`\`\`text
queue_id                    INTEGER PRIMARY KEY
opportunity_id              INTEGER UNIQUE NOT NULL REFERENCES opportunities
ready_state                 TEXT NOT NULL
age_band                    TEXT NOT NULL
priority_score              REAL
next_attempt_at             DATETIME
lease_until                 DATETIME
candidate_channel           TEXT
queue_reason                TEXT
updated_at                  DATETIME NOT NULL
\`\`\`

## 9.3 Queue rule

A queue row exists only when the canonical opportunity is currently actionable.

Derived queue eligibility must reflect:

\`\`\`text
open/plausibly open
within 21 days
hard eligible
not confirmed submitted
not already applied
not in a live attempt
not permanently blocked across all supported channels
retry due when applicable
\`\`\`

A row can disappear from the queue without deleting the opportunity.

## 9.4 Queue rebuild

The implementation must provide a deterministic queue-rebuild operation.

Conceptually:

\`\`\`text
canonical opportunity state
+ latest evaluations
+ current channel health
+ current retry time
→ work_queue projection
\`\`\`

No durable fact may exist only in \`work_queue\`.

---

# 10. \`evaluation_history\`

## 10.1 Purpose

Evaluation history preserves why Hermes reached a decision at a specific time.

It prevents the system from confusing a historical decision with current truth.

## 10.2 Conceptual schema

\`\`\`text
evaluation_id               INTEGER PRIMARY KEY
opportunity_id              INTEGER NOT NULL REFERENCES opportunities
evaluation_type             TEXT NOT NULL
evaluated_at                DATETIME NOT NULL
policy_version              TEXT
input_hash                  TEXT
result                      TEXT
score                       REAL
confidence                  REAL
reason                      TEXT
model_name                  TEXT
model_version               TEXT
metadata                    TEXT
\`\`\`

\`metadata\` is where the prompt/output-schema version and input version AI_SYSTEM.md §25 requires retained are recorded (as structured JSON); no separate column is introduced for them, consistent with §3.1's rule that this is a distinct versioning axis from \`policy_version\`, \`model_version\`, and the database's own \`PRAGMA user_version\`.

## 10.3 Evaluation types

Examples:

\`\`\`text
HARD_ELIGIBILITY
FIT_SCORE
SEMANTIC_SIMILARITY
CORE_STRETCH_CLASSIFICATION
AGE_RECALCULATION
OPEN_STATE_REFRESH
CHANNEL_RESOLUTION
\`\`\`

An implementation may combine some evaluation types only when historical meaning remains recoverable.

## 10.4 Re-evaluation rule

Previous evaluation results remain historical evidence.

Current opportunity truth is recalculated from current observations and current policy.

Therefore:

\`\`\`text
old filtered result
≠ permanent rejection

old low score
≠ permanent dead letter
\`\`\`

---

# 11. \`responses\`

## 11.1 Purpose

\`responses\` stores employer email/message records detected by the response watcher.

It is independent from submission confirmation.

An employer email can strengthen evidence, correlate to an opportunity, or provide a later response without changing the original attempt history.

## 11.2 Conceptual schema

\`\`\`text
message_id                  TEXT PRIMARY KEY
from_addr                   TEXT
subject                     TEXT
received_at                 DATETIME
classification              TEXT
opportunity_id              INTEGER REFERENCES opportunities
attempt_id                  INTEGER REFERENCES application_attempts
job_url_observed            TEXT
notified_at                 DATETIME
notification_level          TEXT
message_hash                TEXT
correlation_reason          TEXT
raw_message_ref             TEXT
created_at                  DATETIME NOT NULL
\`\`\`

## 11.3 Response classifications

Allowed values are the four categories defined in WORKFLOW_ENGINE.md §62 and must use that exact wording, consistent with §11.6's rule for \`notification_level\`: \`screening_follow_up\`, \`human_required_signal\`, \`rejection\`, \`acknowledgement\`, \`ambiguous\`. (five values)

Classification must not be inferred from generic boilerplate alone when stronger correlation evidence exists.

## 11.4 Correlation rule

Response correlation may use:

\`\`\`text
employer/company identity
role title
known application email
ATS/provider markers
unique application identifiers
subject patterns
message timestamps
\`\`\`

A response must not be linked to an opportunity solely because it contains a generic phrase such as \`no-reply\` or \`recommended jobs\`.

## 11.5 Submission evidence relationship

A confirmation email may contribute to \`application_attempts\` evidence, but the response watcher must not retroactively fabricate an attempt that does not exist.

## 11.6 Notification level

\`notification_level\` persists the severity tier that Section 61's classification decision assigned, so an engineer is not left inventing the field or its allowed values. This is the single existing gap the notification model needs closed: no durable field previously existed anywhere in this document to hold it.

Allowed values are the four tiers defined once in WORKFLOW_ENGINE.md §61 (sourced from SYSTEM_RULES.md §31) and must use that exact wording, not a paraphrase:

\`\`\`text
Ignore
Log
Telegram Notification
High Priority Telegram Notification
\`\`\`

\`Ignore\`-tier events produce no durable record by definition (WORKFLOW_ENGINE.md §61), so \`notification_level = 'Ignore'\` should not normally appear as a persisted row; a \`responses\` row that exists at all is expected to carry \`Log\`, \`Telegram Notification\`, or \`High Priority Telegram Notification\`.

\`notification_level\` is independent from \`classification\` (§11.3): \`classification\` describes what the message is, \`notification_level\` describes what Hermes did about it. The mapping from classification to level is owned by WORKFLOW_ENGINE.md §62, not by this table.

---

# 12. \`daily_limits\`

## 12.1 Purpose

Daily quota state protects the system-wide application cap and supports accurate accounting.

## 12.2 Conceptual schema

\`\`\`text
date                        TEXT PRIMARY KEY
indeed_count                INTEGER NOT NULL DEFAULT 0
other_count                 INTEGER NOT NULL DEFAULT 0
total_count                 INTEGER NOT NULL DEFAULT 0
confirmed_count             INTEGER NOT NULL DEFAULT 0
attempt_count               INTEGER NOT NULL DEFAULT 0
updated_at                  DATETIME NOT NULL
\`\`\`

\`indeed_count\` replaces a prior \`linkedin_count\` field: LinkedIn is permanently unsupported (Hermes must not automate or depend on LinkedIn), so a per-platform counter must not exist for it. Indeed is the current Supported (Primary) platform and is therefore the per-platform counter actually needed today; \`other_count\` continues to cover every other enabled channel (e.g. Greenhouse, Lever) without naming a specific unsupported platform.

The exact fields may be normalized or extended, but the distinction between **attempts** and **confirmed submissions** must remain.

## 12.3 Counting invariant

Only confirmed new submissions, for opportunities that passed hard eligibility (DATA_MODEL.md §5.7), count toward the 100 qualified applications/day target.

\`\`\`text
confirmed new submission    +1
already applied             +0
submission unconfirmed      +0
failed                      +0
blocked                     +0
\`\`\`

Attempt counts are operational metrics, not success counts.

---

# 13. Relationships

The minimum relationship graph is:

\`\`\`text
opportunities
    1
    │
    ├──────────< source_observations
    │
    ├──────────< evaluation_history
    │
    ├──────────< application_attempts
    │                  │
    │                  └──────> channel_health
    │
    ├───────────0..1 work_queue
    │
    └──────────< responses
\`\`\`

Additional relationship:

\`\`\`text
channel_health
    1
    │
    └──────────< application_attempts
\`\`\`

\`daily_limits\` is global quota state and therefore does not belong to a single opportunity.

---

# 14. Foreign-Key Rules

Required referential behavior:

\`\`\`text
source_observations.opportunity_id
    → opportunities.opportunity_id

application_attempts.opportunity_id
    → opportunities.opportunity_id

evaluation_history.opportunity_id
    → opportunities.opportunity_id

work_queue.opportunity_id
    → opportunities.opportunity_id

responses.opportunity_id
    → opportunities.opportunity_id

responses.attempt_id
    → application_attempts.attempt_id
\`\`\`

The implementation should favor preserving historical rows rather than cascading destructive deletes.

Canonical opportunity deletion is therefore expected to be extremely rare.

When a role is no longer actionable, state should normally change rather than deleting history.

---

# 15. Uniqueness Rules

The following uniqueness constraints are required conceptually.

\`\`\`text
opportunities.canonical_key
    UNIQUE

work_queue.opportunity_id
    UNIQUE

responses.message_id
    PRIMARY KEY / UNIQUE
\`\`\`

Where reliable source IDs exist:

\`\`\`text
(source_name, source_job_id)
    UNIQUE
\`\`\`

A source without a stable ID must use a source-appropriate dedupe strategy, but it must not be promoted into global canonical identity simply because it is unique within one feed.

---

# 16. Index Strategy

Indexes should serve actual claim, refresh, and lookup paths.

Minimum logical indexes:

\`\`\`text
opportunities(canonical_key)
opportunities(current_open_state, age_band)
opportunities(hard_eligibility_state, age_band)
opportunities(application_state, age_band)
opportunities(last_observed_at)
opportunities(last_verified_open_at)
opportunities(fit_score)
opportunities(updated_at)

source_observations(opportunity_id)
source_observations(source_name, source_job_id)
source_observations(source_name, observed_at)
source_observations(source_url)

application_attempts(opportunity_id, attempt_number)
application_attempts(opportunity_id, started_at)
application_attempts(attempt_state, lease_until)
application_attempts(channel, started_at)

channel_health(channel_key)
channel_health(status, cooldown_until)

evaluation_history(opportunity_id, evaluated_at)
evaluation_history(opportunity_id, evaluation_type, evaluated_at)

work_queue(age_band, next_attempt_at)
work_queue(ready_state, age_band, priority_score)

responses(opportunity_id, received_at)
responses(classification, received_at)
\`\`\`

Exact composite index order may be benchmarked after the real query plan is implemented.

Do not create indexes merely because a field exists.

---

# 17. State-to-Data Separation

The redesign intentionally separates several kinds of state.

## 17.1 Opportunity state

Answers:

\`\`\`text
What job is this?
Is it still open?
How old is it?
Is it hard-eligible?
How well does it fit?
Has this opportunity already been applied to?
\`\`\`

Owner:

\`\`\`text
opportunities
\`\`\`

## 17.2 Observation state

Answers:

\`\`\`text
Where did Hermes see it?
What did that source report?
When did it report it?
What URL/ATS ID did it expose?
\`\`\`

Owner:

\`\`\`text
source_observations
\`\`\`

## 17.3 Execution state

Answers:

\`\`\`text
Did Hermes attempt it?
Through which channel?
When?
What happened?
What evidence exists?
Can it safely retry?
\`\`\`

Owner:

\`\`\`text
application_attempts
\`\`\`

## 17.4 Channel state

Answers:

\`\`\`text
Is this route healthy?
Is authentication valid?
Is it rate limited?
Is it blocked?
Is the schema changed?
\`\`\`

Owner:

\`\`\`text
channel_health
\`\`\`

## 17.5 Response state

Answers:

\`\`\`text
Did the employer send a message?
Was it positive/rejection/ack/other?
Which opportunity or attempt can it be correlated to?
\`\`\`

Owner:

\`\`\`text
responses
\`\`\`

---

# 18. Required Idempotency Rules

Database operations that may be retried must be idempotent or guarded by unique constraints.

Examples:

\`\`\`text
re-observing the same source posting
→ update observation, do not create duplicate canonical opportunity

processing the same email message twice
→ message_id uniqueness prevents duplicate response rows

rebuilding work_queue
→ replace/regenerate projection without creating duplicate canonical facts

re-running startup recovery
→ cannot create a second attempt for an already persisted attempt
\`\`\`

Application submission itself is **not** treated as an idempotent network operation.

Persisted application state and evidence, not replayed POSTs, provide crash safety.

---

# 19. Claim / Lease Persistence Contract

The claim operation must be durable and short.

Conceptually:

\`\`\`text
BEGIN IMMEDIATE

select one claimable opportunity

create new application_attempts row (new attempt_id, next attempt_number)
mark opportunity as APPLYING
set opportunities.current_attempt_id = new attempt_id
set lease_until

COMMIT
\`\`\`

Every retry creates a **new** \`application_attempts\` row with a new \`attempt_id\` (Section 7.3); an expired lease is never reused for a subsequent attempt.

No browser interaction occurs while the transaction is holding its write lock.

The lease must identify enough information to recover after process death:

\`\`\`text
attempt_id
worker_id
claimed_at
lease_until
\`\`\`

## 19.1 Lease Fencing Contract

\`opportunities.current_attempt_id\` (Section 5.2) is the fencing token. It is set only inside the claim transaction above, and only the attempt currently named there is authorized to mutate the opportunity's \`application_state\`.

Every write that promotes an attempt's result onto the opportunity must be conditioned on still owning the lease:

\`\`\`text
UPDATE opportunities
SET application_state = :new_state, ...
WHERE opportunity_id = :opportunity_id
  AND current_attempt_id = :attempt_id
\`\`\`

If this statement affects zero rows, the writing attempt is no longer the current owner — a later attempt has already claimed the opportunity. The write must be discarded and the result routed to reconciliation (WORKFLOW_ENGINE.md §40) rather than applied. This is what "Worker Fencing" (WORKFLOW_ENGINE.md §105) means concretely: no separate token table or generation counter is introduced, and no new architecture is added. \`application_attempts.attempt_id\` already changes on every retry (Section 7.3), so a stale worker attempting to write always carries an \`attempt_id\` that no longer matches \`opportunities.current_attempt_id\`, and its write is atomically rejected by the \`WHERE\` clause above.

This closes the late-write race described in WORKFLOW_ENGINE.md §104 ("Late Success vs Retry"): attempt 1's late success report can still update its own \`application_attempts\` row (preserving evidence for reconciliation), but it can no longer overwrite \`opportunities.application_state\` once attempt 2 has claimed the lease.

The data model does not permit a browser crash to erase unrelated opportunity, observation, response, or attempt history.

---

# 20. Recovery Semantics

On worker startup:

\`\`\`text
find attempts with expired leases
        ↓
inspect attempt state/evidence
        ↓
classify safe recovery path
        ↓
reconcile ambiguous submissions
        ↓
rebuild actionable queue projection
\`\`\`

Important rule:

\`\`\`text
expired lease
≠ automatically safe retry
\`\`\`

When the submit phase may have executed, the application remains ambiguous until evidence is reconciled.

---

# 21. Submit-Phase Crash Safety

The most dangerous state boundary is:

\`\`\`text
browser submits
       ↓
process crashes
       ↓
DB never records final outcome
\`\`\`

The data model must preserve enough information before and during the attempt to distinguish:

\`\`\`text
not started
started but not submitted
submit likely executed / outcome unknown
confirmed submitted
already applied
\`\`\`

Recovery must never assume:

\`\`\`text
no DB success row
→ therefore no application happened
\`\`\`

A second submission requires evidence that the first did not succeed.

---

# 22. Evidence Storage Rules

Evidence must be durable enough to support later verification without storing unnecessary secrets.

Preferred storage pattern:

\`\`\`text
small structured evidence
→ database

large screenshot / artifact
→ filesystem or controlled artifact path

email evidence
→ response message reference + metadata
\`\`\`

The database stores references and hashes when practical rather than copying large binary payloads into every row.

Examples:

\`\`\`text
confirmation_text
confirmation_url
screenshot_ref
email message_id
hash of relevant evidence
\`\`\`

Never store browser passwords, Gmail app passwords, session cookies, or other secrets as application evidence.

---

# 23. Historical Migration from \`jobs\`

The current repository has a single \`jobs\` table containing URL identity, posting data, scoring, tailoring, application state, attempt counters, response fields, and evidence.

The redesign must migrate those semantics instead of deleting history.

## 23.1 Current fields that map cleanly

Examples:

\`\`\`text
jobs.company
jobs.title
jobs.location
jobs.description
jobs.salary_min
jobs.salary_max
jobs.date_posted
    ↓
opportunities + source_observations

jobs.score
jobs.score_reason
    ↓
opportunities current fit fields
+ evaluation_history

jobs.status
jobs.status_reason
    ↓
opportunities application/evaluation state
+ evaluation history

jobs.attempts
jobs.last_attempt_at
jobs.submission_evidence
jobs.screenshot_path
    ↓
application_attempts

jobs.response_status
jobs.response_subject
jobs.response_at
jobs.response_notified_at
    ↓
responses

jobs.apply_channel
    ↓
application route / attempt channel

jobs.ats_meta
    ↓
source observation / route metadata as appropriate
\`\`\`

The migration must not blindly copy every legacy column into every new table.

## 23.2 Legacy \`url\`

The legacy URL becomes a source observation locator.

It must not become the canonical key by default.

## 23.3 Legacy \`dedupe_key\`

The existing \`company|title\` strategy is historical evidence only.

It must not automatically become the new universal canonical key because it can merge distinct postings.

Migration must either:

\`\`\`text
validate it against stronger identity evidence
\`\`\`

or:

\`\`\`text
store it as historical dedupe metadata while generating a safer canonical identity
\`\`\`

## 23.4 Legacy filtered/scored/skipped rows

These rows must remain historical records.

They must not all become permanently ineligible canonical opportunities.

Where the underlying opportunity is still valid, migration should allow fresh observations and fresh evaluation.

## 23.5 Legacy submitted rows

Confirmed prior submissions must migrate into durable canonical application history.

These records are important because they provide duplicate protection.

A migrated submission must carry as much evidence linkage as the legacy data can support.

The migration must never upgrade an unverified historical row into \`SUBMITTED\` merely because its status string says \`submitted\` if stronger evidence contradicts it.

## 23.6 Legacy attempt rows and \`execution_phase\`

Every migrated \`application_attempts\` row must receive a value for \`execution_phase\` (§7.5) — it is \`NOT NULL\`. A legacy row that already carries a terminal \`outcome\` (\`SUBMITTED\`, \`ALREADY_APPLIED\`, \`SUBMISSION_UNCONFIRMED\`, \`RETRYABLE_FAILURE\`, \`CHANNEL_BLOCKED\`, \`UNSUPPORTED_CHANNEL\`, \`TERMINAL_FAILURE\`) backfills to \`OBSERVED\` — the outcome itself is the durable record, and \`execution_phase\` at that point only matters for in-flight recovery, which does not apply to a historical row. A legacy row with no recorded outcome and no way to determine whether external work began must **not** default to \`NOT_STARTED\` — that value asserts "safe to retry," which is exactly the unverified assumption §23.5 forbids. Such a row backfills to \`SUBMIT_INTENT\` (the conservative value: "submission may have occurred, reconcile before touching") unless migration evidence positively supports a more precise classification.

---

# 24. Migration Strategy

The migration should be staged rather than destructive.

Recommended sequence:

\`\`\`text
1. snapshot current DB
2. add new schema structures
3. backfill opportunities
4. backfill source observations
5. backfill evaluation history
6. backfill application attempts
7. backfill responses
8. initialize channel health
9. rebuild work_queue
10. run consistency checks
11. run read-only dual validation
12. switch production reads/writes by domain
13. preserve legacy fields temporarily if needed
14. remove obsolete columns only after verification
\`\`\`

The legacy \`jobs\` table should not be dropped in the first migration step.

A rollback must mean returning to a verified prior application version/database snapshot, not casually restoring after every runtime error.

---

# 25. Migration Consistency Checks

The migration must verify at minimum:

\`\`\`text
number of canonical opportunities created
number of source observations
number of confirmed historical submissions
number of ambiguous submissions
number of response records
number of opportunities with missing identity
number of opportunities with invalid age basis
number of duplicate canonical keys
number of orphaned attempts
number of orphaned responses
number of queue rows with no actionable canonical opportunity
\`\`\`

High-level invariant:

\`\`\`text
No application attempt without an opportunity
No source observation without an opportunity
No response linkage to a missing opportunity
No queue row for a permanently non-actionable opportunity
\`\`\`

---

# 26. Reserve Derivation

\`READY_RESERVE\` must be derived from canonical opportunity state, not from legacy status counts.

Conceptual predicate:

\`\`\`text
current_open_state IN (OPEN, UNKNOWN when policy allows)
AND age_band IN (0_3D, 4_7D, 8_14D, 15_21D)
AND hard_eligibility_state = ELIGIBLE
AND application_state = READY
AND no permanent all-channel block
AND retry conditions satisfied
\`\`\`

\`COMPLETED\` covers both a confirmed submission and a confirmed prior application (see §5.9); both are canonical-history-protected and must not re-enter the reserve.

\`retry conditions satisfied\` is not a separate predicate; it is exactly:

\`\`\`text
work_queue.next_attempt_at IS NULL OR work_queue.next_attempt_at <= now()
\`\`\`

i.e. either this opportunity has never failed an attempt (no retry timer set), or its backoff (WORKFLOW_ENGINE.md §23) has already elapsed. An opportunity whose retry is not yet due fails this clause and correctly does not count toward \`READY_RESERVE\` even though its \`application_state\` remains \`READY\` — it exists but is not currently claimable. This is the timing half of WORKFLOW_ENGINE.md §22's full opportunity-level retry-eligibility predicate; §22 additionally governs whether automatic retry is permitted **at all** (attempt count, route availability). An opportunity that has exhausted \`MAX_ATTEMPTS\` (§7.3) without a confirmed submission is moved to \`MANUAL_REVIEW\` by WORKFLOW_ENGINE.md §66/§68, which the \`application_state NOT IN (...)\` clause above already excludes — so exhausted-retry opportunities cannot silently inflate the reserve by lingering in \`READY\` forever.

This derivation prevents:

\`\`\`text
old scored rows
filtered rows
historical skipped rows
expired rows
\`\`\`

from inflating actionable reserve.

The target buffer is:

\`\`\`text
READY_RESERVE_TARGET = 300
\`\`\`

The reserve calculation must remain cheap enough to execute continuously.

---

# 27. Strict Age-Cascade Support

The data model must make the scheduler's age cascade cheap to query.

Required derived field:

\`\`\`text
age_band
\`\`\`

Supported values:

\`\`\`text
0_3D
4_7D
8_14D
15_21D
EXPIRED
\`\`\`

The scheduler will query:

\`\`\`text
0_3D first
→ 4_7D
→ 8_14D
→ 15_21D
\`\`\`

## 27.1 Recomputation Contract

The stored \`opportunities.age_band\` column is a denormalized cache that exists so the scheduler's claim query can filter/index cheaply. It is **not** the canonical age determination.

\`\`\`text
canonical age_band = f(age_basis, age_reference_at, now)
\`\`\`

using the boundary hours fixed in ARCHITECTURE_REDESIGN_FINAL.md §3.2 (0–72h / >72–168h / >168–336h / >336–504h / >504h = EXPIRED).

Two refresh paths keep the cached column from drifting past a band boundary:

\`\`\`text
1. Per-claim revalidation (WORKFLOW_ENGINE.md §72 "Candidate Revalidation";
   IMPLEMENTATION_ROADMAP.md §38 "M2 — Freshness Revalidation")
   recomputes age_band live from age_reference_at at claim time and
   uses that live value for the claim decision, never the stale cached
   column alone.

2. A periodic maintenance sweep (WORKFLOW_ENGINE.md §76) recomputes and
   persists age_band for all non-expired opportunities so the cached
   column, indexes, and reserve/observability counts stay accurate
   between claims.
\`\`\`

An opportunity's cached \`age_band\` may lag between sweeps; the scheduler's claim-time revalidation is the correctness guarantee, and the sweep is the performance/observability guarantee. Neither may be skipped.

The data model must not introduce additional age-priority tiers for:

\`\`\`text
retry
manual review
recovery
channel failure
\`\`\`

Those remain overlays.

---

# 28. Core / Stretch Persistence

The opportunity stores current classification:

\`\`\`text
CORE
STRETCH
\`\`\`

The classification is a policy output, not identity.

Historical classification changes may be retained in \`evaluation_history\`.

A change from \`STRETCH\` to \`CORE\` must not create a second opportunity.

The data model must support the approximate policy preference:

\`\`\`text
~70% core
~30% stretch
\`\`\`

without making tier distribution a substitute for age ordering.

---

# 29. Channel Routing Persistence

The canonical opportunity may have more than one possible application route.

The data model therefore must not permanently equate:

\`\`\`text
opportunity
→ one channel
\`\`\`

Possible route data may live in the latest source observation, a normalized route object, or a dedicated implementation structure, but semantic ownership must preserve:

\`\`\`text
one opportunity
→ zero/one/many discovered routes
→ one selected channel per attempt
\`\`\`

\`application_attempts.channel\` records the route actually used by that attempt.

\`channel_health\` records the operational condition of the channel separately.

---

# 30. Response Correlation and Duplicate Protection

The data model must support this chain:

\`\`\`text
canonical opportunity
→ application attempt
→ submission evidence
→ employer response
\`\`\`

An employer acknowledgement may strengthen submission evidence when it is legitimately correlated.

A response must not create a second application attempt.

A source observation must not create a duplicate application merely because it has a different URL.

A later observation of a previously submitted opportunity must resolve to the same canonical opportunity and remain protected.

---

# 31. Data Retention Rules

Historical application and evidence data should not be deleted merely because an opportunity expires.

Recommended retention semantics:

\`\`\`text
opportunity record      → retained
source observation     → retained
application attempt    → retained
submission evidence    → retained
response               → retained
evaluation history     → retained
work_queue row         → disposable / rebuildable
model cache            → disposable
browser state          → disposable
\`\`\`

An expiration transition is therefore a state change, not an archival deletion event.

---

# 32. Secret-Handling Boundary

The application database contains sensitive operational information.

It may contain:

\`\`\`text
candidate application history
cover-letter references
employer messages
submission evidence
browser artifact references
\`\`\`

It must not contain:

\`\`\`text
Gmail app password
browser passwords
session cookies
API secrets
private keys
authentication tokens
\`\`\`

Secrets remain in the approved local secret mechanism.

Database permissions remain owner-restricted.

---

# 33. Serialization and Structured Fields

Text fields that need structured subfields may use JSON serialization while SQLite remains the source of record.

Appropriate examples:

\`\`\`text
raw_metadata
fit_reasons
browser_signals
network_signals
evidence_json
\`\`\`

JSON must be treated as structured data with documented keys, not an unbounded dumping ground.

Fields used frequently in scheduler or uniqueness queries should be represented as first-class columns rather than repeatedly parsed from JSON.

---

# 34. Time Handling

All timestamps must be stored consistently and parseably.

Recommended representation:

\`\`\`text
UTC ISO-8601 / SQLite-compatible datetime
\`\`\`

The implementation must not mix ambiguous local timestamps with UTC timestamps without explicit conversion.

Age calculations must use a single consistent temporal basis.

Daily quota calculations must use the configured system timezone semantics deliberately rather than relying on arbitrary browser timestamps.

---

# 35. Null and Unknown Semantics

Null is not automatically equivalent to false, zero, closed, or ineligible.

Examples:

\`\`\`text
salary = NULL
    → salary unknown

posted_at = NULL
    → use approved age fallback

open_state = UNKNOWN
    → not the same as CLOSED

fit_score = NULL
    → not evaluated / unavailable

confirmation_url = NULL
    → not necessarily failed submission
\`\`\`

When a value is unknown, the owning logic must apply an explicit policy rather than relying on a database default that changes meaning.

---

# 36. Current vs Historical Values

The database must distinguish current projections from historical evidence.

Example:

\`\`\`text
opportunities.fit_score
    = current best fit score

evaluation_history.score
    = score produced by one historical evaluation
\`\`\`

Likewise:

\`\`\`text
opportunities.current_open_state
    = current best state

source_observations.open_state
    = what one source reported at one observation time
\`\`\`

This pattern applies throughout the model.

---

# 37. Data-Model Invariants

The implementation must preserve these invariants.

### Identity

\`\`\`text
[ ] canonical_key is unique
[ ] URL is not universal identity
[ ] one opportunity can have multiple observations
[ ] confirmed application history is canonical
\`\`\`

### Observation

\`\`\`text
[ ] source observations retain source-specific evidence
[ ] source failure is not source closure
[ ] re-observation can update a previous opportunity
\`\`\`

### Application

\`\`\`text
[ ] every real application execution has an attempt
[ ] every attempt references one opportunity
[ ] attempts preserve evidence
[ ] ambiguous submit is persisted as ambiguous
\`\`\`

### Channel

\`\`\`text
[ ] channel health is independent of opportunity truth
[ ] one opportunity may have multiple possible channels
[ ] one attempt records the actual selected channel
\`\`\`

### Queue

\`\`\`text
[ ] work_queue is derived
[ ] work_queue can be rebuilt
[ ] stale historical records do not inflate reserve
\`\`\`

### Age

\`\`\`text
[ ] age basis is explicit
[ ] >21d cannot enter automatic application
[ ] retry is not a new age tier
\`\`\`

### Evidence

\`\`\`text
[ ] submitted requires evidence
[ ] no evidence does not mean success
[ ] duplicate retries require reconciliation
\`\`\`

### Persistence

\`\`\`text
[ ] SQLite remains source of record
[ ] DB writes are transactional
[ ] browser work does not hold DB write locks
[ ] process crashes do not erase unrelated history
\`\`\`

---

# 38. Forbidden Data-Model Shortcuts

The following patterns are explicitly forbidden:

\`\`\`text
one jobs row = one canonical opportunity
URL UNIQUE as the universal identity rule
company + title as the universal dedupe key
one status field carrying opportunity + channel + attempt truth
attempt count without an attempt ledger
submission success without evidence
channel failure stored as permanent opportunity invalidation
low score stored as permanent dead-letter identity
queue as the sole source of truth
HTTP replay transcript as application state
browser crash → whole DB rollback
unbounded JSON blobs replacing frequently queried fields
secret credentials inside application records
\`\`\`

---

# 39. Compatibility with Existing Hermes Code

The current codebase contains these load-bearing persistence components:

\`\`\`text
src/db.py
src/states.py
src/pipeline.py
src/apply.py
src/discover.py
src/response_watcher.py
config.yaml
profile/facts.md
\`\`\`

The new data model must be introduced behind explicit persistence boundaries.

During migration:

\`\`\`text
source collectors
→ persistence/domain mapping
→ canonical data model
\`\`\`

rather than allowing every source adapter to write arbitrary database columns.

Likewise:

\`\`\`text
browser applier
→ ApplyResult
→ application state/evidence mapping
→ DB
\`\`\`

The browser adapter must not become the owner of the database model.

---

# 40. Implementation Boundary for Doc 4

The next document, \`WORKFLOW_ENGINE.md\`, must consume this model to define:

\`\`\`text
state transitions
claim rules
lease transitions
retry rules
age-cascade selection
queue refill
terminal states
reconciliation
\`\`\`

Doc 4 must not redefine:

\`\`\`text
canonical identity semantics
entity ownership
source-observation semantics
attempt/evidence ownership
channel-health ownership
\`\`\`

Those are frozen here beneath the architecture.

---

# 41. Acceptance Criteria

The data-model implementation is acceptable only when:

\`\`\`text
[ ] canonical opportunities exist independently of URL
[ ] source observations can be appended/updated without duplicate canonical identities
[ ] confirmed application history survives source URL changes
[ ] every real application execution has an attempt record
[ ] ambiguous submissions cannot be converted into blind retries by missing state
[ ] channel failures are represented separately from opportunity validity
[ ] response records can correlate to opportunities/attempts
[ ] work_queue can be rebuilt from durable state
[ ] reserve calculation excludes historical dead inventory
[ ] age bands are directly queryable
[ ] >21-day opportunities cannot become automatic work
[ ] filtered/low-score historical records can be reevaluated
[ ] daily confirmed counts differ from attempt counts
[ ] database recovery can reconstruct actionable work
[ ] migration preserves existing history and evidence
[ ] no application secret is stored in the database
[ ] uniqueness and foreign-key checks pass
[ ] indexes support real claim/refresh queries
\`\`\`

---

# 42. Final Data Model

The target persistence architecture is:

\`\`\`text
                         SQLITE / WAL
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
   opportunities      source_observations   evaluation_history
          |
          +------------------------+
          |                        |
          v                        v
 application_attempts       work_queue (derived)
          |
          +----------------------+
          |                      |
          v                      v
   evidence/state          channel_health

          +----------------------+
          |
          v
       responses

          +----------------------+
          |
          v
      daily_limits
\`\`\`

The semantic center is:

\`\`\`text
OPPORTUNITY = what the job is
OBSERVATION = what a source said
EVALUATION  = what Hermes decided at that time
ATTEMPT     = what Hermes actually did
CHANNEL     = whether the route is healthy
RESPONSE    = what the employer later communicated
QUEUE       = what is currently actionable
QUOTA       = how much confirmed work has been counted
\`\`\`

That separation is the data foundation for the rest of the Hermes overhaul.

---

# 43. Final Directive

Do not optimize the database by collapsing these entities back together.

Do not rebuild identity from URLs because URL deduplication is easy.

Do not treat historical statuses as current truth.

Do not use the queue as a substitute for canonical state.

Do not use a missing success row as proof that an application never happened.

Do not let a channel failure destroy opportunity history.

The implementation goal is a small, durable, queryable state model that lets Hermes answer four questions reliably:

\`\`\`text
What opportunities exist?
What did each source report?
What has Hermes actually attempted?
What is safe and actionable right now?
\`\`\`

Everything else is derived from those facts.
