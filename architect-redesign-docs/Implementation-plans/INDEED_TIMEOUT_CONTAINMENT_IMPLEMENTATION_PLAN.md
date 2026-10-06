# Hermes Indeed Timeout Containment — Implementation Plan

**Status:** Ready for implementation; deployment is gated on every acceptance test below.  
**Scope:** Five verified blockers on the active legacy Indeed path only: browser ownership, bounded unwind, durable submission risk, authoritative timeout attribution, and duplicate-safe recovery.  
**Out of scope:** Scheduling, queue policy, worker topology, metrics redesign, other application channels, and enabling the workflow engine.

## Architecture Report

### Executive summary

Implement timeout containment inside the existing legacy path. The plan uses one browser instance per Indeed attempt, a deadline controller that can terminate only that verified instance, durable phase state on the legacy `jobs` row, and phase-aware result/recovery handling. A kill or disconnect must stop helper retries and preserve the timeout signal until persistence. Any attempt whose final submit action may have been dispatched remains `submission_unconfirmed` and is not automatically retried.

The draft design is corrected in four material ways:

1. A unique profile does not prove a unique DrissionPage browser. The installed default endpoint is `127.0.0.1:9222` with `auto_port=False`; two pages using different profiles were observed attaching to the same PID/address. Every attempt therefore needs a distinct, verified DevTools endpoint as well as a unique profile.
2. The legacy database stores jobs in `jobs`, not an `applications` table. The legacy recovery function is `apply.reset_stuck_applying()` in `src/apply.py`; `src/recovery.py` and `src/config.py` do not exist.
3. An outer `PageDisconnectedError` handler is insufficient. The actual click helper catches browser errors and retries. Timeout state must be checked at every browser-operation catch/retry boundary.
4. The phase written before the click means **submission may have been dispatched**. It is intentionally conservative: it does not assert that Indeed received the request.

### 1. Exclusive browser ownership

For each claimed Indeed attempt:

- Create a unique, private profile directory and a unique DevTools endpoint. Do not use DrissionPage’s default endpoint or attach to a pre-existing endpoint.
- Launch the browser through the existing Indeed launch boundary in `src/indeed_apply.py`. Capture `page.process_id`, the endpoint, profile path, and process creation identity immediately.
- Verify that the connected browser process command line identifies the expected endpoint and profile. If the endpoint was already occupied, the process identity is missing, or the observed process does not match the launch, fail closed and do not terminate it.
- Before signaling a process, verify that its identity still matches the captured process generation. The root and every descendant eligible for termination must be attributable to this attempt. PID alone is not a process-generation identity.
- Keep the profile until the browser and owned descendants are confirmed stopped and DrissionPage cleanup has completed. Do not remove profile locks manually. If cleanup cannot be confirmed, retain the profile and report cleanup failure rather than deleting data under a live process.

Unique profiles affect authentication. The current code relies on a persistent profile and may seed cookies from `output/indeed_session.json`; it also caches Indeed login-check state at module scope. The implementation must verify authenticated-session behavior with the chosen profile lifecycle and ensure that a cached login result cannot stand in for checking a new profile. This is a pre-deployment acceptance gate.

### 2. Deadline and termination lifecycle

- Start one monotonic deadline controller immediately after successful browser launch, as required by this plan. This intentionally expands the current six-minute window, which begins after job-page navigation, to include session setup and navigation. Keep the duration at the existing `MAX_APPLY_SECONDS`; do not change queue or run budgets.
- The controller records timeout as an irreversible per-attempt signal before initiating termination. Use the specified SIGTERM, two-second grace, then SIGKILL escalation only after validating the process identities and termination scope. Re-enumerate and verify owned descendants; never signal a PID based only on an earlier numeric value.
- Stop and join the controller as part of every normal completion path, before ordinary browser shutdown. A controller that has already timed out remains authoritative even if `page.quit()` or another cleanup call also raises.
- The watchdog is per attempt. It must not outlive the attempt, race into a later attempt, or overwrite a confirmed result observed before the deadline.

The runtime audit observed fast `PageDisconnectedError` unwind for isolated navigation, interaction, upload, click, page-evaluation, and screenshot-during-renderer-stall calls. It also observed a Hermes helper still retrying after disconnection and returning only after about 13 seconds. Acceptance therefore covers the complete Hermes call stack, not just an individual DrissionPage call.

### 3. Durable submission-risk phases

Add a nullable phase column to the legacy `jobs` table, bound to the current `attempts` value. Do not add a column to a nonexistent `applications` table or reuse the engine’s separate `application_attempts` ledger.

Phases:

| Phase | Meaning | Recovery action |
|---|---|---|
| `PRE_SUBMIT` | This attempt has not entered the final submit action. | Safe to requeue if attempts remain; otherwise fail according to the existing cap. |
| `SUBMIT_MAY_HAVE_DISPATCHED` | Durable marker committed before invoking the final submit click. The request may or may not have reached Indeed. | Persist `submission_unconfirmed`; never automatically retry. |
| `CONFIRMATION_PENDING` | The click returned, but success has not yet been durably confirmed. | Persist `submission_unconfirmed`; never automatically retry. |
| `CONFIRMED` | Success evidence and `status='submitted'` were persisted together. | Keep terminal `submitted`; never downgrade due to a late watchdog. |

The claim operation atomically increments `attempts`, sets `status='applying'`, and sets the phase to `PRE_SUBMIT`. Phase writes are conditional on the job row still being `applying` for the same attempt count. Commit `SUBMIT_MAY_HAVE_DISPATCHED` before the final click; if that commit fails, do not click. If a crash occurs after the commit but before dispatch, recovery conservatively records unconfirmed rather than risking a duplicate.

The legacy phase is per current attempt, not a history ledger. Any attempt history requirement beyond what is needed for safe recovery is out of scope.

### 4. Authoritative timeout attribution

Use a per-attempt timeout/abort context shared by the driver and its helpers. A `HardTimeoutError` may carry that context to the applier boundary, but the design must not rely only on catching `PageDisconnectedError` in `_drive_application()`.

- Browser-operation handlers must check the timeout/abort context before swallowing an exception, retrying, sleeping, or converting the error to “no control.” If timeout is set, propagate the authoritative timeout signal immediately.
- Retry/sleep loops must be interruptible by the attempt abort signal. Remove or short-circuit post-disconnect retries; do not add a generic five-second wrapper that leaves existing catches able to continue.
- At `run_indeed_apply()` result mapping, classify from the watchdog timeout signal plus the durable phase: `PRE_SUBMIT` becomes a retryable timeout failure; either submit-risk phase becomes `SUBMISSION_UNCONFIRMED`. Existing confirmed success remains `SUBMITTED`.
- Preserve this classification through `route()`, `apply_one()`, and `record_result()`. The outer `apply_one()` handler must not convert the timeout into generic `FAILED`.
- Cleanup exceptions must not replace the application outcome. Cleanup status can be recorded separately in the result detail, but must not turn an ambiguous submission into a retryable failure.

### 5. Phase-aware recovery

Update the legacy `reset_stuck_applying()` recovery path. Recovery evaluates phase before attempt-count handling:

1. `SUBMIT_MAY_HAVE_DISPATCHED` or `CONFIRMATION_PENDING` → set `submission_unconfirmed`, preserve the attempt count, and do not requeue, regardless of remaining attempts.
2. `CONFIRMED` → preserve `submitted`. The success status and confirmed phase are written atomically; a mismatched `applying`/`CONFIRMED` row is an invariant violation and must fail closed for reconciliation.
3. `PRE_SUBMIT` → reset to `tailored` only when attempts remain; otherwise set `failed` as today.
4. Missing/unknown phase on a stale `applying` row → fail closed as `submission_unconfirmed`; never infer “not submitted” from browser disappearance or a missing phase.

`SUBMISSION_UNCONFIRMED` already exists in `src/states.py`; it must remain excluded from `RETRYABLE`. The dedupe check is not a substitute for same-row recovery safety.

## Implementation Readiness Decision

**READY FOR IMPLEMENTATION**, with the plan’s acceptance tests as mandatory merge/deployment gates. The design directly addresses each verified failure: unique endpoint plus profile and process-generation validation for ownership; abort-aware helper boundaries for unwind; a pre-click durable marker for submission ambiguity; timeout-state precedence through all result handlers; and phase-aware recovery that does not replay submit-risk attempts.

This is not a claim that the blockers are already resolved in the repository. The code is not deployment-ready until every test below passes, including the authenticated-profile check and the dispatch-before-click-return failure case.

## Final Implementation Plan

### Code change map

| File | Required changes |
|---|---|
| `db/schema.sql` | Add the legacy `jobs` phase column. Preserve additive migration compatibility. |
| `src/db.py` | Add the phase migration; atomically initialize phase during `claim_job()` and implement a conditional phase update bound to the current attempt. |
| `src/states.py` | Keep `SUBMISSION_UNCONFIRMED` non-retryable; add a typed transient timeout result only if needed by the existing `ApplyResult` contract. |
| `src/indeed_apply.py` | Launch with unique profile and endpoint; capture/verify browser identity; own the deadline controller lifecycle; stop retries after timeout; persist pre-click and post-click phases; preserve timeout precedence through browser helpers and cleanup. |
| `src/apply.py` | Pass attempt identity/phase persistence into the legacy Indeed call; preserve timeout classification in `apply_one()`; make `record_result()` atomically persist `status='submitted'` with `CONFIRMED`; make `reset_stuck_applying()` phase-aware. |
| New `src/browser_watchdog.py` | Per-attempt monotonic deadline, owned-process verification, termination escalation, timeout signal, bounded stop/join, and cleanup result. No generic worker or scheduler changes. |

Do not create `src/recovery.py` or `src/config.py` for this work. Do not enable `engine.enabled`; the engine’s recovery model is separate and out of scope.

### Execution order

1. **Legacy schema and persistence:** Add phase migration and attempt-fenced updates. Test claim initialization, conditional updates, migration of existing rows, and unknown-phase recovery. Existing stale `applying` rows must be handled conservatively before rollout.
2. **Exclusive launch:** Add unique profile and endpoint allocation; capture process generation and verify process command line. Test two concurrent launches and a decoy already occupying the default endpoint. Verify a new profile authenticates safely or stop before enabling ephemeral profiles.
3. **Watchdog lifecycle:** Implement deadline signal, termination escalation, identity revalidation, tree verification, stop/join, and cleanup. Test root/descendant outcome, process-generation mismatch, occupied endpoint, natural exit, and timeout/completion race.
4. **Helper short-circuiting:** Audit every browser-operation `except`, retry loop, and sleep in `src/indeed_apply.py`. Thread the per-attempt abort context through relevant helpers. Prove kill during control discovery returns within the bound, not after the existing retry/sleep sequence.
5. **Submission phase and classification:** Commit submit-risk phase before click; commit confirmation-pending after click returns; preserve success evidence. Exercise actual local request dispatch before click return, then kill Chrome and inspect result/DB state.
6. **Recovery integration:** Update `reset_stuck_applying()` using phase-before-attempt-count ordering. Simulate worker termination and restart for every phase; assert attempt counts, persisted states, and queue eligibility.
7. **Full-path validation:** Run the complete claim → launch → local submit dispatch → kill → unwind → persist → restart → recovery scenario. Do not enable deployment if any invariant fails.

### Verification matrix

| Blocker | Scenario | Pass criteria |
|---|---|---|
| Ownership | Launch two concurrent attempts plus a decoy browser; also occupy the default DrissionPage endpoint. | Each attempt connects only to its own verified process/profile/endpoint. A pre-existing endpoint causes fail-closed behavior; killing one attempt leaves every decoy alive and responsive. PID generation is checked before signaling. |
| Unwind | Kill during navigation, text/form interaction, upload, intermediate click, final click, evaluation, screenshot during a renderer stall, and shutdown. Also kill during `_click_next_or_submit()` control discovery/retry. | Every caller and helper exits within five seconds of forced termination; no catch retries after abort; owned descendants and DrissionPage threads reach the measured cleanup state; a subsequent browser launch succeeds. |
| Submission boundary | Interrupt after phase commit but before click; after the local server receives dispatch but before click returns; after click return; and after confirmation observation. | No click occurs before phase commit. The first two submit-risk cases persist unconfirmed and never requeue. Confirmed success remains submitted through a watchdog race. |
| Attribution | Trigger kill at each browser-operation phase and run through actual `run_indeed_apply()` → `route()` → `apply_one()` → `record_result()`. | Pre-submit timeout remains a typed timeout/retryable pre-submit failure. Submit-risk timeout remains `SUBMISSION_UNCONFIRMED`. No case becomes `FORM_CHANGED`, generic retryable failure, swallowed success/failure, or missing persistence. |
| Recovery | Restart with each persisted phase and with a missing/unknown phase. | Submit-risk/unknown phases never requeue; pre-submit requeues only below the attempt cap; attempt counts do not reset; confirmed success is never downgraded. |
| Composition | Full failure simulation with a real local test endpoint recording the submission request. | After restart, DB state and retry eligibility match the recorded phase; no duplicate dispatch occurs on recovery. |

The previous test “kill immediately after click returns” is insufficient by itself: the known risk window is a request reaching the destination before the click call returns and before a post-click callback can execute.

### Rollback

- Stop new applications and identify every `applying` row before reverting code.
- Resolve rows in submit-risk or unknown phases to `submission_unconfirmed`; do not allow old recovery code to requeue them.
- Ensure no owned browser or descendant remains before deleting any temporary profile.
- Revert application code only while retaining the additive phase column and a recovery guard for submit-risk rows. Do not drop the phase column as part of rollback.
- Resume only after confirming no unresolved `applying` row can enter the old blind-reset path.

## Deferred Validation Register

**No safety-relevant validation is deferred.** Orphan processes, PID reuse, profile/session behavior, helper unwind, file descriptors, DrissionPage threads, and next-launch behavior are ownership, cleanup, or bounded-recovery concerns and must be measured before deployment. Post-deployment observation may supplement those tests but cannot replace them.
