# Hermes Architecture Redesign — Full Adversarial Audit

**Date:** 2026-10-01
**Scope:** All 9 documents in `architect-redesign-docs/master-redesign-plan/` (20,547 lines), cross-checked against `deepseek_adversarial_audit.md`, `FUNNEL_BOTTLENECK_AUDIT.md`, and `old_redesign_plan.md`.
**Method:** Full, non-sampled reads of every document (three parallel auditors, each covering a disjoint document set, plus orchestrator verification of the one predicate that spans auditor boundaries). Every defect below is cited to an exact file and section/line.
**Evidence hierarchy honored:** FROZEN > DATA_MODEL > WORKFLOW_ENGINE > SYSTEM_RULES > remaining documents.

---

## DELIVERABLE 1 — Repository Readiness Verdict

| Metric | Score | Basis |
|---|---|---|
| **Overall verdict** | **FAIL (as-is)** | 5 CRITICAL + 8 HIGH defects block safe implementation; none require architectural redesign, all are documentation-level corrections |
| **Readiness score** | 6/10 | Core data model, claim/fencing, and crash-recovery logic are sound and internally consistent; reserve derivation, retry-counting, channel recovery, and AI/browser resource arbitration are not |
| **Implementation score** | 5/10 | Multiple sections are written clearly enough that two engineers would implement them *differently* (outcome→state mapping, retry-exhaustion terminal state, form-stability criteria, M4 classification ownership) |
| **Confidence score** | 8/10 | Based on full-text coverage of all 9 docs + 3 historical audit docs, with the one deliberate cross-auditor-boundary predicate (READY_RESERVE / retry-eligibility) independently re-verified line-by-line by the orchestrator against all three authority documents |

---

## DELIVERABLE 2 — Defect Register (44 defects)

### CRITICAL (5)

| ID | Root cause | Files | Why it matters | Required correction |
|---|---|---|---|---|
| **G1-001** | FROZEN document (frozen 2026-09-27) contains a self-reference to "the pre-2026-09-30 revision of this diagram" — proof of a post-freeze edit with no logged change decision | ARCHITECTURE_REDESIGN_FINAL_2026-09-27-FROZEN.md §5.1 | The whole evidence hierarchy depends on FROZEN being authoritative and stable. An unlogged edit after the freeze date undermines the audit's own ground truth and any future "what changed and why" question | Add a revision log entry for the 09-30 edit, or correct the freeze date/Document ID to reflect reality |
| **G1-002 (orchestrator-verified)** | `READY_RESERVE`'s operative predicate, as literally stated in **DATA_MODEL.md §26** ("Reserve Derivation," line 1524–1543), excludes only `APPLYING, AWAITING_RECONCILIATION, COMPLETED, MANUAL_REVIEW, EXPIRED` from `application_state` — it never positively requires `application_state = READY`, nor excludes `OBSERVED`/`EVALUATING`. An opportunity still mid-evaluation that already has `hard_eligibility_state = ELIGIBLE` (a separately-completed evaluation stage, DATA_MODEL §5.7) and a fresh `age_band`/`current_open_state` satisfies every clause and would count toward the reserve. **Verified independently:** WORKFLOW_ENGINE.md §22 (line 577–588) — which DATA_MODEL §26 itself calls "the full opportunity-level retry-eligibility predicate" — *does* include `application_state = READY` explicitly, with its own rationale (line 598) for why. But DATA_MODEL §26 says §22 only "additionally governs... attempt count, route availability," not the READY gate itself. The top-authority document, FROZEN §8.1 (line 574–583), is pure prose ("available for ranking or application") and is itself ambiguous on whether a not-yet-scored opportunity counts. No document in the authority chain unambiguously closes this gap at the READY_RESERVE definition itself. | DATA_MODEL.md §26 (primary defect), cross-checked against WORKFLOW_ENGINE.md §22 and ARCHITECTURE_REDESIGN_FINAL §8.1 | This is the exact "sub-threshold/pre-score jobs counted as reserve" bug the redesign exists to eliminate (FROZEN §2.2; also flagged historically in FUNNEL_BOTTLENECK_AUDIT.md item 6, and not explicitly closed per the Group 3 remediation check). If implemented literally from DATA_MODEL §26, the reserve metric silently overcounts, corrupting the scheduler's view of actionable supply — the single most load-bearing number in the whole throughput model | Add `AND application_state = READY` as an explicit clause to DATA_MODEL.md §26's predicate, and update FROZEN §8.1's prose to state it unambiguously |
| **G2-001** | WORKFLOW_ENGINE.md §24 creates the attempt row (with `current_attempt_id` fencing) inside the claim transaction, *before* tailoring runs (§47 loop order: CLAIM → TAILOR → APPLY); §22's retry predicate counts `attempts < 3` off that same row; but §30 says a tailoring failure before external action should "not consume an application attempt." No mechanism excludes a tailoring-only failure from the counter | WORKFLOW_ENGINE.md §24, §30, §47 | Either outcome is bad: false-exhaustion to `MANUAL_REVIEW` from pure model hiccups unrelated to applicability, or — if §30 is implemented literally — an **unbounded retry loop** that never reaches `MAX_ATTEMPTS` | Either defer attempt-row creation until after tailoring succeeds, or define a separate tailoring-retry budget that doesn't touch `current_attempt_id`/the application-attempt counter |
| **G3-001** | BROWSER_SYSTEM.md §103 (line 1990–2009) enumerates five explicit channel-health degrade triggers; IMPLEMENTATION_ROADMAP.md §86 echoes the resulting enum. **No section in either document defines what returns a channel from degraded/paused back to healthy** — no condition, duration, or verification step | BROWSER_SYSTEM.md §11, §103–104; IMPLEMENTATION_ROADMAP.md §86, §93, §96 | Without a defined recovery rule, implementers will diverge (fixed timer vs. re-probe vs. manual-only). Worst case: a channel that could legitimately recover stays paused forever, or a still-blocking channel (e.g., Ashby) gets reactivated by a naive timer and re-trips immediately, burning attempt budget | Add a "channel recovery" section mirroring §103, with per-trigger reactivation conditions (e.g., `ANTIBOT_BLOCKED` requires minimum cooldown + a successful read-only probe before re-enabling submission) |
| **G3-004** | IMPLEMENTATION_ROADMAP.md §22 states a "7–10 GB practical AI RAM budget" and separately lists browser RSS and Ollama RSS as baseline measurements, but no rule combines them. BROWSER_SYSTEM.md's backpressure (§82–83, §128) is keyed purely to the browser's own RSS/page/context counts — none reference Ollama RSS or total host memory pressure | IMPLEMENTATION_ROADMAP.md §22, §75; BROWSER_SYSTEM.md §10, §82–83, §128 | This is the literal resource-contention scenario in question (local models + Chromium/Playwright on a 16 GB host). The documents acknowledge the shared envelope exists but never specify a joint ceiling or load-shedding order for when a model load and a browser launch overlap | Add an explicit joint-budget rule (e.g., don't start a new browser-interactive attempt while a model load is in flight, or a single combined-RSS backpressure trigger referenced from both documents) |

### HIGH (8)

| ID | Root cause | Files | Why it matters | Required correction |
|---|---|---|---|---|
| G1-003 | FROZEN §1's diagram lists `EXPIRED` as an attempt-outcome branch and omits `TERMINAL_FAILURE`; §5.1 defers outcome authority to DATA_MODEL §7.4, whose enum has no `EXPIRED` and does have `TERMINAL_FAILURE` | FROZEN §1, §5.1; DATA_MODEL §7.4 | Self-contradiction inside the top-authority document | Correct FROZEN §1's diagram to match DATA_MODEL §7.4 |
| G1-004 | `daily_limits.linkedin_count` references LinkedIn as a tracked channel, but LinkedIn appears in no source/channel list anywhere in the four foundation docs | DATA_MODEL §12.2 | Unreconciled legacy artifact; implies a channel that's never defined elsewhere | Define LinkedIn as a channel upstream, or remove the column |
| G2-002 | WORKFLOW_ENGINE.md §67 states in bold terms that attempt-outcome `CHANNEL_BLOCKED` and `channel_health.status` are "never the same field." EXECUTION_PROTOCOL.md §74.6 then instructs operators to "leave channel_health at its worker-set value (CHANNEL_BLOCKED...)" — citing §67 as support while doing the opposite | WORKFLOW_ENGINE.md §67; EXECUTION_PROTOCOL.md §74.6 | Direct contradiction, with one document miscciting the other as justification | Fix EXECUTION_PROTOCOL §74.6 step 3 to reference the correct `channel_health.status` enum value, not an attempt-outcome token |
| G2-003 | Systemic enum/literal drift (8+ instances): `UNSUPPORTED` vs canonical `UNSUPPORTED_CHANNEL`; `BLOCKED_ANTIBOT` vs canonical `ANTIBOT_BLOCKED`/`CHANNEL_BLOCKED`; `FORM_CHANGED` vs `FORM_SCHEMA_CHANGED`; plain `FAILED`/`BLOCKED`; `PERMANENTLY_INVALID` (undefined anywhere); `LOGIN_REQUIRED` (undefined); `NOT_SUBMITTED`/`SAFE_RETRY` (maps to no canonical state); `MODEL_UNAVAILABLE`/`MODEL_TIMEOUT` not matching AI_SYSTEM's own failure taxonomy | WORKFLOW_ENGINE.md §28, §33, §40, §53, §54, §55, §56, §59, §139, §150; AI_SYSTEM.md §76 | A pattern, not a typo — any code generated against these sections will not match the canonical enums at all, defeating the "cross-document enum alignment" remediation the repo claims is already done | Pass every token in these sections through the canonical DATA_MODEL enums and correct mismatches |
| G3-002 | `ACCOUNT_REQUIRED` (BROWSER_SYSTEM.md, 3 locations) vs. the DATA_MODEL-canonical `ACCOUNT_WALL` (also used correctly by IMPLEMENTATION_ROADMAP §86); separately `NETWORK_ERROR` vs. `NETWORK_UNAVAILABLE` — disagreeing **within BROWSER_SYSTEM.md itself** (§68 vs §103) | BROWSER_SYSTEM.md lines 922, 1402, 1407, 2008, 2563; IMPLEMENTATION_ROADMAP.md lines 1840, 1842 | Concrete counter-example to the repo's claimed "cross-document enum alignment" fix — one of the mismatches isn't even cross-document | Standardize BROWSER_SYSTEM.md on `ACCOUNT_WALL` and `NETWORK_UNAVAILABLE` everywhere |
| G3-003 | IMPLEMENTATION_ROADMAP.md §75 says "active browser work takes priority... models may be unloaded between phases." BROWSER_SYSTEM.md §97–99 has AI participating live inside the snapshot→classify→act browser loop — i.e., needs a model warm precisely while the browser is "active." Neither document reconciles per-attempt time budget (§79) against a possible cold model load mid-attempt | IMPLEMENTATION_ROADMAP.md §75; BROWSER_SYSTEM.md §79, §97–99 | "Browser wins priority" + "models unload between phases" + "AI participates live in the browser loop" cannot all be true without uncosted latency or an unwritten tie-break rule | State explicitly that the classification role stays resident for the duration of an active application attempt, and add that exception to §75 |
| G3-005 | BROWSER_SYSTEM.md's anti-bot detection (§55–56) is built entirely around CAPTCHA/Turnstile/interstitial markers. None describe a page that returns HTTP 200 with ordinary-looking body text that happens to say something like "flagged as possible spam" (Ashby's actual known behavior) | BROWSER_SYSTEM.md §50, §55, §56, §62, §112 | Of all known anti-bot behaviors, this one is most likely to produce a false "confirmed" or false "ambiguous" classification, because the page shape resembles a normal response far more than a Cloudflare interstitial does | Add a "rejection-text classification" rule alongside §56 — check page text against known per-ATS rejection phrases before trusting any confirmation-shaped signal |
| G3-011 | deepseek_adversarial_audit.md previously flagged unbounded SQLite WAL growth as HIGH. Neither BROWSER_SYSTEM.md nor IMPLEMENTATION_ROADMAP.md defines an ongoing WAL checkpoint cadence or size ceiling; Observability (§97) lists RSS/latency metrics but no WAL metric | IMPLEMENTATION_ROADMAP.md §21, §97 | A previously-identified risk remains open — confirmed "still-broken," not re-addressed | Add a periodic WAL checkpoint policy and a WAL-size/checkpoint-lag observability metric |

### MEDIUM (17)

| ID | Summary | Files |
|---|---|---|
| G1-005 | `EXPIRED` independently (re)defined in three unrelated enums with no disambiguation | DATA_MODEL (multiple) |
| G1-006 | `OBSERVED` reused for `application_state` (lifecycle start) and `execution_phase` (attempt end) with opposite meanings | DATA_MODEL §5.9, §7.5 |
| G1-007 | `channel_health.status`: DATA_MODEL defines 10 values; 3 other docs repeat a shorter 7–8-value "example" list, all omitting `DEGRADED`/`PAUSED` | DATA_MODEL §8.3; FROZEN §10.2; SYSTEM_RULES §15; MASTER_PLAN §4.6/§14.2 |
| G1-008 | `attempt_state` and `execution_phase` are parallel progress state machines on the same row with no stated sync/mapping rule | DATA_MODEL §7.2/§7.5 |
| G1-009 | No owner assigned for writing `application_state = EXPIRED` on unclaimed aged-out opportunities | DATA_MODEL §27.1 |
| G1-010 | `work_queue.age_band` has no recomputation/freshness contract, unlike `opportunities.age_band` | DATA_MODEL §27.1 |
| G1-011 | `MANUAL_REVIEW` has no documented exit/resolution path, unlike `AWAITING_RECONCILIATION` | FROZEN §15.2; DATA_MODEL |
| G2-004 | `EVALUATING` is a persisted state with no corresponding crash-recovery or startup-recovery step | WORKFLOW_ENGINE §44, §115 |
| G2-005 | Ambiguity between sequential loop placement of maintenance (§47) and "periodic" lease sweep (§76/§78) — theoretical self-race where a slow-but-alive worker's lease could be reclaimed mid-Submit | WORKFLOW_ENGINE §47, §76, §78 |
| G2-006 | Opportunity-level `MAX_ATTEMPTS = 3` is shared across channel-fallback attempts without stating this is intentional | WORKFLOW_ENGINE §22, §106–107 |
| G3-006 | No instruction to classify from rendered/visible text rather than raw HTML — the known Cloudflare challenge-script failure mode | BROWSER_SYSTEM §15, §56; IMPLEMENTATION_ROADMAP §44 |
| G3-007 | Headless-by-default framing doesn't acknowledge headful was historically used to reduce fingerprint-detection risk | BROWSER_SYSTEM §9, §10, §120 |
| G3-008 | Greenhouse's email-verification gate not reconciled with the "continuous unattended worker" goal (M9) | BROWSER_SYSTEM §48; IMPLEMENTATION_ROADMAP §78–80 |
| G3-009 | Retry-exhaustion terminal outcome is never named (TERMINAL_FAILURE? MANUAL_REVIEW? held-open RETRYABLE_FAILURE?) | IMPLEMENTATION_ROADMAP §40; BROWSER_SYSTEM §79 |
| G3-010 | "Manual review readily available" is a rollout-gate precondition with no defined mechanism; UI/control-plane work is an explicit Frozen Non-Goal | IMPLEMENTATION_ROADMAP §5, §34, §83, §108 |
| G3-012 | No outcome→state transition table — the two enums match each other, but nothing states which outcome drives which state transition | IMPLEMENTATION_ROADMAP §34; BROWSER_SYSTEM §132–136 |
| G3-013 | M4 (Indeed) requires an AI "classify question" step that the roadmap's own dependency graph assigns to M6 (two milestones later); plausibly resolved by the stated strangler-fig pattern (§15) but never stated explicitly for this case | IMPLEMENTATION_ROADMAP §15, §17, §54, §66 |

### LOW (14)

| ID | Summary |
|---|---|
| G1-012 | "Sufficient evidence" gate for `SUBMITTED` is only a qualitative hierarchy, never a checkable rule |
| G1-013 | Shorthand `failed`/`blocked` labels in quota tables never mapped to the formal outcome enum |
| G1-014 | `source_observations.open_state` column exists but its value set is never declared |
| G1-015 | FROZEN's "BAND 0–3" vs. DATA_MODEL's `0_3D` naming — same ranges, no formal mapping table |
| G1-016 | `age_band` called "Required" in prose but not marked `NOT NULL` in schema |
| G1-017 | `MAX_ATTEMPTS = 3` has no cited provenance; SYSTEM_RULES' policy-value list omits a retry-limit number despite listing "retry limits" as a category |
| G1-018 | Ambiguous whether single-residency applies identically to the generative model and `phi4-mini` (labeled a separate "specialist") |
| G1-019 | Cosmetic: inconsistent "Document: N/8" sequence markers across docs |
| G2-007 | EXECUTION_PROTOCOL §74.9 overstates what AI_SYSTEM §83 actually covers |
| G2-008 | Dual naming: `AUTH_EXPIRED` / `LOGIN_REQUIRED` |
| G2-009 | EXECUTION_PROTOCOL §61's worker-loop summary is coarser than but compatible with WORKFLOW_ENGINE §47 (not contradictory) |
| G3-014 | "Form known to be stable" (permits multi-field batching) has no defined evidence criteria |
| G3-015 | Lease metadata fields referenced only abstractly; none of `claimed_at`/`lease_until`/`worker_id`/`current_attempt_id` appear in BROWSER_SYSTEM/ROADMAP (likely owned by DATA_MODEL, out of scope for those two docs — not itself a defect, but blocks verification) |
| G3-016 | Model-family roster drift: BROWSER_SYSTEM/ROADMAP both say Nomic/BGE-reranker/Phi-4-mini/Qwen3.5-4B, internally consistent with each other but **does not match the stack named in the audit brief** (BGE Large/Phi-4 Mini/Gemma 3 4B) — see meta-finding below |

### META-FINDING (not severity-scored — affects how to read Deliverable 5)

The documents' **actual, internally-consistent model roster is Nomic (embedding) / BGE-class (reranking) / Phi-4-mini (scoring) / Qwen3.5-4B (generation)** — both docs that name it say "exact checkpoint variants are selected by benchmark," which may excuse this as a placeholder, but it does not match the "current recommended stack" (BGE Large / Phi-4 Mini / Gemma 3 4B) used to frame this audit. Any feasibility number computed against the wrong roster is invalid. **Before any benchmarking happens, pin the exact model names/checkpoints in one place AI_SYSTEM.md explicitly owns, and make every other document reference it rather than repeating the list.**

---

## DELIVERABLE 3 — Cross-Document Consistency Matrix

| Category | Status | Evidence |
|---|---|---|
| **Opportunity lifecycle enum** (`OBSERVED→EVALUATING→READY→APPLYING→{COMPLETED\|AWAITING_RECONCILIATION\|READY\|MANUAL_REVIEW\|EXPIRED}`) | ✅ Consistent (vocabulary) / ⚠️ Partial (behavior) | Enum matches byte-for-byte across DATA_MODEL §5.9, FROZEN §5.1, BROWSER_SYSTEM §131, IMPLEMENTATION_ROADMAP §34 — but no outcome→state transition table exists anywhere (G3-012) |
| **Attempt-outcome enum** | ✅ Consistent (core docs) / ❌ Inconsistent (WORKFLOW_ENGINE/EXECUTION_PROTOCOL prose) | DATA_MODEL §7.4, BROWSER_SYSTEM §131, IMPLEMENTATION_ROADMAP §34 agree exactly; WORKFLOW_ENGINE/EXECUTION_PROTOCOL prose drifts in 8+ places (G2-003) |
| **`channel_health.status` enum** | ❌ Inconsistent | DATA_MODEL's 10-value canonical set vs. 7–8-value "examples" in FROZEN/SYSTEM_RULES/MASTER_PLAN (G1-007); `ACCOUNT_REQUIRED`/`NETWORK_ERROR` drift in BROWSER_SYSTEM, including a same-document internal mismatch (G3-002) |
| **`READY_RESERVE` predicate** | ❌ Inconsistent / underspecified | FROZEN §8.1 prose is ambiguous; DATA_MODEL §26's formal predicate omits the `application_state = READY` gate that WORKFLOW_ENGINE §22 treats as essential (G1-002, CRITICAL) |
| **Retry-eligibility predicate** | ✅ Consistent once both halves are read together | DATA_MODEL §26 (timing half) + WORKFLOW_ENGINE §22 (full predicate) cross-reference each other correctly and agree — this is the one place the "split predicate" pattern works as intended, in contrast to READY_RESERVE |
| **`current_attempt_id` fencing** | ✅ Consistent within scope | Fully defined in DATA_MODEL §19.1; not contradicted anywhere it's referenced, but entirely absent from BROWSER_SYSTEM/IMPLEMENTATION_ROADMAP (G3-015), so cannot be verified as carried through to the operational layer |
| **`execution_phase` durability** | ✅ Consistent | DATA_MODEL §7.5 and BROWSER_SYSTEM §70–72 define matching values and matching synchronous-write guarantees |
| **Crash recovery classification** | ✅ Consistent | DATA_MODEL §7.5/FROZEN §13.4/§17.2 and BROWSER_SYSTEM §71–73/§86–90 give a matching stage-aware taxonomy |
| **Ownership boundaries** (tables, WAL, lease) | ⚠️ Partial | Table/data ownership is clearly assigned (DATA_MODEL §2/§17); WAL *checkpoint cadence* ownership is never assigned to any component (G3-011); lease/fencing field names are never named in the operational docs (G3-015) |
| **Model roster** | ✅ Consistent across BROWSER_SYSTEM/ROADMAP, ❌ inconsistent with audit brief's assumed stack | See meta-finding above (G3-016) |
| **Roadmap → data-model/workflow-engine references** | ⚠️ Unverified by name | IMPLEMENTATION_ROADMAP references ~13 constructs (table names, enums, abstractions, algorithms) that belong to other documents' domains; names matched correctly wherever cross-checked, but "ready reserve" (line 2062) and "lease metadata" (line 705) are referenced without their defining predicate/fields being named |

---

## DELIVERABLE 4 — Failure Mode Matrix

| # | Failure mode | Probability | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| 1 | Reserve inflation via `READY_RESERVE` gap (G1-002) | High (any opportunity with early-completed hard-eligibility, pre-score) | High — corrupts the scheduler's core supply signal | Add explicit `application_state = READY` clause | DATA_MODEL.md |
| 2 | Unbounded retry loop or false `MANUAL_REVIEW` exhaustion from tailoring failures (G2-001) | Medium–High | High — either silent infinite loop or false-negative discard of good opportunities | Exclude tailoring-only failures from the attempt counter, or give tailoring its own budget | WORKFLOW_ENGINE.md |
| 3 | Channel stuck permanently paused, or prematurely reactivated into a repeat-block loop (G3-001) | High over long-running operation | Medium–High — throughput loss, wasted attempts | Define per-trigger recovery criteria | BROWSER_SYSTEM.md |
| 4 | OOM/thrash from unreconciled Ollama + browser RAM contention on the 16GB host (G3-003/G3-004) | Medium–High under sustained operation | Critical — crash, corrupted in-flight attempt, cascading recovery load | Joint RSS ceiling + load-shedding policy, reconciled residency rule | BROWSER_SYSTEM.md + IMPLEMENTATION_ROADMAP.md (arbitrated at FROZEN level) |
| 5 | False-confirmed or false-ambiguous submission on Ashby-style silent-200 blocks (G3-005) | Medium | High — ground-truth corruption (a BLOCKED submission recorded as SUBMITTED) | Rejection-text classification rule | BROWSER_SYSTEM.md |
| 6 | Unbounded WAL growth under sustained single-worker writes (G3-011) | Medium over long uptime | Medium — disk growth, read-performance degradation, eventual checkpoint stall | Periodic checkpoint cadence + WAL-size metric | WORKFLOW_ENGINE.md maintenance plane |
| 7 | Incompatible implementations from enum drift / missing outcome→state mapping (G1/G2/G3 enum findings, G3-012) | High if implementation starts now | Medium–High — silent behavioral divergence, hard-to-debug state corruption | Single canonical enum module generated from DATA_MODEL.md, cross-doc lint in CI | DATA_MODEL.md + process |
| 8 | `MANUAL_REVIEW` backlog with no resolution tooling (G1-011/G3-010) | High — will occur as soon as retries exhaust | Medium — operator burden, stalled opportunities | Minimal CLI/query-based review procedure, even if full UI is out of scope | IMPLEMENTATION_ROADMAP.md |
| 9 | Feasibility numbers computed against the wrong model roster (meta-finding) | Certain if unresolved | High — invalidates all benchmarking until fixed | Pin exact model names/checkpoints in one authoritative location | AI_SYSTEM.md |
| 10 | Greenhouse OTP gate blocks unattended operation (G3-008) | Medium, channel-dependent | Medium — loses one channel's unattended throughput | Explicit unattended-OTP plan, or accept channel as human-assisted only | IMPLEMENTATION_ROADMAP.md |

---

## DELIVERABLE 5 — Feasibility Validation

**Can Hermes realistically achieve 100 applications/day on a Ryzen 7 7730U / 16GB RAM / Arch Linux host using this documented architecture?**

### **CONDITIONAL YES**

**Supporting evidence:**
- Nothing in the architecture is fundamentally impossible for this hardware class: SQLite, a single-worker Python process, and sequential Ollama model serving are all well within normal capability for this CPU/RAM tier at modest request volumes.
- The documents are honest about the target: both WORKFLOW_ENGINE §83 and EXECUTION_PROTOCOL §60 explicitly call 100/day "a validation target, not a guaranteed capacity" — there is no false overclaiming to correct.
- Retry/claim/fencing/crash-recovery logic (the correctness backbone) is largely sound, which matters more for *sustained* unattended operation than raw throughput does.

**Why not an unconditional YES:**
1. **The model roster is unresolved** (meta-finding) — feasibility cannot be computed until it's known whether the real stack is Nomic/BGE-reranker/Phi-4-mini/Qwen3.5-4B or BGE Large/Phi-4 Mini/Gemma 3 4B. These have different parameter counts and different CPU-inference costs.
2. **No per-job latency numbers exist for the current stack.** The only real data point available (prior Qwen 2.5 stack: ~11.8s/job scoring, ~23s/job cover-letter, ~4.5GB RSS, 24% pass rate, 100/day *not yet demonstrated*) is for a superseded model and cannot be extrapolated with confidence.
3. **Funnel math is absent from the documents.** Using the only available real pass-rate (24%, old stack), reaching 100 confirmed applications/day would require scoring roughly 417 jobs/day (~17.4/hour, ~1 every 3.4 minutes) continuously. Nothing in AI_SYSTEM.md confirms the new stack can sustain that scoring rate serialized with browser automation.
4. **RAM arbitration between Ollama and the browser is undocumented** (G3-003/G3-004). On a 16GB host running 3+ local models plus Chromium/Playwright via Xvfb, this is the single most concrete risk to *sustained* (not just peak) throughput — a single OOM-driven crash mid-attempt costs far more time than it saves.
5. **`READY_RESERVE` as literally specified can overcount** (G1-002) — if implemented as written, the system could believe it has a healthy supply of actionable opportunities when it does not, masking a throughput shortfall rather than surfacing it.

**Net assessment:** the architecture does not block 100/day, but nothing in the documents currently *proves* it either. This is a benchmarking gap, not a design gap — see Deliverable 6.

---

## DELIVERABLE 6 — Benchmark Requirement Matrix

### Already proven
- Prior-stack (Qwen 2.5, superseded) measured timings and RAM footprint on comparable hardware — useful only as a rough sanity anchor, not as evidence for the current stack.
- Several known, previously-observed ATS-specific behaviors (Indeed Cloudflare scripts, Ashby silent-200 block, Greenhouse OTP gate, Lever's low India-onsite supply) — real, but these are operational facts, not benchmarks.

### Unproven assumptions (must be resolved before benchmarking is even well-posed)
- Which exact models constitute the "current" stack (meta-finding) — **resolve this first**, before running any of the benchmarks below.
- The "7–10 GB practical AI RAM budget" (IMPLEMENTATION_ROADMAP §22) — asserted with no cited derivation or component breakdown.

### Benchmarks required before implementation
1. **Cold-start load latency + peak RSS per model**, via Ollama, on the actual target CPU, for the final (resolved) model roster.
2. **End-to-end per-job latency**: embed → rerank → score → (conditionally) generate, CPU-only, against a representative sample of real job postings.
3. **Joint peak RSS** with one model loaded + one active headful Playwright/Chromium session running concurrently via Xvfb — this is the number that validates or refutes G3-004.
4. **Real funnel/pass-rate measurement** for the new stack against real job postings — replaces the superseded 24% Qwen figure, and is the input the 100/day funnel math (Deliverable 5, point 3) depends on.
5. **WAL growth rate** under realistic sustained write volume, with whatever checkpoint cadence is adopted in response to G3-011.
6. **Live anti-bot classification validation** against real Ashby/Greenhouse/Indeed responses once the rejection-text rule (G3-005) and visible-text rule (G3-006) are implemented — this cannot be benchmarked from documents alone and requires live (careful, rate-limited, ToS-aware) testing.
7. **Sustained-cadence test**: can the single-worker, single-page serialized loop actually hold the ~1-confirmed-application-per-~14-minute cadence implied by point 3 above, once AI latency + browser automation latency + model-swap latency are all serialized together, for multiple hours unattended?

---

## DELIVERABLE 7 — Final Verdict

### **B. READY AFTER SPECIFIC FIXES**

**Justification:** The architecture's correctness backbone — claim/fencing, crash recovery, execution-phase durability, duplicate-submission prevention — is sound and internally consistent across the documents that define it. The defects found are not architectural; none require redesigning a subsystem, and the one deliberate design decision an earlier audit questioned (rejecting Camoufox/stealth in favor of a detect-and-stop posture) was handled correctly, with reasoning, not by omission. What blocks implementation is a concentrated set of **specification gaps and cross-document drift**, each narrow enough to fix without touching the frozen architecture's actual design.

**Minimum remaining actions before implementation begins** (in priority order):

1. Resolve the model-roster meta-finding — pin the exact stack in AI_SYSTEM.md, update every other reference to point to it rather than repeating the list (closes the precondition for all feasibility benchmarking).
2. Fix `READY_RESERVE`'s predicate in DATA_MODEL.md §26 to explicitly gate on `application_state = READY` (G1-002, CRITICAL).
3. Resolve the tailoring-failure/attempt-counter ambiguity in WORKFLOW_ENGINE.md (G2-001, CRITICAL).
4. Add channel-health recovery criteria to BROWSER_SYSTEM.md (G3-001, CRITICAL).
5. Add a joint RAM-arbitration rule between Ollama and the browser, reconciled with the "models may unload between phases" vs. "AI participates live in the browser loop" conflict (G3-003/G3-004, CRITICAL).
6. Fix the remaining HIGH-severity items: FROZEN's internal outcome-enum contradiction (G1-003), the `CHANNEL_BLOCKED` field-conflation between WORKFLOW_ENGINE and EXECUTION_PROTOCOL (G2-002), the systemic enum drift in WORKFLOW_ENGINE/EXECUTION_PROTOCOL (G2-003) and in BROWSER_SYSTEM/ROADMAP (G3-002), the Ashby silent-block classification gap (G3-005), and WAL checkpoint monitoring (G3-011).
7. Run the seven benchmarks in Deliverable 6 against the resolved model roster before committing to the 100/day target operationally.
8. Address the MEDIUM items opportunistically during implementation (they are implementation-ambiguity risks, not correctness risks) — in particular the outcome→state transition table (G3-012) and the M4/M6 classification-ownership statement (G3-013), since both are "two engineers would build this differently" risks that are cheap to close now and expensive to discover later.

Do not begin implementation on the items touched by the 5 CRITICAL defects until they are corrected in the documents themselves — code written against DATA_MODEL §26 or WORKFLOW_ENGINE §24/§30/§47 as currently written will reproduce the exact bugs this audit found.
