---
name: refactoring-specialist
description: "Use this skill when improving existing code quality without changing behavior. Detects code smells, ensures tests exist before touching code, and applies safe incremental refactoring patterns."
version: 1.0.0
triggers:
  - "refactor"
  - "clean up"
  - "code smell"
  - "technical debt"
  - "hard to read"
  - "too complex"
  - "@refactoring-specialist"
token_budget: 2500
tools_required:
  - view_file
  - search_code
  - run_terminal
output_contract:
  format: "Before/after diff + smell identified + tests confirming no regression"
  includes:
    - smell-identified
    - refactoring-applied
    - tests-passing
    - complexity-delta
works_with:
  - test-generator
  - architecture-analyst
  - code-synthesizer
  - documentation-writer
risk: medium
---

## Mission

Improve existing code quality without changing external behavior by detecting code smells using Fowler's taxonomy, ensuring tests exist before any refactoring begins, and applying safe, incremental, one-refactoring-at-a-time transformations. Each refactoring step is committed separately, verified by tests, and measurably reduces complexity. If tests don't exist, they are written first — refactoring without a safety net is not refactoring, it's rewriting.

## When To Activate

- User asks to clean up, refactor, or reduce technical debt
- Code is hard to read, understand, or modify
- Cyclomatic complexity or file length exceeds thresholds
- Code smells are suspected or reported by linters
- **Anti-trigger**: Do NOT activate for adding new features (use `code-synthesizer`) or fixing bugs that change behavior (use `debugging-master`)

## Core Concepts

### Fowler's Smell Taxonomy (Encoded)

| Smell | Detection | Threshold | Fix |
|-------|-----------|-----------|-----|
| **Long Method** | Function line count | >20 lines | Extract named sub-functions |
| **Large Class** | Class line count / method count | >200 lines or >7 public methods | Split by responsibility |
| **Duplicate Code** | Same logic in 2+ places | 3+ occurrences (Rule of Three) | Extract shared function |
| **Long Parameter List** | Function parameter count | >4 parameters | Introduce parameter object |
| **Divergent Change** | One class changes for multiple unrelated reasons | 2+ distinct change reasons | Split by reason for change |
| **Shotgun Surgery** | One feature change requires editing many files | 6+ files changed together | Consolidate into one module |
| **Feature Envy** | Method uses more of another class's data than its own | >50% external references | Move method to the data owner |
| **Primitive Obsession** | Using `string` for email, phone, status, money | Domain concepts as primitives | Create value objects/types |
| **Data Clumps** | Same 3+ fields passed together to multiple functions | 3+ functions with same params | Extract to a type/interface |

### Safe Refactoring Principles

1. **Tests First**: If tests don't exist, write characterization tests (tests that document current behavior, even if that behavior is wrong) before refactoring.
2. **One Refactoring Per Commit**: Apply one transformation, run tests, commit. If something breaks, revert exactly one step.
3. **Behavior Must Not Change**: Refactoring = same inputs produce same outputs. If a test fails, the refactoring changed behavior — revert.
4. **Strangler Fig Pattern**: For large legacy rewrites, build the new implementation alongside the old. Route traffic incrementally. Delete old code only when new code handles 100%.

## Reasoning Graph

```
[INPUT: Code to refactor]
  │
  ├─► [STEP 0: TESTS FIRST — MANDATORY]
  │     ├── Do tests exist for this code?
  │     │     ├── Yes → Run them, confirm they pass → proceed
  │     │     └── No → STOP → activate test-generator → write characterization tests
  │     └── Tests passing = safety net established
  │
  ├─► [CLASSIFY: Which smell?]
  │     │
  │     ├─► [BRANCH A: Long method / high complexity]
  │     │     ├── Find the "and" in what the function does
  │     │     ├── Each "and" = extraction point
  │     │     ├── Name extracted functions by INTENT, not mechanism
  │     │     │     └── calculateDiscount() not processStep2()
  │     │     ├── One extraction → run tests → commit
  │     │     └── [VALIDATE: complexity measurably reduced]
  │     │
  │     ├─► [BRANCH B: Duplicate code]
  │     │     ├── Find ALL occurrences (not just 2)
  │     │     ├── Extract shared function with typed parameters
  │     │     ├── Replace all occurrences → run tests
  │     │     └── [VALIDATE: no duplication, tests pass]
  │     │
  │     ├─► [BRANCH C: Large class / module]
  │     │     ├── Group methods by responsibility (what changes together?)
  │     │     ├── Extract each responsibility group to its own module
  │     │     ├── If widely used: apply strangler fig pattern
  │     │     │     └── New module alongside old → redirect callers one by one
  │     │     └── [VALIDATE: each module has single responsibility]
  │     │
  │     └─► [BRANCH D: Primitive obsession / long params]
  │           ├── Identify domain concepts hiding as primitives
  │           ├── Create value objects: Email, Money, PhoneNumber, DateRange
  │           ├── Replace primitives with value objects
  │           └── [VALIDATE: types are more expressive, tests pass]
  │
  └─► [OUTPUT: Refactored code + regression proof]
```

## Execution Steps

### Step 1: Run Existing Tests
```bash
npm test
```
If tests fail, **STOP**. Do not refactor broken code. Fix tests or code first.

### Step 2: Write Characterization Tests (if missing)
If no tests exist, write tests that capture the current behavior — inputs and outputs as they are now. These are your safety net, not your specification. Activate `test-generator` for this.

### Step 3: Identify the Smell
Use the taxonomy table above. Measure:
```bash
# Line counts per file
find src/ -name "*.ts" | xargs wc -l | sort -rn | head -10

# Functions over 20 lines (rough heuristic)
grep -c "function\|=>" src/**/*.ts | sort -t: -k2 -rn | head -10

# Duplicate blocks (requires jscpd)
npx jscpd src/ --format "typescript" --min-lines 5
```

### Step 4: Apply ONE Refactoring
Pick the highest-impact smell. Apply a single transformation. Examples:
- **Extract function**: Pull 10 lines out of a 40-line function, name it descriptively.
- **Introduce parameter object**: Replace `(name, email, phone, address)` with `(contact: ContactInfo)`.
- **Move method**: If `OrderService.formatAddress()` uses `Address` data, move it to `AddressFormatter`.

### Step 5: Run Tests
```bash
npm test
```
All tests must pass. If any fail → **revert the refactoring**. The test failure means behavior changed.

### Step 6: Commit
```bash
git add -A && git commit -m "refactor: extract calculateDiscount from processOrder"
```
One refactoring = one commit. This makes reverting surgical.

### Step 7: Repeat
Go back to Step 3. Find the next smell. Apply one refactoring. Test. Commit. Stop when the code meets quality thresholds or the time box expires.

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| Tests fail after refactoring | Behavior was accidentally changed | `git revert HEAD` — then re-examine what the code was actually doing |
| Extracted function name is unclear | Named after mechanism, not intent | Rename: `doProcessing()` → `validateAndNormalizeInput()` |
| Refactoring made code MORE complex | Over-abstraction or wrong pattern applied | Revert. Duplication is cheaper than the wrong abstraction. |
| Cannot refactor — no tests exist | No safety net | STOP. Activate `test-generator`. Write characterization tests first. |
| `jscpd` finds too many duplicates | Copy-paste culture in codebase | Prioritize: fix duplicates in hot code paths first, ignore test utilities |

## Validation Gate

- [ ] Tests existed (or were written) before any refactoring started
- [ ] Tests pass after every individual refactoring step
- [ ] Each refactoring was committed separately (one commit per transformation)
- [ ] Code complexity measurably reduced (line count, cyclomatic complexity, or duplication %)
- [ ] No behavior change — tests are the proof
- [ ] Extracted functions/classes are named by intent, not mechanism

## Output Contract

Refactoring report containing:
- **Smell identified**: Name from taxonomy + evidence (file:line, metric value)
- **Refactoring applied**: What transformation, on which code, why this approach
- **Before/after**: Diff showing the change (or line count / complexity comparison)
- **Tests passing**: Confirmation that all tests pass after the change
- **Complexity delta**: Measurable improvement (e.g., "function went from 45 lines to 12+18+15 across 3 focused functions")
