# Hermes — Implementation Readiness Verification

**Date:** 2026-10-01
**Scope:** Final implementation-blocker elimination pass over all 9 Tier 1–3 documents in `architect-redesign-docs/master-redesign-plan/` (18,826 lines), re-verified line-by-line against the current file contents (not assumed from prior reports).
**Method:** Full, non-sampled read of all 9 authoritative documents end-to-end in a single pass, followed by independent re-verification of every CRITICAL/HIGH finding in `ADVERSARIAL_AUDIT_REPORT_2026-10-01.md` against the current text (the documents were edited today — `ARCHITECTURE_REDESIGN_FINAL`, `MASTER_PLAN`, and `IMPLEMENTATION_ROADMAP` carry later timestamps than the prior audit — so "previously flagged" is not assumed to mean "still true"). Two new gaps not present in the prior audit were found during the fresh read. Lower-tier audit files (`ADVERSARIAL_AUDIT_REPORT_2026-10-01.md`, `deepseek_adversarial_audit.md`, `FUNNEL_BOTTLENECK_AUDIT.md`, `old_redesign_plan.md`) were used only as pointers to re-check, never as authority — every claim below is cited to current text in the 9 Tier 1–3 documents themselves.
**Evidence hierarchy honored:** `ARCHITECTURE_REDESIGN_FINAL` > `MASTER_PLAN` > `SYSTEM_RULES` > `DATA_MODEL` > `WORKFLOW_ENGINE` > `BROWSER_SYSTEM` > `AI_SYSTEM` > `EXECUTION_PROTOCOL` > `IMPLEMENTATION_ROADMAP`.

---

## 1. Executive Verdict

**IMPLEMENTATION READY AFTER SPECIFIC FIXES.**

No finding below requires architectural redesign, a new subsystem, a new platform, or any change forbidden by the frozen baseline. Every open item is a documentation-level correction: a missing clause in a stated predicate, an undefined token, a missing recovery rule, or a missing operator/notification procedure. The frozen correctness backbone — claim/fencing (`DATA_MODEL.md §19.1`, `WORKFLOW_ENGINE.md §105`), crash recovery (`DATA_MODEL.md §7.5`, `WORKFLOW_ENGINE.md §41-§45`), duplicate-submission prevention (`WORKFLOW_ENGINE.md §64`), and the notification-severity model (`SYSTEM_RULES.md §31`, `WORKFLOW_ENGINE.md §61/§68`) are sound and internally consistent.

A prior adversarial audit (`ADVERSARIAL_AUDIT_REPORT_2026-10-01.md`, same date, earlier) found 5 CRITICAL and 8 HIGH defects. The documents were revised after that audit (file timestamps: `ARCHITECTURE_REDESIGN_FINAL` 14:02, `MASTER_PLAN` 14:02, `IMPLEMENTATION_ROADMAP` 14:06, vs. the other six documents at 12:4x–12:5x). Re-verification against the current text shows the revision pass was **selective, not comprehensive**:

- **Fixed:** `daily_limits.linkedin_count` removed (G1-004), WAL checkpoint cadence/metric added (G3-011), a full outcome→state Transition Table added (G3-012, `WORKFLOW_ENGINE.md §68`).
- **Still open, unchanged:** all 5 prior CRITICAL items, and 5 of 8 prior HIGH items.
- **New, not previously found:** a `responses.classification` taxonomy conflict with no routing rule for plain acknowledgement emails, and a missing operator procedure for Gmail-watcher authentication failure.

The practical implication: an engineer who starts coding against the current `DATA_MODEL.md §26` reserve formula or `WORKFLOW_ENGINE.md §24/§30/§47` tailoring-attempt interaction will reproduce real bugs, not hypothetical ones. These are narrow, surgical fixes — see §13 for exact patch text.

---

## 2. Architecture Readiness Score: 7/10

The frozen architecture (`ARCHITECTURE_REDESIGN_FINAL...FROZEN.md`) and the domain contracts beneath it are coherent at the design level: canonical identity, age-cascade scheduling, evidence-based confirmation, and the security boundary are unambiguous and consistently invoked everywhere they matter. The score is not higher because one frozen-document self-reference (§4.1 below) undermines the freeze's own evidentiary basis, and because the top-level attempt-outcome diagram (`ARCHITECTURE_REDESIGN_FINAL.md §1`) still conflicts with the document's own later, authoritative enum (`DATA_MODEL.md §7.4`).

## 3. Implementation Readiness Score: 5/10

Unchanged from the prior audit's assessment, because none of the items that justified that score have been corrected. Two specific sections (`DATA_MODEL.md §26`, `WORKFLOW_ENGINE.md §24/§30/§47`) would cause two competent engineers to build materially different, and in one case actively incorrect, implementations if coded today exactly as written. See §4.1–§4.2.

---

## 4. Defect Register

Each entry: severity, authoritative document/section, implementation impact, smallest correction. Confirmed by re-reading the cited text in this pass, not inherited from the prior audit.

### CRITICAL

#### 4.1 — `READY_RESERVE` predicate omits the `application_state = READY` gate (re-confirmed open)

- **Document / section:** `DATA_MODEL.md §26`, cross-checked against `WORKFLOW_ENGINE.md §15` and `§22`, and `ARCHITECTURE_REDESIGN_FINAL.md §8.1`.
- **Current text:** The predicate is `current_open_state IN (...) AND age_band IN (...) AND hard_eligibility_state = ELIGIBLE AND application_state NOT IN (APPLYING, AWAITING_RECONCILIATION, COMPLETED, MANUAL_REVIEW, EXPIRED) AND no permanent all-channel block AND retry conditions satisfied`.
- **Why it's a bug, not a style issue:** `opportunities.application_state` (`DATA_MODEL.md §5.9`) has 8 values: `OBSERVED, EVALUATING, READY, APPLYING, AWAITING_RECONCILIATION, COMPLETED, EXPIRED, MANUAL_REVIEW`. The `NOT IN (...)` clause excludes 5 of them, leaving `OBSERVED`, `EVALUATING`, and `READY` all satisfying the predicate. Fit evaluation (embedding → BGE rerank → Phi-4-mini judgment) is explicitly rate-bounded per cycle (`AI_SYSTEM.md §67`, "current configuration includes `max_llm_per_run`... a large discovery backlog must not starve application execution. Unprocessed work waits for later cycles"). This guarantees a continuously-present backlog of opportunities that have cleared hard eligibility (`hard_eligibility_state = ELIGIBLE`) but are still in `EVALUATING` awaiting fit scoring — not a rare edge case, a structural one. As literally written, `READY_RESERVE` counts this backlog, reproducing the exact "sub-threshold/pre-score jobs counted as reserve" failure mode the redesign exists to eliminate (`ARCHITECTURE_REDESIGN_FINAL.md §2.2`).
- **Cross-check:** `WORKFLOW_ENGINE.md §22` (the "authoritative, opportunity-level retry-eligibility predicate") explicitly requires `opportunity.application_state = READY` and gives its own rationale for naming it explicitly (because claim-time revalidation must reject `APPLYING`/`AWAITING_RECONCILIATION`/`MANUAL_REVIEW` regardless of attempt history). `DATA_MODEL.md §26` cites §22 as covering "attempt count, route availability" only — not the READY gate itself — so the two predicates are not actually equivalent despite the cross-reference implying they are.
- **Implementation impact:** `READY_RESERVE` is "the single most load-bearing number in the whole throughput model" (it gates refill/backoff decisions, `WORKFLOW_ENGINE.md §9/§84`, and is the primary observability signal for supply health, `SYSTEM_RULES.md §32`). An inflated reserve masks a real throughput shortfall instead of surfacing it — directly contradicting `MASTER_PLAN.md §12`'s stated purpose for this metric.
- **Smallest correction:** In `DATA_MODEL.md §26`, replace `application_state NOT IN (APPLYING, AWAITING_RECONCILIATION, COMPLETED, MANUAL_REVIEW, EXPIRED)` with `application_state = READY`. This is strictly more restrictive (it already implies exclusion of all 5 named states, plus `OBSERVED`/`EVALUATING`) and requires no other clause to change. Also update `ARCHITECTURE_REDESIGN_FINAL.md §8.1`'s prose ("available for ranking or application") to state the same condition explicitly, since it is currently pure prose and does not itself resolve the ambiguity.

#### 4.2 — Tailoring failure vs. attempt-counter interaction is unresolved (re-confirmed open)

- **Document / section:** `WORKFLOW_ENGINE.md §24` (claim transaction), `§30` (tailoring failure), `§47` (loop order).
- **Current text:** §24's claim transaction creates the `application_attempts` row (new `attempt_id`, incrementing `attempt_number` per `DATA_MODEL.md §7.3`) and marks the opportunity `APPLYING`, **before** tailoring runs (§47 order: `CLAIM NEXT → TAILOR → RESOLVE CHANNEL → APPLY`). §30 then states a tailoring failure before external action should "not consume an application attempt."
- **Why it's unresolved:** The attempt row already exists with a specific `attempt_number` by the time tailoring can fail. A tailoring failure (e.g., Ollama unavailable, per `AI_SYSTEM.md §77`/`WORKFLOW_ENGINE.md §56`) is classified via the Retry Matrix (`WORKFLOW_ENGINE.md §114`, "model unavailable before external action → defer/retry") as `RETRYABLE_FAILURE` — which **does** increment the attempt history and **does** count toward `MAX_ATTEMPTS = 3` (`WORKFLOW_ENGINE.md §22`: `attempts < 3`). No mechanism in the current text excludes a pure-tailoring failure (zero browser/external interaction, `execution_phase = NOT_STARTED` per `DATA_MODEL.md §7.5`) from this count. §30's stated intent and the actual mechanics of §24/§47 are not reconciled anywhere in the 9 documents.
- **Implementation impact:** Two mutually exclusive bad outcomes, and nothing in the text says which one to accept: (a) implement §30 literally and the opportunity gets an unbounded number of free tailoring-failure retries that never reach `MAX_ATTEMPTS` (contradicts `SYSTEM_RULES.md §12`, "the database must not allow ordinary application logic to create an unbounded retry loop"), or (b) implement §22/§114 literally and 3 consecutive Ollama hiccups — zero external interaction, zero evidence problem — permanently exile a perfectly good, fresh, hard-eligible opportunity to `MANUAL_REVIEW` (`WORKFLOW_ENGINE.md §66`).
- **Smallest correction:** Add one sentence to `WORKFLOW_ENGINE.md §22` and `§30`: "An attempt whose `execution_phase` never advances past `NOT_STARTED` (`DATA_MODEL.md §7.5`) — i.e., no browser/network action toward the target site began — does not count against `MAX_ATTEMPTS` in §22's `attempts < 3` clause, even though its row persists for audit." This requires no schema change: `execution_phase` already exists and already distinguishes exactly this case.

#### 4.3 — Channel-health recovery criteria are undefined (re-confirmed open)

- **Document / section:** `BROWSER_SYSTEM.md §103-104`; `IMPLEMENTATION_ROADMAP.md §86`.
- **Current text:** §103 enumerates five trigger→degrade mappings (`login_required → AUTH_EXPIRED`, etc.). §104 clarifies cooldown is separate from opportunity age. Neither section, nor any other section in `BROWSER_SYSTEM.md` (confirmed by full read), states what moves a channel **back** to `HEALTHY`.
- **Partial existing coverage:** `EXECUTION_PROTOCOL.md §74.5` defines recovery for `AUTH_EXPIRED` specifically (operator re-authenticates; channel resumes automatically once `channel_health` reports available — "no separate resume command... health is read live"). `DATA_MODEL.md §8.2`'s schema has a `cooldown_until DATETIME` field, implying some time-based reactivation exists for the other five statuses, but no document states the duration or whether a re-probe is required before resuming submission.
- **Implementation impact:** Without a stated reactivation rule, implementers will diverge: a fixed timer, a re-probe-on-expiry, or manual-only. The worst case is concrete and already named in the documents themselves: `ANTIBOT_BLOCKED` on Ashby (`BROWSER_SYSTEM.md §50`, `IMPLEMENTATION_ROADMAP.md §85`) reactivated by a naive timer would immediately re-trip the block and burn attempt budget on a channel the architecture explicitly treats as "not a bypass project."
- **Smallest correction:** Add a `§103.1 Channel Recovery` subsection to `BROWSER_SYSTEM.md` with one rule per trigger, e.g.: `AUTH_EXPIRED` → clears only via successful re-auth (already covered, `EXECUTION_PROTOCOL.md §74.5`); `RATE_LIMITED` / `NETWORK_UNAVAILABLE` → clears when `cooldown_until` elapses; `FORM_SCHEMA_CHANGED` → does not self-heal on a timer, requires an explicit code/driver update before clearing; `ANTIBOT_BLOCKED` → requires minimum cooldown **and** a successful read-only, non-mutating probe before resuming *submission* attempts specifically.

#### 4.4 — No joint RAM-arbitration rule between Ollama and the browser (re-confirmed open)

- **Document / section:** `AI_SYSTEM.md §70-75`, `§121`; `BROWSER_SYSTEM.md §82-83`, `§128`; `IMPLEMENTATION_ROADMAP.md §22`.
- **Current text:** Both documents state the 16 GB host is shared (`AI_SYSTEM.md §70`: "must share resources with browser, Python worker, SQLite, discovery, desktop"; `BROWSER_SYSTEM.md §82`: identical framing in the other direction) and both state a priority **order** (active browser work outranks speculative AI batches, `AI_SYSTEM.md §74`/`§121`). Neither states a **joint ceiling** — a combined-RSS number or load-shedding rule that fires when a model load and a browser launch would overlap.
- **Implementation impact:** This is the literal resource-contention scenario the hardware target exists to worry about (16 GB RAM, one CPU-only inference host, Chromium concurrently resident). An OOM mid-attempt is the single most expensive failure mode in the whole system — it can corrupt an in-flight `SUBMIT_INTENT` attempt into exactly the ambiguous-submission state the architecture spends the most effort protecting against (`DATA_MODEL.md §21`).
- **Smallest correction:** Add one rule, in `SYSTEM_RULES.md` (the cross-cutting rules document) since it spans two domain documents: "Before loading or reloading a generative/scoring model, the AI Gateway checks current browser process RSS (`BROWSER_SYSTEM.md §81`); before opening a new browser context mid-cycle, the workflow checks current Ollama RSS. If the measured combined RSS would exceed the safe ceiling established during `IMPLEMENTATION_ROADMAP.md §22`'s M0 resource baseline, the lower-priority operation defers per the existing priority order (`AI_SYSTEM.md §74`)." This requires no new measurement infrastructure — both RSS values are already listed as metrics to capture (`AI_SYSTEM.md §71`, `BROWSER_SYSTEM.md §81`) — only a rule that combines them.

#### 4.5 — Frozen document contains a post-freeze self-reference with no revision log (re-confirmed open)

- **Document / section:** `ARCHITECTURE_REDESIGN_FINAL...FROZEN.md §5.1`.
- **Current text:** "The pre-2026-09-30 revision of this diagram listed a single collapsed sequence..." — this sentence proves the document, frozen 2026-09-27 per its own header and §29 revision status, was edited after 2026-09-30, with no corresponding entry in a revision log (there is none in the document) and no update to the "Revision status: Final frozen baseline — 2026-09-27" line at the bottom.
- **Implementation impact:** Low direct functional impact, but high process impact: the entire evidence hierarchy in every one of the 9 documents depends on this file being the stable, dated ground truth against which "what changed and why" questions are answered (`SYSTEM_RULES.md §39`: "A real architecture change must document: existing decision, new decision, reason, evidence, impact..."). An undated, unlogged edit to the supposedly-frozen document is itself the exact failure mode §39 exists to prevent — and this audit's own evidence hierarchy now has a self-undermining citation at its root.
- **Smallest correction:** Add a one-line revision log entry at the end of the document (e.g., "2026-09-30: §5.1 diagram corrected to separate opportunity-processing-state from attempt-outcome dimensions; see SYSTEM_RULES.md §39 change-control record") or correct the freeze metadata to reflect that this is now baseline 2026-09-30, not 2026-09-27.

### HIGH

#### 4.6 — `ARCHITECTURE_REDESIGN_FINAL.md §1` top diagram still conflicts with `DATA_MODEL.md §7.4` (re-confirmed open, partially mitigated)

- **Current text:** §1's diagram lists, as branches of "VERIFIED APPLICATION ATTEMPT": `SUBMITTED, ALREADY_APPLIED, SUBMISSION_UNCONFIRMED, RETRYABLE_FAILURE, CHANNEL_BLOCKED / UNSUPPORTED_CHANNEL, EXPIRED (>21d)`. The authoritative attempt-outcome enum (`DATA_MODEL.md §7.4`) has 7 values and does **not** include `EXPIRED` (an `application_state`, not an attempt outcome, per `DATA_MODEL.md §5.9`) and **does** include `TERMINAL_FAILURE`, absent from the §1 diagram.
- **Mitigating factor:** §5.1, four sections later, now explicitly states the top-level diagrams are "conceptual flow through both dimensions together, not a literal enum" and defers to `DATA_MODEL.md §5.9`/`§7.4`. But §1 — the very first page of the document — carries no such disclaimer, and a reader encountering it first has no signal not to treat it as the literal enum.
- **Smallest correction:** Either remove `EXPIRED` from §1's list and add `TERMINAL_FAILURE`, or add the same one-sentence disclaimer used in §5.1 directly beneath the §1 diagram.

#### 4.7 — `EXECUTION_PROTOCOL.md §74.6` conflates `CHANNEL_BLOCKED` (attempt outcome) with `channel_health.status`, while citing the section that forbids exactly this (re-confirmed open)

- **Current text:** `WORKFLOW_ENGINE.md §67` states in bold terms: "`CHANNEL_BLOCKED` is the attempt-outcome value for this dimension; it is distinct from `channel_health.status = ANTIBOT_BLOCKED`... The two are never the same field." `EXECUTION_PROTOCOL.md §74.6` step 3 then instructs: "leave `channel_health` at its worker-set value (`CHANNEL_BLOCKED` / route-dependent, `WORKFLOW_ENGINE.md §67`)" — citing §67 as support while using `CHANNEL_BLOCKED` as if it were a `channel_health.status` value, which is the exact conflation §67 forbids.
- **Implementation impact:** An operator or implementer following §74.6 literally would attempt to write `CHANNEL_BLOCKED` into the `channel_health.status` column, which per `DATA_MODEL.md §8.3`'s canonical 10-value enum has no such value.
- **Smallest correction:** In `EXECUTION_PROTOCOL.md §74.6` step 3, replace `(CHANNEL_BLOCKED / route-dependent, WORKFLOW_ENGINE.md §67)` with the correct `channel_health.status` value for a security block, i.e. `ANTIBOT_BLOCKED` (`DATA_MODEL.md §8.3`), and drop the `§67` citation from this clause since §67 is about the attempt-outcome field, not this one.

#### 4.8 — Systemic enum/token drift in `WORKFLOW_ENGINE.md` narrative sections (re-confirmed open, pattern unaddressed)

- **Current text, confirmed present in this pass:**
  - `§53`, `§139`: `BLOCKED_ANTIBOT` — matches neither `channel_health.status = ANTIBOT_BLOCKED` nor attempt-outcome `CHANNEL_BLOCKED` (`DATA_MODEL.md §8.3`/`§7.4`). (Note: this token is a legitimate citation of legacy code, `src/apply.py`'s `BLOCKED_ANTIBOT` constant, when used in `ARCHITECTURE_REDESIGN_FINAL.md §6`; here in `WORKFLOW_ENGINE.md` it is used as if it were the canonical workflow token, which it is not.)
  - `§54`: `FORM_CHANGED` — canonical is `FORM_SCHEMA_CHANGED`.
  - `§55`: `LOGIN_REQUIRED` used as an undefined alternate to `AUTH_EXPIRED`.
  - `§56`: `MODEL_UNAVAILABLE` / `MODEL_TIMEOUT` — do not match `AI_SYSTEM.md §76`'s own stated failure-class vocabulary ("runtime unavailable", "timeout").
  - `§59`: `PERMANENTLY_INVALID` — appears nowhere else in any enum in the 9 documents.
- **Implementation impact:** This is a pattern across 5+ sections of the same document, not an isolated typo. Code generated against these narrative sections will not match the canonical `DATA_MODEL.md` enums, which is precisely the risk the data model's own ownership rule (`DATA_MODEL.md §2`: "No entity may silently become the owner of another entity's truth") exists to prevent.
- **Smallest correction:** Pass every token in `WORKFLOW_ENGINE.md §§53-59, §139` through the canonical enums in `DATA_MODEL.md §5.9/§7.4/§8.3` and correct mismatches; for `BLOCKED_ANTIBOT` specifically, disambiguate which dimension is meant at each occurrence (e.g., "record attempt outcome = `CHANNEL_BLOCKED`; set `channel_health.status = ANTIBOT_BLOCKED`").

#### 4.9 — `ACCOUNT_REQUIRED`/`NETWORK_ERROR` drift inside `BROWSER_SYSTEM.md` itself (re-confirmed open)

- **Current text:** `§41`, `§68`, `§136` all use `ACCOUNT_REQUIRED`; the canonical `channel_health.status` value is `ACCOUNT_WALL` (`DATA_MODEL.md §8.3`). Separately, `§68`'s error taxonomy lists `NETWORK_ERROR` while `§103` (same document) uses `NETWORK_UNAVAILABLE` for the identical concept.
- **Notable pattern:** Most of `§68`'s other entries (`ANTIBOT_BLOCKED`, `RATE_LIMITED`, `AUTH_EXPIRED`, `FORM_SCHEMA_CHANGED`) are named identically to their `channel_health` counterpart, implying a 1:1 naming convention across the browser-error-taxonomy → channel-health mapping. `ACCOUNT_REQUIRED` and `NETWORK_ERROR` break that convention with no stated reason, inside a single document, which is a stronger defect than ordinary cross-document drift.
- **Smallest correction:** In `BROWSER_SYSTEM.md §41/§68/§136`, replace `ACCOUNT_REQUIRED` with `ACCOUNT_WALL` and `NETWORK_ERROR` with `NETWORK_UNAVAILABLE`, matching this document's own §103 and the canonical `DATA_MODEL.md §8.3` enum.

#### 4.10 — No classification rule for an ordinary-looking HTTP 200 rejection page (re-confirmed open)

- **Document / section:** `BROWSER_SYSTEM.md §55-56`, `§62`, `§112`.
- **Current text:** Anti-bot/security-interstitial detection (§56) is built around high-signal markers: challenge-specific title/URL/iframe, or "very low content + challenge marker." No section addresses a page that returns HTTP 200 with an ordinary-looking body that happens to contain plain rejection text (the documented, known Ashby behavior — "flagged as possible spam" — referenced elsewhere in the document set as the reason Ashby is `BLOCKED_ANTIBOT`, `ARCHITECTURE_REDESIGN_FINAL.md §6`).
- **Implementation impact:** Of all known anti-bot behaviors in scope, this is the one most likely to be misclassified as a confirmation or an ambiguous-but-passable state, since its page shape resembles a normal response far more than a Cloudflare interstitial does — directly risking a false `SUBMITTED` record, the worst possible truthfulness failure in the system.
- **Smallest correction:** Add a rule beside §56: maintain a small per-channel list of known rejection phrases (e.g., Ashby's observed text); check the post-submit page's visible text against this list **before** accepting any confirmation-shaped signal as evidence, tying into the existing Evidence Hierarchy (§62) by treating a rejection-phrase match as overriding weak confirmation signals.

---

## 5. Ambiguity Register (does not block implementation, but should be resolved opportunistically)

| ID | Ambiguity | Documents | Why it's lower severity |
|---|---|---|---|
| A1 | `OBSERVED` is reused for `application_state` (first lifecycle stage) and `execution_phase` (final post-submit phase) with opposite temporal meaning | `DATA_MODEL.md §5.9`, `§7.5` | The two fields are distinct columns, always referenced by full dotted name (`opportunities.application_state` vs. `application_attempts.execution_phase`) everywhere else in the document set; risk is confined to a reader skimming a bare log line, not to a correctly-scoped implementation. |
| A2 | Browser decision-support AI (`AI_SYSTEM.md §51-54`, `BROWSER_SYSTEM.md §97-99`) may need a model warm mid-attempt, while `IMPLEMENTATION_ROADMAP.md §75` says "models may be unloaded between phases" | `AI_SYSTEM.md §51/§74`, `BROWSER_SYSTEM.md §97-99`, `IMPLEMENTATION_ROADMAP.md §75` | Narrower than it first appears: tailoring/generation is explicitly just-in-time and happens *before* the browser stage in the common-path loop (`WORKFLOW_ENGINE.md §47`: `TAILOR → RESOLVE CHANNEL → APPLY`), and browser decision-support AI is explicitly optional ("may optionally assist", `AI_SYSTEM.md §51`) with deterministic rules preferred first (`AI_SYSTEM.md §43`). The conflict is confined to the edge case of an ambiguous form mid-attempt invoking AI live, not the primary path. Still worth one clarifying sentence in `IMPLEMENTATION_ROADMAP.md §75` stating the scoring/classification role stays resident for the duration of an active attempt that has already invoked it. |
| A3 | The continuous worker's concurrency model (single cooperative loop with conditional cheap-checks, vs. genuinely concurrent threads/processes for discovery/evaluation/maintenance) is never named | `ARCHITECTURE_REDESIGN_FINAL.md §19`, `WORKFLOW_ENGINE.md §47`, `IMPLEMENTATION_ROADMAP.md §88-89` | All three documents present the worker as one linear diagram, while `IMPLEMENTATION_ROADMAP.md §89` separately requires discovery to "refresh independently of application execution" and not "starve" live applications (§90/§93). This is resolvable within either a single-threaded design (cheap per-iteration checks that skip expensive work, per `WORKFLOW_ENGINE.md §47`'s own caveat: "Expensive stages do not run unnecessarily when no work requires them") or a multi-threaded one; `SYSTEM_RULES.md §39` already classifies "internal code organization" as not requiring architecture review, so this is legitimately an implementation choice, not a missing architectural decision — but the diagrams alone could mislead an implementer into building a literal blocking loop that then fails the non-starvation requirement. Worth one sentence in `IMPLEMENTATION_ROADMAP.md §88` naming this explicitly as an open implementation choice. |

---

## 6. Missing-Contract Register

| ID | Missing contract | Where it should live | Severity |
|---|---|---|---|
| MC1 | `responses.classification` has two unreconciled taxonomies (see §8 below) | `DATA_MODEL.md §11.3` / `WORKFLOW_ENGINE.md §62` | HIGH (new finding, this pass) |
| MC2 | No notification/routing rule for a plain acknowledgement email (see §8 below) | `WORKFLOW_ENGINE.md §62` | HIGH (new finding, this pass) |
| MC3 | No operator recovery procedure for Gmail-watcher authentication/connection failure (see §9 below) | `EXECUTION_PROTOCOL.md §74` | HIGH (new finding, this pass) |
| MC4 | Channel recovery criteria (duplicate of §4.3, listed here for completeness of the register) | `BROWSER_SYSTEM.md §103` | CRITICAL |
| MC5 | Joint Ollama/browser RAM ceiling (duplicate of §4.4) | `SYSTEM_RULES.md` | CRITICAL |

---

## 7. Resource-Arbitration Verification

| Resource | Priority/ordering specified? | Numeric thresholds specified? | Verdict |
|---|---|---|---|
| **Ollama** | Yes — `AI_SYSTEM.md §72` (one expensive generative inference at a time), `§74` (active browser work outranks background scoring), `§64` (serial model scheduling) | No — deliberately deferred, `AI_SYSTEM.md §70/§110`: "resource feasibility is established on the actual host," "model benchmarking... on the real laptop" | Adequate. Numeric deferral is consistent, intentional project policy (see §12 of this report), not an oversight. |
| **Browser** | Yes — `BROWSER_SYSTEM.md §8` (1 worker, 1 active attempt baseline), `§128` (resource backpressure examples) | No — `BROWSER_SYSTEM.md §83`: "Do not impose an arbitrary architecture rule such as an 800 MB browser ceiling. Use measured host behavior." | Adequate, same reasoning. |
| **SQLite** | Yes — `SYSTEM_RULES.md §26` (WAL, `BEGIN IMMEDIATE`, bounded retry on busy), fencing via `current_attempt_id` (`DATA_MODEL.md §19.1`) | Partially — `MAX_ATTEMPTS = 3` is a frozen concrete number (`DATA_MODEL.md §7.3`); busy-retry backoff duration is deferred | Adequate. Correctness-critical numbers are frozen; pure timing values are deferred, consistent with the project-wide pattern. |
| **Scheduler** | Yes, fully — strict age cascade with concrete literal band values (`DATA_MODEL.md §5.6/§27`), `READY_RESERVE_TARGET = 300` is a frozen number | Yes, where it matters (reserve target, age-band hour boundaries are exact: 0–72h/>72–168h/>168–336h/>336–504h, `ARCHITECTURE_REDESIGN_FINAL.md §3.2`) | Fully specified. |
| **Ollama ↔ Browser joint ceiling** | **No** — see §4.4 | **No** | **Gap — CRITICAL, §4.4.** This is the one resource-arbitration case where even the qualitative priority rule is incomplete, because it requires combining two independently-measured values that neither document's own arbitration rule references together. |

**Conclusion:** Resource arbitration is fully and consistently specified at the *policy* level (what takes priority over what) in every case. Numeric thresholds are consistently and deliberately deferred to measured, real-host config for everything except the handful of values that are genuinely correctness-critical (attempt cap, reserve target, age-band boundaries, daily cap) — this is a coherent, repeatedly-stated design philosophy (`ARCHITECTURE_REDESIGN_FINAL.md §13.3/§21.2`, `MASTER_PLAN.md §20`, `SYSTEM_RULES.md §39`, `BROWSER_SYSTEM.md §83`), not an accidental gap, and the methodology for establishing those numbers is itself fully specified (`IMPLEMENTATION_ROADMAP.md §22` M0 Resource Baseline; M3/M4 exit gates require "resource behavior is measurable" / "resource envelope measured"). The single exception is the Ollama↔browser *joint* ceiling (§4.4), which is missing even at the policy level.

---

## 8. Notification-System Verification

The four-tier severity model (`Ignore / Log / Telegram Notification / High Priority Telegram Notification`) is defined exactly once, in `WORKFLOW_ENGINE.md §61` (itself sourced from `SYSTEM_RULES.md §31`), and every other reference in the document set names a tier rather than restating the model — confirmed by reading every citing section (`WORKFLOW_ENGINE.md §62/§68`, `EXECUTION_PROTOCOL.md §§41-45, §56, §74.1-§74.11`). The fixed path (Company → Platform → Gmail → Hermes → Telegram for employer-derived signals; direct Hermes → Telegram for internal/operational events) is consistently invoked and the distinction between the two paths is explicit (`EXECUTION_PROTOCOL.md §56`).

**Gap found (new, this pass):** `DATA_MODEL.md §11.3` defines `responses.classification` with "at minimum: `positive, rejection, ack, other`." `WORKFLOW_ENGINE.md §62`, which is where classification is actually routed to a notification tier, uses a **different** four-category vocabulary: `screening-adjacent follow-up`, `interview/salary/offer/contract/legal-identity-document signal`, `rejection`, `ambiguous/unclassifiable`. Only `rejection` matches verbatim between the two lists. Unlike `notification_level` (`DATA_MODEL.md §11.6`, which explicitly says "must use that exact wording" from `WORKFLOW_ENGINE.md §61`), `§11.3` does not cross-reference `§62` as authoritative, and the two taxonomies were evidently written independently.

Concretely: an `ack` email (e.g., an automated "we received your application" receipt — one of the most common response types in practice) has **no routing rule anywhere in `WORKFLOW_ENGINE.md §62`**. It is not a follow-up request, not a human-required signal, not a rejection, and not meaningfully "ambiguous" (it is clearly classified as an acknowledgement, just not actionable). An implementer has to invent what notification tier, if any, an `ack` email receives.

**Smallest correction:** Reconcile the two lists by making `WORKFLOW_ENGINE.md §62`'s four categories authoritative for `responses.classification` (consistent with the established pattern that workflow routing semantics are owned by `WORKFLOW_ENGINE.md`, `DATA_MODEL.md §5.9`'s own pattern), update `DATA_MODEL.md §11.3` to cross-reference `§62` by exact wording the way `§11.6` already does for `notification_level`, and add a fifth category to `§62`: `acknowledgement` (automated receipt, no action implied) → terminal, no action; **Notification: `Ignore`** (routine, high-volume, non-actionable — consistent with the existing rule that routine/expected events get `Ignore`, `WORKFLOW_ENGINE.md §61`'s own example is "a healthy claim").

---

## 9. Gmail Classification Verification

Core response classification/correlation logic is well specified: `WORKFLOW_ENGINE.md §62` gives an explicit anti-false-positive rule ("Generic phrases are not proof of application or interview status"), `DATA_MODEL.md §11.4` lists concrete correlation signals (employer identity, role title, application identifier, ATS/provider marker, known sender, timestamp relationship) and explicitly forbids correlating on bare generic phrases like "no-reply" or "recommended jobs" (`DATA_MODEL.md §11.4`, `MASTER_PLAN.md §18`, `SYSTEM_RULES.md §31` all repeat this consistently). The automation boundary that classification must respect (`AI_SYSTEM.md §28`: resume/portfolio/project responses automatable; interview/offer/contract/legal decisions forbidden and must route to `MANUAL_REVIEW`) is stated once and correctly cross-referenced everywhere it's invoked (`WORKFLOW_ENGINE.md §60/§62`).

**Two gaps found:**

1. **Classification taxonomy mismatch + missing `ack` rule** — see §8 above (MC1/MC2). This is the one genuine specification hole in the Gmail classification system itself.
2. **No operator procedure for the watcher's own failure** — `EXECUTION_PROTOCOL.md §74` has 11 detailed operator-recovery subsections (`§74.1`–`§74.11`) covering DB corruption, `MANUAL_REVIEW` triage, systemd failure, `AUTH_EXPIRED` channel pause, security blocks, backup-restore failure, zero-claim diagnosis, model failure, resource exhaustion, and stuck attempts — but none for the Gmail IMAP watcher's own authentication or connection failure, despite Gmail being named as a verified, critical, independent support component throughout (`MASTER_PLAN.md §5`: "Gmail IMAP watcher" listed among verified/historically-proven components; `WORKFLOW_ENGINE.md §61`: "failure of the watcher must not stop application processing"). The functional-continuity requirement is stated, but there is no notification severity assigned to this specific failure and no recovery procedure (e.g., regenerating an expired Gmail App Password) analogous to `§74.5`'s channel-auth-recovery pattern.

   **Smallest correction:** Add `EXECUTION_PROTOCOL.md §74.12`, modeled directly on the existing `§74.5` pattern: Notification `Telegram Notification` (sent via the direct Hermes→Telegram path per `§56`, since this is an internal/operational event, not an employer-response notification — and notably, this failure is also the one case where the Company→Platform→Gmail→Hermes→Telegram path cannot carry the notification, because Gmail itself is down); recovery steps: confirm it's a genuine auth/connection failure and not a transient blip (consistent with `§61`'s continuity requirement), regenerate the Gmail App Password through the normal account flow if expired/revoked, update the credential file, restart only the response-watcher component (not the whole service, consistent with `SYSTEM_RULES.md §31`'s independence rule), and rely on `message_id` uniqueness (`DATA_MODEL.md §11.2/§18`) to safely resume ingesting any backlog without manual replay.

---

## 10. Recovery-System Verification

Crash/recovery logic is the strongest-specified subsystem in the document set. `execution_phase` (`DATA_MODEL.md §7.5`) gives a clean, monotonic, durable answer to "did external work begin," consumed identically and without drift by `WORKFLOW_ENGINE.md §41-45` and `BROWSER_SYSTEM.md §70-73`. Lease fencing (`DATA_MODEL.md §19.1`, `WORKFLOW_ENGINE.md §105`) correctly closes the late-write race described in `§104`. The 11-item operator-procedure section (`EXECUTION_PROTOCOL.md §74`) is thorough and internally consistent, reads evidence the same way the system itself does, and explicitly forbids the dangerous shortcuts an operator might otherwise take (`§74.4`: never hand-edit `application_attempts.outcome`, never delete rows, never restore a snapshot for an ordinary crash).

**One gap re-confirmed from the prior audit, unchanged:** channel-level recovery (§4.3 above) — this is the one place where *forward* recovery (an individual attempt recovering from a crash) is fully specified but *channel-level* recovery (a route returning to service after a degrade) is not.

**One gap found (new, this pass):** the Gmail-watcher-specific recovery procedure (§9 above).

No other recovery gaps were found; the remaining 9 of `§74`'s 11 procedures were each re-checked against their cited upstream sections (`WORKFLOW_ENGINE.md §44/§45/§76`, `DATA_MODEL.md §3.1/§25/§26`, `AI_SYSTEM.md §77/§85`, `SYSTEM_RULES.md §24/§26/§32`) and each citation resolves correctly to text that actually supports the claim made.

---

## 11. Cross-Document Consistency Matrix

| Category | Status | Evidence |
|---|---|---|
| Opportunity lifecycle enum | ✅ Consistent (vocabulary and transitions) | `DATA_MODEL.md §5.9`, `BROWSER_SYSTEM.md §131`, `IMPLEMENTATION_ROADMAP.md §34` match exactly; `WORKFLOW_ENGINE.md §68`'s Transition Table (confirmed present and complete in this pass — this closes what the prior audit flagged as a missing outcome→state mapping) |
| Attempt-outcome enum (core docs) | ✅ Consistent | `DATA_MODEL.md §7.4`, `BROWSER_SYSTEM.md §131`, `IMPLEMENTATION_ROADMAP.md §34` agree exactly |
| Attempt-outcome enum (narrative prose) | ❌ Inconsistent, unresolved | `WORKFLOW_ENGINE.md §§53-59, §139` token drift (§4.8); `ARCHITECTURE_REDESIGN_FINAL.md §1` diagram (§4.6) |
| `channel_health.status` enum | ❌ Inconsistent, unresolved | `BROWSER_SYSTEM.md` internal drift (§4.9); recovery direction entirely undefined (§4.3) |
| `READY_RESERVE` predicate | ❌ Incorrect as written, unresolved | §4.1 |
| Retry-eligibility predicate | ✅ Consistent once both halves are read together | `DATA_MODEL.md §26` (timing half) + `WORKFLOW_ENGINE.md §22` (full predicate) correctly cross-reference — but note §4.1 is a *different* predicate (reserve counting) that was supposed to mirror this one and doesn't |
| Attempt-vs-tailoring-failure counting | ❌ Unresolved | §4.2 |
| `current_attempt_id` fencing | ✅ Consistent | `DATA_MODEL.md §19.1`, `WORKFLOW_ENGINE.md §105` |
| `execution_phase` durability | ✅ Consistent | `DATA_MODEL.md §7.5` and `BROWSER_SYSTEM.md §70-72` match exactly, including the synchronous-write guarantee |
| Notification severity model | ✅ Consistent, defined once | `SYSTEM_RULES.md §31` → `WORKFLOW_ENGINE.md §61` → cited by name everywhere else |
| `responses.classification` | ❌ Inconsistent, unresolved (new finding) | §8 above |
| WAL checkpoint ownership | ✅ Fixed since prior audit | `SYSTEM_RULES.md §26`, `WORKFLOW_ENGINE.md §76` — newly present, resolves the prior audit's G3-011 |
| `daily_limits` platform counters | ✅ Fixed since prior audit | `DATA_MODEL.md §12.2` — `linkedin_count` removed, resolves prior G1-004 |
| Resource arbitration (Ollama↔browser joint ceiling) | ❌ Unresolved | §4.4, §7 |
| Channel-health recovery | ❌ Unresolved | §4.3 |

---

## 12. Implementation Blocker Matrix

| # | Blocker | Blocks | Confidence | Fix cost |
|---|---|---|---|---|
| 1 | `READY_RESERVE` overcounts `EVALUATING` backlog (§4.1) | Any M1/M2 work that reads reserve to gate refill or reports it as an observability metric | CONFIRMED — structural, not edge-case | One clause change in one section |
| 2 | Tailoring-failure attempt-counting (§4.2) | M2 retry policy implementation; will misbehave the first time Ollama is briefly unavailable during a claim | CONFIRMED | One sentence in two sections |
| 3 | Channel recovery undefined (§4.3) | M8 (Ashby/deferred-channel re-evaluation) and any channel that degrades in production before then | CONFIRMED | New subsection, ~5 rules |
| 4 | Joint RAM ceiling undefined (§4.4) | M9 continuous-worker integration and M12 24/7 stability validation | CONFIRMED | One cross-cutting rule |
| 5 | `responses.classification` taxonomy + missing `ack` rule (§8) | M5/M9 response-monitoring integration | CONFIRMED (new) | Reconcile two lists, add one category |
| 6 | Missing Gmail-watcher recovery procedure (§9) | Day-1 operations once deployed (an operator-facing document, zero code-architecture impact) | CONFIRMED (new) | One new `§74.x` subsection |
| 7 | Enum/token drift (§4.6, §4.8, §4.9) | Code review / static-consistency tooling, not runtime correctness directly | CONFIRMED, cosmetic-but-real | Find/replace across named sections |
| 8 | Frozen-doc revision-log gap (§4.5) | Process/governance only | CONFIRMED | One log line |

None of the 8 items above requires new architecture, a new subsystem, a new platform, or touches any item on the Frozen Non-Goals list (`IMPLEMENTATION_ROADMAP.md §5`).

---

## 13. Exact Patch Instructions

Ordered by priority (CRITICAL first). Each patch is additive or a narrow in-place replacement; none requires renumbering a document or touching an unrelated section.

### Patch 1 — `DATA_MODEL.md §26`
Replace:
```
AND application_state NOT IN (
    APPLYING,
    AWAITING_RECONCILIATION,
    COMPLETED,
    MANUAL_REVIEW,
    EXPIRED
)
```
with:
```
AND application_state = READY
```
Also update `ARCHITECTURE_REDESIGN_FINAL...FROZEN.md §8.1`'s prose ("available for ranking or application") to read "in `application_state = READY`" so the top-authority document states the same condition unambiguously.

### Patch 2 — `WORKFLOW_ENGINE.md §22` and `§30`
Add to `§22`, immediately after the predicate list: "An attempt counts against `attempts < 3` above only if its `execution_phase` (`DATA_MODEL.md §7.5`) advanced past `NOT_STARTED` before finishing — i.e., some external browser/network action toward the target site began. A tailoring failure that never leaves `NOT_STARTED` does not consume a slot in this count, consistent with §30."
Add to `§30`, after "Do not consume an application attempt unless actual external application work began": "Concretely, its `execution_phase` remains `NOT_STARTED`, which is what `§22`'s retry-eligibility count excludes."

### Patch 3 — `BROWSER_SYSTEM.md`, new `§103.1`
Insert after §103:
```
### 103.1 Channel Recovery

A channel degrade must have a defined reactivation path; none is implicit.

AUTH_EXPIRED    -> clears only via successful re-authentication (EXECUTION_PROTOCOL.md §74.5)
RATE_LIMITED    -> clears when channel_health.cooldown_until elapses
NETWORK_UNAVAILABLE -> clears when cooldown_until elapses and the next health probe succeeds
FORM_SCHEMA_CHANGED -> does not self-heal on a timer; requires an explicit driver fix before clearing
ANTIBOT_BLOCKED -> requires minimum cooldown AND a successful read-only, non-mutating
                   probe before resuming submission attempts on that route
```

### Patch 4 — `SYSTEM_RULES.md`, addition to `§24` (Local AI Responsibilities) or new short section
Add: "Before loading or reloading a generative/scoring model, check current browser process RSS (`BROWSER_SYSTEM.md §81`); before opening a new browser context mid-cycle, check current Ollama RSS. If combined measured RSS would exceed the safe ceiling established during `IMPLEMENTATION_ROADMAP.md §22`'s resource baseline, the lower-priority operation defers per the existing priority order (`AI_SYSTEM.md §74`)."

### Patch 5 — `ARCHITECTURE_REDESIGN_FINAL...FROZEN.md §1`
Replace the attempt-outcome branch list:
```
    +--> SUBMITTED (confirmed evidence)
    +--> ALREADY_APPLIED
    +--> SUBMISSION_UNCONFIRMED (never blindly replay)
    +--> RETRYABLE_FAILURE
    +--> CHANNEL_BLOCKED / UNSUPPORTED_CHANNEL
    +--> EXPIRED (>21d)
```
with:
```
    +--> SUBMITTED (confirmed evidence)
    +--> ALREADY_APPLIED
    +--> SUBMISSION_UNCONFIRMED (never blindly replay)
    +--> RETRYABLE_FAILURE
    +--> CHANNEL_BLOCKED / UNSUPPORTED_CHANNEL
    +--> TERMINAL_FAILURE

    (opportunity-level EXPIRED, a separate dimension, is covered in §5.1/§5.9 of DATA_MODEL.md)
```

### Patch 6 — `EXECUTION_PROTOCOL.md §74.6` step 3
Replace: "leave `channel_health` at its worker-set value (`CHANNEL_BLOCKED` / route-dependent, `WORKFLOW_ENGINE.md §67`)"
with: "leave `channel_health.status` at its worker-set value (`ANTIBOT_BLOCKED`, `DATA_MODEL.md §8.3`; this is the channel-health dimension, distinct from the attempt-outcome `CHANNEL_BLOCKED` value per `WORKFLOW_ENGINE.md §67`)"

### Patch 7 — `WORKFLOW_ENGINE.md §§53-56, §59, §139`
- §53, §139: replace `BLOCKED_ANTIBOT` with explicit two-field language: "record attempt outcome = `CHANNEL_BLOCKED`; set `channel_health.status = ANTIBOT_BLOCKED`."
- §54: replace `FORM_CHANGED` with `FORM_SCHEMA_CHANGED`.
- §55: replace `AUTH_EXPIRED / LOGIN_REQUIRED` with `AUTH_EXPIRED` alone (drop the undefined alternate).
- §56: replace `MODEL_UNAVAILABLE / MODEL_TIMEOUT` with the terms `AI_SYSTEM.md §76` actually defines ("runtime unavailable", "timeout"), or add these two as recognized aliases in `AI_SYSTEM.md §76` itself.
- §59: remove `PERMANENTLY_INVALID` from the list, or if a genuinely new terminal condition is intended, add it to `DATA_MODEL.md §5.9`'s enum first and cite it from there.

### Patch 8 — `BROWSER_SYSTEM.md §41, §68, §136`
Replace `ACCOUNT_REQUIRED` with `ACCOUNT_WALL` and `NETWORK_ERROR` with `NETWORK_UNAVAILABLE` throughout, matching this document's own §103 usage and `DATA_MODEL.md §8.3`.

### Patch 9 — `BROWSER_SYSTEM.md`, addition beside `§56`
Add: "A response with HTTP 200 and an ordinary page shape that nonetheless contains a known per-channel rejection phrase (e.g., Ashby's observed 'flagged as possible spam' text) must be classified as `ANTIBOT_BLOCKED` / attempt outcome `CHANNEL_BLOCKED`, never as a confirmation or passable ambiguous state. Maintain a small per-channel rejection-phrase list and check it against post-submit page text before accepting any confirmation-shaped signal (§62 Evidence Hierarchy) — a rejection-phrase match overrides weak confirmation signals."

### Patch 10 — `DATA_MODEL.md §11.3` and `WORKFLOW_ENGINE.md §62`
In `DATA_MODEL.md §11.3`, replace "At minimum: `positive, rejection, ack, other`" with: "Allowed values are the four categories defined in `WORKFLOW_ENGINE.md §62` and must use that exact wording, consistent with `§11.6`'s rule for `notification_level`: `screening_follow_up`, `human_required_signal`, `rejection`, `acknowledgement`, `ambiguous`." (five values, see next change)

In `WORKFLOW_ENGINE.md §62`, add a fifth routing row:
```
acknowledgement (automated "application received" / no-action receipt)
    -> terminal, no action; Notification: Ignore
```

### Patch 11 — `EXECUTION_PROTOCOL.md`, new `§74.12`
```
## 74.12 Gmail watcher authentication/connection failure

Notification: Telegram Notification — sent via the direct Hermes -> Telegram
path (EXECUTION_PROTOCOL.md §56), since Gmail itself being unavailable is
why the Company -> Platform -> Gmail -> Hermes -> Telegram path cannot be
used for this specific failure's own notification.

~~~
1. confirm this is a genuine auth/connection failure in watcher logs, not a
   transient blip (WORKFLOW_ENGINE.md §61: watcher failure must not stop
   application processing)
2. if the Gmail App Password has expired or been revoked, generate a new
   one through the normal Google account flow and update the credential
   file (chmod 600); never weaken IMAP auth to work around this
3. restart only the response-watcher component -- this does not require
   restarting hermes-continuous.service, since response monitoring is an
   independent support path (SYSTEM_RULES.md §31)
4. confirm the watcher resumes ingesting messages; any backlog since the
   outage began is safely re-ingestible via message_id uniqueness
   (DATA_MODEL.md §11.2/§18) without manual replay
~~~
```

---

## 14. Final Go/No-Go Decision

**IMPLEMENTATION READY AFTER SPECIFIC FIXES.**

Apply Patches 1–4 (the CRITICAL items) before any M1/M2/M9 code is written against `DATA_MODEL.md §26`, `WORKFLOW_ENGINE.md §24/§30/§47`, or `BROWSER_SYSTEM.md §103` — these are the three sections where code written against the current text would reproduce a real bug, not a stylistic inconsistency. Patches 5–9 (HIGH, enum/diagram drift) should be applied before M2 (first code that touches these enums) but do not block earlier work (M0/M1 data-foundation work does not depend on them). Patches 10–11 (Gmail/notification gaps) should be applied before M5/M9 (response-monitoring integration) and before first production deployment respectively, but block nothing earlier.

No patch here requires reopening the frozen architecture, adding a platform, adding a subsystem, or any item on the Forbidden Assumptions / Frozen Non-Goals lists. All 11 patches are documentation-only corrections inside the existing 9-document structure.
