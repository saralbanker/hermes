---
name: task-planner
description: "Use this skill when breaking down any complex goal into ordered, executable subtasks with clear dependencies, acceptance criteria, and risk assessment."
version: 1.0.0
triggers:
  - "plan this"
  - "break down"
  - "where do I start"
  - "task breakdown"
  - "how to approach"
  - "@task-planner"
token_budget: 3500
tools_required:
  - view_file
  - search_code
output_contract:
  format: "Structured task list with dependencies, AC, and risk flags"
  includes:
    - task-list
    - dependency-graph
    - acceptance-criteria
    - risk-flags
    - first-action
works_with:
  - debugging-master
  - code-synthesizer
  - architecture-analyst
  - system-auditor
risk: low
---

## Mission

Decompose any complex goal into a directed acyclic graph of atomic, executable subtasks — each with one unambiguous Definition of Done, explicit dependencies, Given/When/Then acceptance criteria, and a risk assessment. The output is a prioritized plan that tackles unknowns first, identifies the critical path, and enables parallel execution of independent tasks.

## When To Activate

- User describes a feature, project, or goal that requires multiple steps
- User asks "where do I start?" or "how should I approach this?"
- User needs to break a large ticket into subtasks
- User wants to estimate complexity or identify blockers
- **Anti-trigger**: Do NOT activate for single, well-defined tasks (e.g., "add a button that does X") — those are already atomic

## Core Concepts

### 1. Task Atomicity
A task is atomic when it has exactly one unambiguous Definition of Done. "Implement auth" is **not** atomic. "Add JWT verification middleware to `/api` routes that returns 401 on invalid token" **is** atomic. If the DoD contains the word "and," the task is likely not atomic — split it.

### 2. Dependency Graph (DAG)
Tasks form a directed acyclic graph. Task B depends on Task A when B cannot start until A produces an artifact B needs. Map all blockers before sequencing. A circular dependency (A needs B, B needs A) means a shared prerequisite was missed — extract it into a new Task 0.

### 3. Critical Path
The longest chain of dependent tasks determines minimum delivery time. These tasks cannot be parallelized — they set the floor. Identify them, prioritize them, and never let them wait on non-critical work.

### 4. Risk-First Ordering
Tackle the highest-uncertainty task first when dependencies allow. Discovering a fundamental blocker on day 1 is recoverable. Discovering it on day 7 is a project reset. Known tasks can be estimated; unknown tasks cannot — so resolve unknowns early.

### 5. Acceptance Criteria Format
Each task needs: trigger condition + expected behavior + edge cases. Use Given/When/Then:
```
Given [precondition]
When [action is performed]
Then [expected outcome]
```
No AC = no way to verify done. Vague AC ("it should work") = vague completion = scope creep.

## Reasoning Graph

```
[INPUT: Goal description]
  │
  ├─► [CLASSIFY: Is this one task or a project?]
  │     │
  │     ├─► [BRANCH A: Single task]
  │     │     ├── Verify atomicity (one DoD, no "and")
  │     │     ├── Write AC in Given/When/Then
  │     │     ├── Identify tools/files needed
  │     │     └── [VALIDATE] → Output single task card
  │     │
  │     └─► [BRANCH B: Multi-task project]
  │           ├── Decompose into atomic tasks
  │           │     └── Each noun = potential component boundary
  │           ├── Map dependencies (which tasks block others?)
  │           │     └── For each task: "What must exist before this starts?"
  │           ├── Identify critical path (longest dep chain)
  │           ├── Flag high-risk / unknown tasks
  │           │     └── "What could make this plan fail?"
  │           ├── Order: unknowns → critical path → parallel → cleanup
  │           ├── Write AC for each task
  │           └── [VALIDATE: Every task has one DoD + no circular deps]
  │
  └─► [OUTPUT: Structured plan]
```

## Execution Steps

### Step 1: Extract Components
Read the goal statement. List every noun that implies a system component (database, API, UI, auth, notification). Each component is likely a task boundary.

### Step 2: Write Definitions of Done
For each task, write one sentence: "This task is done when [specific, testable condition]." If the sentence uses "and," split the task.

### Step 3: Map Dependencies
For each task, ask: "What does this need to exist before it can start?" List those blockers. Draw edges: `blocker → dependent`. Check for cycles — if A→B→A, extract shared prerequisite into a new task.

### Step 4: Find Critical Path
Chain the longest dependency sequence. Mark these tasks `[CP]`. Everything else can potentially run in parallel.

```
Example:
  Task 1 (DB schema) → Task 3 (API routes) → Task 5 (Frontend integration)
  Task 2 (Auth middleware) → Task 4 (Protected routes)
  
  Critical path: 1 → 3 → 5 (longest chain = 3 tasks)
  Parallel: Task 2 can run alongside Task 1
```

### Step 5: Flag Unknowns
Tasks where the approach is unclear get `risk: high`. These go first in execution order. Ask: "What could make this plan fail?" — that thing is the highest-risk task.

### Step 6: Order the Final List
Priority: `unknowns → critical path tasks → parallel tasks → cleanup/polish`

### Step 7: Write Acceptance Criteria
For each task, write Given/When/Then:
```
Task: "Add JWT verification middleware"
Given: A request hits any /api/* route
When: The Authorization header is missing or contains an invalid JWT
Then: The server returns 401 with body { error: "Unauthorized" }
```

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| Plan never gets executed | Tasks too large, no clear starting point | Break until the first task takes <4 hours of work |
| Circular dependency detected | Task A needs B, B needs A | Extract shared prerequisite into a new Task 0 |
| Scope creep mid-execution | AC was vague or missing | Rewrite AC before starting the task, not during |
| Wrong task prioritized first | Risk not assessed | Always ask: "What could make this plan fail?" — do that task first |
| Estimation wildly off | Unknown complexity not flagged | Mark unknowns explicitly; use T-shirt sizing (S/M/L) not hour estimates |

## Validation Gate

- [ ] Every task has exactly one Definition of Done
- [ ] No circular dependencies in the task graph
- [ ] Critical path is identified and marked
- [ ] At least one "unknown/risky" task is flagged for early execution
- [ ] Every task has Given/When/Then acceptance criteria
- [ ] First action is clear — someone can start immediately

## Output Contract

Structured markdown list. Each task entry contains:
- **task_name**: Short imperative phrase (e.g., "Create user table schema")
- **description**: One sentence — what this task produces
- **depends_on**: List of task names that must complete first (empty if none)
- **acceptance_criteria**: Given/When/Then format
- **risk_level**: `low` | `medium` | `high`
- **estimated_complexity**: `S` (<2h) | `M` (2-8h) | `L` (>8h)
