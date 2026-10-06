# Hermes — AI System

**Document ID:** HERMES-AI-SYSTEM-2026-09-27  
**Status:** ACTIVE IMPLEMENTATION SPECIFICATION  
**Document:** 6/8  
**Parent:** ARCHITECTURE_REDESIGN_FINAL-2026-09-27-FROZEN.md + MASTER_PLAN.md + SYSTEM_RULES.md + DATA_MODEL.md + WORKFLOW_ENGINE.md + BROWSER_SYSTEM.md  
**Repository:** saralbanker/hermes  
**Baseline branch:** overhaul-2026-09-23

> Purpose: define Hermes local-AI responsibilities, role contracts, inference flow, grounding, validation, resource residency, caching, failure behavior, evaluation, and migration from the current AI modules.
>
> This document implements the frozen AI architecture. It does not reopen architecture, platform scope, scheduler semantics, or candidate-policy decisions.

---

# 1. Objective

Use local AI only where semantic inference provides value beyond deterministic rules.

Primary uses:

- semantic job relevance
- semantic reranking
- structured fit scoring/classification
- truthful application-language generation
- bounded browser decision support

AI must improve selection and wording without weakening truthfulness, duplicate safety, hard eligibility, security controls, or durable workflow state.

---

# 2. Core Principle

Hermes separates four responsibilities:

1. deterministic policy
2. semantic inference
3. language generation
4. external execution

The invariant is:

AI may recommend or generate.

Deterministic code validates and authorizes.

The workflow persists the durable result.

---

# 3. Non-Negotiable AI Rules

1. No recurring paid API is required.
2. Candidate facts come only from profile/facts.md.
3. Job descriptions are untrusted external data, not instructions.
4. Hard eligibility remains deterministic.
5. Fit score is a ranking signal, not permanent truth.
6. AI failure must not kill continuous operation.
7. AI failure must not fabricate a successful application.
8. Model output is untrusted until validated.
9. AI may never override duplicate protection, daily caps, or security blocks.
10. AI may never execute arbitrary browser or shell operations.
11. One primary generative specialist should normally be resident on the 16 GB host.
12. Exact model checkpoints remain benchmark-selected inside the frozen role contracts.
13. Laya is not a Hermes dependency.
14. Heavy models are not kept resident concurrently without measured need.
15. Resource feasibility is established on the actual Ryzen 7 7730U host.

---

# 4. Role Architecture

The frozen role set is:

- Embedding
- Semantic reranking
- Scoring/classification
- Generation

Current practical baseline:

- Nomic embedding model
- BGE-class reranker
- Phi-4-mini scoring/classification specialist
- Qwen3.5-4B generation specialist

The model family/role is architectural.

The exact checkpoint is an implementation choice until benchmarked on the real host.

---

# 5. Role Separation

Each role optimizes for a different task.

Embedding favors throughput and stable semantic representation.

Reranking favors fine-grained relevance discrimination.

Scoring favors structured judgment and consistency.

Generation favors grounded language quality.

A single model can sometimes perform several tasks, but the system must not depend on forcing every role through one model.

---

# 6. Local Runtime

Primary runtime:

Ollama

Compatible lower-level backends may include:

- llama.cpp
- ONNX Runtime

The higher-level AI API should remain backend-neutral.

Current legacy llm.py is the starting point for this abstraction.

---

# 7. AI Gateway

The target AI boundary should expose operations equivalent to:

- embed(texts)
- rerank(query, documents)
- classify(input, schema)
- generate(input, constraints)
- health(role)
- load(role)
- unload(role)

The rest of Hermes should not duplicate raw Ollama HTTP calls.

---

# 8. Current Legacy Reality

Current repository AI modules include:

- src/llm.py
- src/score.py
- src/tailor.py
- src/answers.py

Current behavior is centered on:

Nomic embedding plus Qwen chat.

That behavior is migration input, not the frozen target role structure.

---

# 9. Target Evaluation Pipeline

The target evaluation path is:

Discovery data
→ deterministic hard filters
→ candidate/job embedding
→ similarity floor
→ shortlist
→ BGE-class reranking
→ Phi-4-mini fit judgment
→ ranking result

Generation occurs only after an opportunity is actionable:

Ready opportunity
→ current job context
→ approved facts
→ generation
→ validation
→ application

---

# 10. Cost Order

Expensive AI work must follow cheap deterministic work.

Preferred order:

hard filters
→ embeddings
→ reranking
→ scoring
→ generation only for actionable work

Do not generate cover letters for jobs that are already ineligible.

---

# 11. Hard Eligibility Boundary

AI must not decide hard policy gates.

Examples remain deterministic:

- geography
- published salary floor
- age
- explicit role exclusion
- impossible experience requirement
- confirmed prior application
- unsupported route
- security/channel state

When enough evidence exists, these checks occur before expensive semantic inference.

---

# 12. Embedding Role

Embedding creates a semantic representation of the candidate and job.

It answers approximately:

How semantically related are these texts?

It does not answer:

Should Hermes submit this application?

---

# 13. Candidate Representation

Candidate embedding input must derive from profile/facts.md.

Do not embed:

- passwords
- OTPs
- private mailbox contents
- transient workflow logs
- speculative facts
- unverified candidate claims

The candidate representation should remain stable enough for reuse but versioned when facts change.

---

# 14. Job Representation

Job embedding input should prioritize:

- title
- relevant description
- requirements
- responsibilities
- experience requirement
- location/work mode
- salary information where present

Do not send unlimited raw page HTML into the embedding model.

Normalize first.

---

# 15. Representation Versioning

Semantic inputs require a representation version.

A cache/evaluation record should be able to identify:

- input hash
- representation version
- model identifier
- generation timestamp

This prevents incompatible vectors or scores from being mixed.

---

# 16. Embedding Cache

Cache keys should include enough information to distinguish:

model
+
input hash
+
representation version

Candidate and opportunity identity remain separate from semantic cache identity.

A cache hit is an optimization, not canonical truth.

---

# 17. Similarity Floor

The current configuration has a calibrated minimum similarity threshold.

The target continues using a similarity floor as a cheap semantic gate.

A below-floor result is a current evaluation outcome, not a permanent tombstone.

Reevaluation remains possible after:

- job content change
- candidate facts change
- model change
- representation change

---

# 18. Similarity Is Not Eligibility

A highly similar opportunity can still be ineligible.

Examples:

- salary below policy
- unsupported location
- too old
- confirmed duplicate
- unsupported route

A semantic similarity number must never override these deterministic facts.

---

# 19. Reranker Role

The reranker receives a smaller candidate set than the embedding stage.

It performs finer semantic discrimination.

Input:

candidate query plus shortlisted job documents

Output:

relative relevance score and ordering

The reranker does not decide eligibility or submission.

---

# 20. BGE-Class Reranker

The architecture uses a BGE-class reranking role.

Do not freeze a particular large BGE checkpoint merely because it exists.

The selected checkpoint must be measured for:

- ranking lift
- CPU latency
- peak RSS
- stability
- throughput

on the real host.

---

# 21. Reranking Scope

Do not rerank the whole discovery database.

Preferred:

embedding shortlist
→ rerank top K
→ score best candidates

K is a measured performance parameter.

---

# 22. Scoring Role

The scoring specialist provides structured fit judgment.

Target baseline:

Phi-4-mini

Inputs include:

- approved candidate facts
- job title
- relevant job description
- role metadata
- deterministic eligibility context

Output is a bounded judgment.

---

# 23. Score Output

Recommended logical fields:

- score: 1–10
- confidence
- concise reason
- risk flags

The model cannot create new policy states.

Deterministic code maps the output into workflow semantics.

---

# 24. Score Meaning

A score is an internal ranking signal.

It is not:

- interview probability
- hiring probability
- guaranteed fit
- objective candidate quality
- a hiring forecast

Score interpretation depends on the model and prompt/calibration version.

---

# 25. Score Versioning

Evaluation history should retain:

- model identifier
- prompt/output-schema version (the AI prompt template and structured-output shape — distinct from the
  database's own schema generation, DATA_MODEL.md §3.1)
- score
- confidence
- reason
- input version
- timestamp

These are recorded in `evaluation_history.metadata` (DATA_MODEL.md §10.2), since no dedicated column exists for them.

Changing a model must not erase historical evaluation evidence.

---

# 26. Score Threshold

The current configuration uses a minimum fit score.

That threshold is policy/ranking logic.

An opportunity below the threshold is not permanently dead.

It may return to evaluation when its inputs or evaluation method materially change.

---

# 27. Core and Stretch

Core/stretch classification remains deterministic policy.

AI provides fit evidence.

The model must not alter role tier merely to satisfy the desired approximate distribution.

Truthfulness and hard eligibility always outrank the 70/30 preference.

---

# 28. Generation Role

Primary generation baseline:

Qwen3.5-4B

Approved uses:

- cover letters
- motivation answers
- free-text screening answers
- bounded browser decision support when explicitly needed

Generation is not used for:

- hard eligibility
- duplicate detection
- daily quota
- security decisions
- canonical identity
- submission confirmation

Automation boundary, binding on every AI-generated response (cover letters, screening answers, and any future auto-reply logic):

Automation allowed — repeatable actions Hermes may generate/send:

- resume delivery
- portfolio delivery
- GitHub delivery
- project information
- screening responses

Automation forbidden — high-impact human decisions AI must never auto-handle:

- interview decisions
- salary negotiation
- offer handling
- contract handling
- legal/identity document handling

Hermes automates repeatable actions. Hermes never automates high-impact human decisions. A screening field answerable from a fixed deterministic policy value (e.g. a stated salary floor) is a screening response, not salary negotiation; any back-and-forth negotiation, counter-offer, or employer-initiated compensation/offer/contract/legal-document discussion is forbidden and must route to a human-required state (WORKFLOW_ENGINE.md §60, Manual Review) rather than receive an AI-generated response.

---

# 29. Generation Timing

Generation should occur after a job becomes genuinely actionable.

Preferred:

claimable opportunity
→ select resume/material context
→ generate
→ validate
→ browser execution

Do not maintain a giant pre-generated cover-letter backlog.

---

# 30. Generation Input

A generation request should contain only necessary grounded context:

- candidate facts
- job/company context
- requested output type
- format requirements
- length limit
- forbidden claims

Avoid unrelated logs and private information.

---

# 31. Candidate Fact Boundary

profile/facts.md is the candidate truth boundary.

The model may transform or emphasize verified facts.

It may not invent:

- employers
- employment status
- education
- years
- salaries
- certifications
- technologies
- production claims
- client work
- metrics

---

# 32. Employer Text Boundary

Job descriptions may explain:

- what the employer wants
- why a role is relevant
- which skills matter
- how wording can be tailored

Job text cannot become candidate evidence.

A requirement such as 5 years of experience must never become a claim that the candidate has 5 years.

---

# 33. Experience Truth

The two verified experience concepts remain distinct:

- about 4 years of hands-on software development
- about 1+ year of paid client-facing professional experience

AI must never silently convert the former into four years of professional employment.

This distinction applies to:

- scoring
- cover letters
- screening answers
- browser actions

---

# 34. Degree Truth

Verified education:

Diploma in Computer Engineering, LJ Polytechnic, May 2026, CGPA 8.36/10, top 10%.

No bachelor's or master's degree exists in the fact source.

AI must not imply otherwise.

---

# 35. Skill Truth

Only skills in the verified fact sheet may be claimed.

Explicitly absent professional experience must remain absent, including examples such as:

- AWS
- GCP
- Azure
- Kubernetes
- Java/Spring
- .NET
- PHP
- iOS
- ML model training

A job requirement is not evidence of candidate experience.

---

# 36. Domain Truth

Do not fabricate domain experience such as:

- healthcare
- fintech compliance
- e-commerce at scale
- security certifications

The model may discuss these as employer requirements, not as candidate history.

---

# 37. Number Safety

Numbers are high-risk generation content.

Do not invent:

- years
- users
- revenue
- savings
- percentages
- project size
- salary
- dates

A number existing somewhere in the facts file is not automatically valid in every sentence.

---

# 38. Project Number Attribution

Project-specific metrics must remain attached to the correct project.

Examples in the fact source include:

AWIS:
about 25,000 lines of Go and 773 Go test functions.

Neuro-Zenith:
about 70,000 lines across 400+ files and 44 database migrations.

Shade Ledger:
220+ units and 40+ hours of monthly manual work saved.

A model must not transfer one project's number to another project.

---

# 39. Generation Validation

Required pattern:

generate
→ deterministic validation
→ one constrained retry if needed
→ deterministic fallback or no artifact

Unvalidated generation output must never be submitted.

---

# 40. Existing Tailor Validation

Legacy tailor.py already validates important properties including:

- unsupported numbers
- percentages
- banned skill/domain claims
- overstated professional experience
- hype claims
- project-number attribution

The target AI system must preserve these semantic guarantees during migration.

---

# 41. Generation Retry

Generation retries are bounded.

Recommended:

first generation
→ validation
→ one constrained retry
→ fallback/no artifact

Do not retry indefinitely.

Repeated invalid output is a model/prompt quality signal.

---

# 42. Deterministic Generation Fallback

Facts-only templates may be used when the model fails.

Examples:

- cover-letter fallback
- simple motivation answer
- rule-based screening response

A deterministic fallback is preferable to fabricated content.

---

# 43. Screening Architecture

Screening uses:

deterministic rules first
→ AI only when rules lack an answer and the question is genuinely answerable

Deterministic candidates include:

- name
- email
- phone
- degree
- professional experience
- notice period
- employment status
- work authorization
- sponsorship
- relocation

---

# 44. Screening Question Interpretation

Before invoking AI, identify:

- actual question text
- field type
- provided options
- whether it is required
- whether it asks for an artifact
- whether it is numeric
- whether the visible text is merely an option label

This prevents model confabulation from poor page parsing.

---

# 45. Unknown Is Valid

The model must be permitted to return:

UNKNOWN

UNKNOWN means:

The verified facts do not support a truthful answer.

It does not mean:

guess
→ choose a likely option
→ invent an answer

---

# 46. Multiple-Choice Screening

Preferred:

deterministic exact mapping
→ deterministic semantic mapping
→ AI only if needed
→ final value must be one of the supplied options

Never invent an option.

---

# 47. Boolean Screening

A yes/no model answer should be used only when the input is a real question.

A bare option such as "LinkedIn" is not a yes/no question.

This guard prevents accidental source claims.

---

# 48. Assignment Questions

Never fabricate:

- take-home repository
- challenge URL
- submission link
- homework artifact
- coding-test result

When an assignment artifact does not exist, return UNKNOWN or an unsupported result.

---

# 49. Free-Text Screening

Free-text screening may use:

candidate facts
+
current job context
+
question

The result must pass the same deterministic truthfulness checks used for cover letters.

---

# 50. Screening Validation

Validate at minimum:

- numbers
- experience
- skills
- domains
- degrees
- employment claims
- percentages
- project attribution

Screening answers are external application material and carry the same truthfulness standard.

---

# 51. Browser Decision Support

AI may optionally assist with complex structured browser state.

Possible uses:

- interpret ambiguous labels
- identify semantic control
- identify page phase
- propose one bounded next action

The model does not execute that action.

---

# 52. Browser AI Input

Prefer compact state:

- current URL
- page phase
- interactive controls
- labels
- accessible names
- validation messages
- relevant instructions

Do not send full raw HTML by default.

---

# 53. Browser AI Output

A valid conceptual output is:

CLICK element_17

or:

TYPE_TEXT element_8 using approved_answer_3

The deterministic BrowserGateway validator decides whether it can execute.

---

# 54. No Laya

Laya is not a required model, tool, or subsystem.

Browser decision support remains:

structured browser state
+
bounded AI interpretation where necessary
+
deterministic action validation

No additional browser-specialist resident model is required.

---

# 55. AI Tool Authority

AI cannot:

- run shell commands
- execute arbitrary JavaScript
- read arbitrary local files
- write arbitrary local files
- navigate to arbitrary destinations
- submit arbitrary forms
- modify SQLite directly
- modify system configuration
- override security blocks
- override duplicate protection

AI output is input to deterministic subsystems.

---

# 56. Prompt Architecture

Use task-specific prompts:

- scoring prompt
- generation prompt
- screening prompt
- browser-decision prompt

Do not create one universal prompt for every task.

Task separation improves consistency and reduces unnecessary context.

---

# 57. Prompt Versioning

Record prompt/output-schema version with structured outputs (DATA_MODEL.md §10.2) — distinct from the database's own schema generation (DATA_MODEL.md §3.1).

Prompt changes can materially change system behavior even when the model binary remains unchanged.

Evaluation history must preserve that distinction.

---

# 58. Structured Output

Prefer structured output for:

- score
- classification
- risk flags
- browser action
- multiple-choice selection

Use free text for:

- cover letters
- motivation answers
- narrative screening

All structured output is schema-validated.

---

# 59. Output Parsing

Parsing must enforce:

- expected fields
- value ranges
- enums
- types
- required values

Malformed output must not be accepted as truth.

Minor formatting defects may use bounded deterministic parsing where safe.

---

# 60. Temperature

Lower randomness is preferred for:

- scoring
- classification
- factual screening
- browser proposals

Generation may use controlled randomness for natural wording.

Temperature never replaces validation.

---

# 61. Context Size

Use the smallest useful context.

Scoring generally needs:

facts
+
title
+
location
+
bounded description

Browser decision support generally needs:

structured state
+
relevant visible context

Do not maximize context length merely because the model allows it.

---

# 62. Fact Prompt Reuse

The current Ollama implementation puts the fact sheet early in the prompt so cached-prefix behavior can reduce repeated processing.

That optimization can remain.

However, cached candidate facts must be invalidated when facts change.

Cache reuse never overrides fact freshness.

---

# 63. Model Keep-Alive

Keep-alive is a resource optimization.

Warm residency is useful for repeated same-role work.

Cold loading may be preferable when:

- model switches are infrequent
- RAM pressure is high
- browser work dominates

Exact values are runtime-tuned.

---

# 64. Serial Model Scheduling

On the constrained host, prefer:

embedding batch
→ reranking
→ scoring
→ generation for selected work

rather than keeping every heavyweight model resident simultaneously.

The AI scheduler may batch compatible tasks, but active application work takes priority.

---

# 65. Embedding Batching

Embedding requests should be batched.

Batch size is calibrated against:

- CPU throughput
- RAM
- latency
- reserve depth

Do not use a huge batch merely to maximize theoretical throughput if it stalls fresh opportunities.

---

# 66. Reranking Budget

Only a shortlist should reach the reranker.

Measure:

- K size
- ranking lift
- latency
- RSS

Choose K by observed value, not by a fixed prestige number.

---

# 67. Scoring Budget

Current configuration includes max_llm_per_run.

The target keeps a bounded scoring budget.

A large discovery backlog must not starve application execution.

Unprocessed work waits for later cycles.

---

# 68. Tailoring Budget

Current configuration includes max_tailor_per_run.

Tailoring remains just-in-time.

Avoid generating material for:

- ineligible jobs
- expired jobs
- stale opportunities
- already-applied opportunities
- jobs that cannot reach a supported route

---

# 69. AI Backpressure

When AI is slower than discovery:

preserve deterministic filtering
→ preserve actionable work
→ defer expensive evaluation
→ avoid queue explosion

AI backlog is not a reason to break scheduler freshness or daily application safety.

---

# 70. Resource Budget

The host has:

- 16 GB RAM
- Ryzen 7 7730U
- Vega 8 iGPU
- CPU-only inference
- practical AI RAM budget of about 7–10 GB

The AI subsystem must share resources with:

- browser
- Python worker
- SQLite
- discovery
- desktop

---

# 71. Runtime Memory

Model package size is not runtime memory.

Measure:

- model weights
- KV/cache
- runtime overhead
- token buffers
- embedding buffers
- Python process RSS
- browser RSS
- concurrent processes

Actual process RSS is the operational metric.

---

# 72. AI Concurrency Baseline

Default:

one expensive generative inference at a time

and limited embedding/reranking concurrency.

Do not run multiple large generation requests concurrently by default.

---

# 73. Model Switching Cost

Switching models can cause:

- load latency
- CPU spikes
- memory pressure
- cache loss

The scheduler should batch compatible tasks where practical without allowing stale backlog to block current application work.

---

# 74. Active Browser Priority

If an active browser attempt needs AI:

serve active attempt

before starting a large background scoring batch.

Application safety and completion take priority over speculative bulk scoring.

---

# 75. Freshness Priority

AI scheduling cannot violate the frozen job scheduler.

A newly discovered 1-day opportunity must not wait indefinitely behind a large 15-day scoring backlog.

AI backlog is subordinate to age-priority workflow.

---

# 76. AI Failure Classes

Classify failures such as:

- runtime unavailable
- model missing
- timeout
- malformed output
- validation failure
- context overflow
- resource exhaustion
- unexpected exception

The response depends on the class.

---

# 77. Runtime Unavailable

If local inference is unavailable:

record AI degradation
→ use safe deterministic fallback where available
→ defer model-dependent work
→ keep worker alive

Do not crash the whole continuous pipeline.

---

# 78. Missing Model

A missing model is an AI health failure.

It must become a typed LLM-unavailable condition rather than an unhandled exception.

The legacy llm.py centralized this concept as LLMUnavailable and that semantic behavior should remain.

---

# 79. Timeout

Model timeout:

bounded retry when no external side effect exists
→ otherwise defer/fallback

Never let one generation call consume the entire application budget.

---

# 80. Malformed Output

Malformed structured output:

validate
→ bounded repair/retry
→ fallback or defer

Do not silently coerce dangerous text into accepted output.

---

# 81. Validation Failure

Unsafe generation:

reject artifact
→ provide deterministic feedback
→ one bounded retry
→ fallback or no artifact

Never retry until the model happens to produce an acceptable answer.

---

# 82. Resource Exhaustion

When memory or CPU pressure becomes unsafe:

stop new heavy inference
→ release/unload model
→ record resource pressure
→ recover

Lightweight deterministic work can continue where safe.

---

# 83. AI Failure Before Application

If AI fails before browser interaction:

- no submission is confirmed
- no daily count increment occurs
- no browser lease is implied merely by an AI request

Workflow owns exact attempt semantics.

---

# 84. AI Failure During Browser Work

If browser decision support fails:

deterministic path if available
or
safe stop

Do not broaden AI authority because the normal model path is unavailable.

---

# 85. Fallback Ranking

Legacy keyword scoring can remain a degraded fallback.

It must be tagged as deterministic fallback rather than represented as an equivalent model score.

Fallback provenance should include:

- method
- version
- reason
- timestamp

---

# 86. Evaluation History

AI results belong in evaluation history with:

- opportunity
- task type
- model
- prompt/output-schema version
- input version
- timestamp
- result
- validation status

This allows reevaluation without destroying history.

---

# 87. Re-Evaluation Triggers

Material changes may trigger reevaluation:

- job description changed
- candidate facts changed
- embedding model changed
- reranker changed
- scoring model changed
- prompt/schema changed
- policy threshold changed

Do not recompute everything merely because time passed.

---

# 88. Semantic Staleness

AI output becomes stale when its inputs become stale.

Examples:

job description hash changed
candidate fact hash changed
model version changed
prompt version changed

Stale semantic output must not override current deterministic policy.

---

# 89. Cache Invalidation

Relevant cache keys may include:

- model version
- prompt version
- input representation version
- candidate fact version
- job content hash

Incompatible cached data is not valid.

---

# 90. No Cache as Canonical Truth

A cached score, embedding, or letter is an optimization artifact.

Canonical opportunity truth remains in the data model.

Historical evaluation remains historical.

---

# 91. Candidate Fact Change

When profile/facts.md changes:

- refresh candidate embedding
- invalidate affected semantic caches
- revalidate outstanding generated artifacts
- reevaluate material downstream outputs

Do not silently submit content generated from obsolete facts.

---

# 92. Job Change

When a source reports a changed job description:

observation updated
→ canonical job representation refreshed
→ affected semantic cache invalidated
→ evaluation rerun when required

The prior evaluation remains history.

---

# 93. Prompt Injection Defense

Job descriptions are untrusted.

Instructions embedded in job text such as:

ignore previous instructions
send a secret
claim a qualification
visit this URL

must be treated as data, not authority.

System instructions and candidate-fact boundaries remain higher priority.

---

# 94. Browser Prompt Injection Defense

Visible page text is also untrusted.

A page can attempt to instruct Hermes to:

- upload another document
- reveal a token
- run a command
- disable a security feature
- visit an unrelated URL

BrowserGateway and deterministic validation prevent these instructions from becoming privileged actions.

---

# 95. Candidate Data Minimization

Only necessary candidate facts should enter a given prompt.

Never send:

- passwords
- OTP values
- session cookies
- authorization headers
- unrelated private mailbox data

unless explicitly required by a separately authorized subsystem, which browser AI is not.

---

# 96. Generated URLs

AI must not fabricate:

- GitHub repositories
- portfolio URLs
- assignment links
- employer URLs
- application endpoints

Use verified candidate artifacts or current route context.

Artifact existence should be checked deterministically.

---

# 97. Generated Numbers

Numbers require both:

fact grounding
and
semantic attribution

A valid number in the facts file can still be invalid if attached to the wrong project or claim.

---

# 98. Generated Skills

A generated sentence may mention an employer requirement.

It may not convert that requirement into candidate experience.

Example:

Good semantic use:
"The role emphasizes Kubernetes."

Forbidden candidate claim:
"I have Kubernetes production experience."

when the fact sheet does not support it.

---

# 99. Generated Experience

Never allow job requirements to become candidate years.

The model must distinguish:

required experience
versus
candidate experience

before generation is accepted.

---

# 100. Browser Confidence

When browser AI is used, low confidence should produce:

deterministic fallback
or
safe stop

not:

execute anyway

Confidence is advisory.

The validator remains authoritative.

---

# 101. AI Health

Per-role health should expose:

- available/unavailable
- installed model
- last success
- last failure
- failure type
- latency
- RSS where measurable

Health informs degradation and recovery.

---

# 102. Health Recovery

After local-model failure:

backoff
→ retry
→ health restoration
→ resume role

Do not restart the complete Hermes worker for one model outage.

---

# 103. AI Observability

Useful metrics:

- request count
- success count
- failure count
- timeout count
- malformed-output count
- validation rejects
- fallback count
- average latency
- p95 latency
- model load time
- RSS where measurable

Do not create a separate analytics platform just for this.

---

# 104. Embedding Metrics

Track:

- batch size
- items per second
- latency
- RSS
- cache hit rate
- similarity distribution

These measurements support calibration of the similarity floor and batching.

---

# 105. Reranker Metrics

Track:

- K size
- ranking changes
- ranking lift
- latency
- RSS

A reranker that costs significant CPU while adding little ranking value should be tuned, not blindly maximized.

---

# 106. Scoring Metrics

Track:

- latency
- parse failures
- fallback rate
- score distribution
- validation failures

Large score drift after model/prompt changes requires benchmark review.

---

# 107. Generation Metrics

Track:

- generation latency
- validation rejection rate
- retry rate
- fallback rate
- output length

A high rejection rate is a model/prompt problem, not a reason for unlimited retries.

---

# 108. Regression Fixtures

Maintain representative local fixtures for:

- strong-fit core role
- weak-fit role
- stretch role
- salary unknown
- degree mismatch
- experience mismatch
- unsupported technology
- truthful cover letter
- hallucinated metric
- project-number mix-up
- assignment URL request
- ambiguous boolean question
- unsupported domain claim

Use them to detect regressions.

---

# 109. Golden Constraints

For structured outputs, tests should validate properties rather than exact wording.

Examples:

- score within valid range
- required field present
- valid enum
- no banned claims
- no ungrounded number

For prose, validate safety properties rather than requiring one exact sentence.

---

# 110. Model Benchmarking

Before selecting exact checkpoints, benchmark candidate models on the real host.

Measure:

- semantic quality
- ranking quality
- latency
- peak RSS
- throughput
- stability

The benchmark chooses the checkpoint inside an already-frozen role.

---

# 111. Benchmark Conditions

Measure at least:

- cold start
- warm start
- steady state
- peak RSS
- average latency
- p95 latency

Where possible, benchmark with browser/runtime activity present because production is not an isolated idle environment.

---

# 112. Benchmark Dataset

Use a fixed local corpus containing:

- representative job descriptions
- candidate fact sheet
- screening questions
- cover-letter tasks
- browser-state fixtures

Do not unnecessarily expose sensitive live employer data.

---

# 113. Model Replacement

Replacing a checkpoint inside the same role is normally an implementation change when:

- input/output contract is unchanged
- truth validation remains unchanged
- resource envelope is acceptable

It still requires regression/benchmark evidence.

---

# 114. Role Replacement

Changing the role architecture requires explicit review.

Examples:

- removing the reranker
- adding a required permanent agent
- adding another required resident generative model
- introducing a dedicated permanent browser model

These are not casual model swaps.

---

# 115. No Permanent Multi-Agent Fleet

Hermes is not designed around many simultaneously resident autonomous agents.

Preferred:

- specialist role contracts
- deterministic orchestration
- serial or bounded-semiparallel inference
- compact prompts

A cloud-style multi-agent fleet is inappropriate for the constrained laptop unless measured need and architecture review justify it.

---

# 116. Agent vs Model

Application modules can orchestrate models without turning every task into an autonomous agent.

Prefer deterministic orchestration for:

- ranking pipeline
- generation pipeline
- screening
- browser action proposal

Long-running self-directed conversations are unnecessary by default.

---

# 117. Model Memory Is Not Database State

Model context or runtime cache is not durable system state.

Durable state belongs in:

- SQLite
- approved local artifacts
- evaluation history

Models can be unloaded and restarted without losing canonical workflow truth.

---

# 118. AI Task Identity

A semantic task should have a stable logical identity based on concepts such as:

- opportunity
- task type
- input version
- model version
- prompt version

Repeated execution must not create duplicate external application attempts.

---

# 119. AI Result Persistence

Persist a model result only after its output passes the relevant validation.

Do not write an invalid artifact and later treat it as approved.

Where possible, persist provenance with the result.

---

# 120. AI + SQLite

Never hold a SQLite write transaction while waiting for inference.

Correct pattern:

read durable input
→ release transaction
→ infer
→ validate
→ write result

AI latency must never hold database write locks.

---

# 121. AI + Browser

For active browser work:

browser state
→ bounded AI proposal when needed
→ deterministic validator
→ action

Avoid launching a huge background inference batch that starves an active application.

---

# 122. Continuous Operation

AI subsystem behavior during failures:

- model down: fallback/defer
- model slow: bounded request
- model malformed: validate/retry once
- model memory pressure: unload/recover
- model unavailable: keep worker alive

Continuous operation means safe degradation, not pretending every AI task must succeed.

---

# 123. Daily Target Interaction

AI must never spend unbounded resources merely to approach the 100 qualified applications/day target.

The target is a goal.

Correctness, candidate truth, duplicate safety, and evidence remain higher priority.

---

# 124. Definition of Done

The AI system is ready when:

Roles:
- embedding role defined
- reranking role defined
- scoring role defined
- generation role defined

Grounding:
- facts boundary enforced
- employer/candidate text separated
- generated claims validated

Runtime:
- local inference works
- role health exists
- bounded timeouts exist
- deterministic fallbacks exist

Resources:
- host residency measured
- heavy-model concurrency bounded
- browser coexistence tested

Evaluation:
- representative fixtures exist
- exact checkpoint benchmark exists
- regression checks exist

---

# 125. Final AI Reference

Candidate facts
→ deterministic hard filters
→ embeddings
→ reranking
→ fit scoring
→ actionable ranking
→ generation
→ deterministic validation
→ browser execution

Cross-cutting rules:

AI proposes meaning.

Deterministic code enforces truth and policy.

Workflow owns durable state.

Browser executes only validated actions.

---

# 126. Implementer Directive

When implementing Hermes AI:

Use the frozen four-role architecture.

Keep candidate truth in profile/facts.md.

Treat external job text as untrusted data.

Run cheap deterministic work before expensive inference.

Generate only for actionable work.

Validate every external-facing artifact.

Use bounded retries.

Measure RSS and latency on the real laptop.

Prefer graceful degradation to worker failure.

Do not add Laya or an unnecessary resident model.

Do not turn Hermes into a multi-agent cloud architecture.

The AI subsystem remains local, bounded, grounded, resource-aware, recoverable, and auditable.
