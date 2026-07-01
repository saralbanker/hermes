---
name: debugging-master
description: "Use this skill when diagnosing any software bug, error, or unexpected behavior. Applies systematic fault isolation to find root cause before touching any code."
version: 1.0.0
triggers:
  - "bug"
  - "error"
  - "not working"
  - "broken"
  - "fix this"
  - "debug"
  - "exception"
  - "crash"
  - "@debugging-master"
token_budget: 4000
tools_required:
  - view_file
  - search_code
  - run_terminal
output_contract:
  format: "Root cause report + code fix + regression test"
  includes:
    - root-cause
    - evidence
    - fix
    - test
    - prevention
works_with:
  - code-synthesizer
  - test-generator
  - system-auditor
  - performance-optimizer
risk: medium
---

## Mission

Diagnose any software bug by applying systematic fault isolation — trace the symptom to root cause using evidence, form a testable hypothesis before touching any code, write a failing test that captures the bug, apply the minimal fix, and verify the fix prevents recurrence. Never guess. Never shotgun debug. Never change code without a hypothesis.

## When To Activate

- An error message, exception, or stack trace is reported
- Code produces wrong output but no error is thrown
- A feature "stopped working" after a change
- Intermittent / flaky behavior is observed
- **Anti-trigger**: Do NOT activate for performance issues (use `performance-optimizer`) or system-level failures spanning multiple services (use `system-auditor`)

## Core Concepts

### 1. Hypothesis Before Fix
Never change code before forming a testable hypothesis. Structure: "I think **X** is wrong because **Y**, and if I'm right, then **Z** will happen when I check." Changing code without a hypothesis is random mutation — it sometimes works, but you can't explain why, and the bug will return.

### 2. Binary Search Isolation
For unknown bug location, bisect the execution path. Confirm the bug exists at the midpoint of the call chain. Eliminate half the codebase each step. Three bisections on a 1000-line flow narrows to ~125 lines. Never read from line 1 to line 1000.

### 3. Minimal Reproducible Example
The bug must reproduce in isolation before fixing. If it only appears with 5 services running, the real bug is in the **interaction**, not the service. Strip away components until you find the minimum setup that triggers the bug. That setup IS your test case.

### 4. Heisenbugs
Bugs that disappear when observed (adding a console.log "fixes" it, debugger breakpoint changes timing) indicate race conditions, async ordering issues, or undefined behavior from timing. For these: add **deterministic** timestamps/sequence IDs to logs, not interactive breakpoints. Reproduce the exact sequence, then reason about ordering.

### 5. Test-First Fixing
Write a failing test that captures the bug BEFORE fixing it. The test is proof the bug existed. The fix makes the test pass. Without this, the bug can (and will) silently return in a future refactor. The test IS the documentation of the bug.

## Reasoning Graph

```
[INPUT: Error message / unexpected behavior]
  │
  ├─► [CLASSIFY: Do we have an error message?]
  │     │
  │     ├─► [BRANCH A: Error message exists]
  │     │     ├── Parse error type (TypeError / ReferenceError / NetworkError / etc.)
  │     │     ├── Find stack trace — identify FIRST frame in YOUR code (skip node_modules)
  │     │     ├── Read that file + function
  │     │     ├── Trace: what did the function expect vs. what did it receive?
  │     │     ├── Form hypothesis: "Bug is in [fn] because [reason]"
  │     │     ├── Write failing test
  │     │     ├── Apply fix → run test
  │     │     └── [VALIDATE: test passes + full suite passes]
  │     │
  │     ├─► [BRANCH B: Wrong behavior, no error]
  │     │     ├── Define expected vs actual behavior precisely
  │     │     │     └── "Expected: X. Got: Y. Difference: Z."
  │     │     ├── Add strategic logging at input/output of suspect functions
  │     │     ├── Binary search: does the problem exist at function boundary X?
  │     │     │     ├── Yes → problem is before X → move midpoint earlier
  │     │     │     └── No → problem is after X → move midpoint later
  │     │     ├── Isolate to single function → form hypothesis
  │     │     ├── Write failing test → apply fix
  │     │     └── [VALIDATE]
  │     │
  │     └─► [BRANCH C: Intermittent / flaky]
  │           ├── Assume async/timing issue FIRST
  │           ├── Look for: unhandled promise rejections, shared mutable state, race conditions
  │           ├── Search: `grep -rn "setTimeout\|setInterval\|Promise.all\|race" src/`
  │           ├── Add deterministic timestamps to logs
  │           ├── Reproduce 3x before fixing → form hypothesis
  │           └── [VALIDATE]
  │
  └─► [OUTPUT: Root cause + fix + test]
```

## Execution Steps

### Branch A: Error Message Exists (Most Common)

### Step 1: Capture the Error
Copy the full error message. Extract: error type, file path, line number, error text. Example:
```
TypeError: Cannot read properties of undefined (reading 'email')
    at getUserProfile (/src/services/user.ts:42:18)
    at handler (/src/routes/profile.ts:15:22)
```

### Step 2: Find YOUR Code
The first stack frame pointing to YOUR code (not `node_modules`) is line 42 of `user.ts`, function `getUserProfile`. That is the investigation starting point.

### Step 3: Read the Function
Open `user.ts:42`. What does `getUserProfile` expect at line 42? It's accessing `.email` on something that's `undefined`. What variable is it? Where should that variable have been set?

### Step 4: Trace Backwards
Who calls `getUserProfile`? `handler` in `profile.ts:15`. What does `handler` pass? Trace the argument — is it coming from `req.params`, `req.body`, a database query? Find where the undefined value originates.

### Step 5: Form Hypothesis
"The bug is in `getUserProfile` because `user` object from the database query is `undefined` when no user exists for the given ID. The function assumes the query always returns a result but doesn't handle the empty case."

### Step 6: Write Failing Test
```typescript
it('should_throw_NotFoundError_when_user_does_not_exist', async () => {
  await expect(getUserProfile('nonexistent-id'))
    .rejects.toThrow(NotFoundError);
});
```

### Step 7: Apply Fix
```typescript
const user = await db.user.findUnique({ where: { id } });
if (!user) throw new NotFoundError(`User ${id} not found`);
return user;
```

### Step 8: Verify
Run the new test — it should pass. Run the full test suite — no regressions. Add a comment: `// Fixed: handle missing user — see test should_throw_NotFoundError_when_user_does_not_exist`

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| `Cannot read properties of undefined (reading 'x')` | Object is null/undefined at call site | Trace where the object should have been set; add null guard or fix the source |
| `ECONNREFUSED 127.0.0.1:5432` | Database/service not running or wrong port | Verify service: `curl http://localhost:5432` or `docker ps` |
| `UnhandledPromiseRejection` | Async error with no `.catch()` or `try/catch` | Wrap the `await` in try/catch or add `.catch()` to the promise chain |
| Bug fixed locally, broken in CI | Missing env variable or different Node version | Compare `process.env` keys and `node -v` between local and CI |
| Fix works but test still fails | Test is asserting the wrong condition | Re-read the test: is it testing the bug symptom or the correct behavior? |
| `ENOENT: no such file or directory` | Hardcoded path works on dev machine, not in CI | Use `path.resolve(__dirname, ...)` or env-based config |

## Validation Gate

- [ ] Root cause identified (not just symptom — "undefined" is a symptom, "missing null check on DB query" is a root cause)
- [ ] Hypothesis was formed before any code was changed
- [ ] Failing test written that reproduces the bug
- [ ] Fix makes that test pass
- [ ] Full test suite still passes after fix
- [ ] Prevention noted (what structural change prevents this class of bug?)

## Output Contract

Root cause report containing:
- **Symptom**: What was observed (error message, wrong behavior)
- **Root cause**: What structural issue allowed the symptom (file:line, specific code)
- **Evidence**: Logs, stack trace, or reproduction steps that confirm the diagnosis
- **Fix**: The code change applied (minimal diff)
- **Test**: The test that proves the bug existed and is now fixed
- **Prevention**: How to prevent this class of bug (e.g., "add integration test for 404 cases on all endpoints")
