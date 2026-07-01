---
name: documentation-writer
description: "Use this skill when writing any technical documentation — API references, READMEs, architecture docs, or inline code comments. Applies audience-first writing and docs-as-code principles."
version: 1.0.0
triggers:
  - "write docs"
  - "document this"
  - "README"
  - "API docs"
  - "add comments"
  - "how to use"
  - "@documentation-writer"
token_budget: 2000
tools_required:
  - view_file
  - search_code
output_contract:
  format: "Documentation file or inline docs"
  includes:
    - what-why-how
    - usage-example
    - parameters
    - returns
    - caveats
works_with:
  - architecture-analyst
  - refactoring-specialist
  - research-engine
  - code-synthesizer
risk: low
---

## Mission

Write technical documentation that serves its audience by applying audience-first principles, docs-as-code practices, and standardized formats for READMEs, API references, architecture docs, and inline comments. Every doc answers: what does this do, why does it exist, and how do I use it — in that order. Every example is runnable. Every comment explains WHY, not WHAT.

## When To Activate

- User asks to write or update documentation
- A new module, API, or feature needs documentation
- README is missing, outdated, or incomplete
- Code lacks meaningful comments or JSDoc
- **Anti-trigger**: Do NOT activate for code implementation (use `code-synthesizer`) or architecture decisions (use `architecture-analyst`). Activate when the task is writing human-readable docs, not writing code.

## Core Concepts

### 1. Audience First
Before writing a single word, ask: **who reads this?**

| Audience | Needs | Format |
|----------|-------|--------|
| New contributor | Setup, architecture overview, where to start | README + CONTRIBUTING.md |
| API consumer | Endpoints, params, responses, errors, examples | API reference (OpenAPI/JSDoc) |
| Ops/SRE | Deploy, config, monitoring, troubleshooting | Runbook / Operations guide |
| Future self | Why decisions were made, trade-offs considered | ADR (Architecture Decision Record) |

Write for ONE audience per document. Mixing audiences creates docs that serve nobody well.

### 2. Docs as Code
Documentation lives in the repo, versioned with code, reviewed in PRs, updated when code changes. If docs live in a wiki or Google Doc, they will go stale within weeks.

Rules:
- Doc files live in `docs/` or next to the code they describe
- PR template includes: "Did you update the docs?" checkbox
- CI can lint docs (markdownlint, vale, dead link checker)

### 3. README Structure (6 Sections)
Every README needs these sections in this order:

```markdown
# Project Name          ← What (1 sentence: what this is)

Brief description       ← Why (problem it solves, 2-3 sentences)

## Installation         ← Exact copy-paste commands
## Usage                ← Minimal working example (10-20 lines)
## API Reference        ← All public options/methods
## Contributing         ← How to set up dev env and submit changes
## License              ← SPDX identifier
```

The README is a funnel: most readers need What + Install + Usage. Only power users read API Reference. Keep the top concise.

### 4. API Doc Standard (per Function/Endpoint)
Every public function or API endpoint needs:

```typescript
/**
 * Calculate shipping cost based on weight and destination.
 * 
 * Uses tiered pricing: domestic flat rate, international by weight bracket.
 * Rates are loaded from config/shipping-rates.json.
 * 
 * @param weight - Package weight in kg. Must be > 0 and ≤ 50.
 * @param destination - ISO 3166-1 alpha-2 country code (e.g., "US", "DE").
 * @returns Shipping cost as Money object with amount and currency.
 * @throws {ArgumentError} If weight is ≤ 0 or > 50.
 * @throws {NotFoundError} If destination country is not in shipping zones.
 * 
 * @example
 * const cost = calculateShippingCost(2.5, 'DE');
 * // => { amount: 15.99, currency: 'USD' }
 */
function calculateShippingCost(weight: number, destination: string): Money
```

Required fields: description, every `@param`, `@returns`, every `@throws`, at least one `@example`.

### 5. Comment Philosophy
Comments explain **WHY**, not **WHAT**. The code tells you what; the comment tells you why.

```typescript
// ❌ BAD: restates the code
i += 1; // increment i by 1

// ❌ BAD: obvious from function name
async function getUser(id: string) { // gets a user by ID

// ✅ GOOD: explains a non-obvious constraint
const MAX_RETRIES = 3; // Circuit breaker trips after 3 failures per PCI-DSS requirement

// ✅ GOOD: explains WHY this approach was chosen
// Using setTimeout instead of setInterval because setInterval
// doesn't account for execution time, causing drift under load.
```

### C4 Model Basics (Architecture Docs)
For architecture documentation, use the C4 model levels:
1. **Context**: System + external actors (users, other systems)
2. **Container**: Major deployment units (web app, API, DB, cache)
3. **Component**: Modules within a container (auth, billing, notification)
4. **Code**: Classes/functions (only for critical code, usually not needed)

Each level zooms in. Most projects need Context + Container diagrams.

## Reasoning Graph

```
[INPUT: Code or system to document]
  │
  ├─► [CLASSIFY: What type of doc?]
  │     │
  │     ├─► [BRANCH A: README / Getting Started]
  │     │     ├── Read entry point file → write 1-sentence description
  │     │     ├── Identify core value → write problem statement (2-3 sentences)
  │     │     ├── Extract install commands from package.json / Makefile
  │     │     ├── Write minimal working example (fewest lines that show it working)
  │     │     ├── List config options with types and defaults
  │     │     ├── Add contributing guide + license
  │     │     └── [VALIDATE: all 6 sections present, examples run]
  │     │
  │     ├─► [BRANCH B: API Reference]
  │     │     ├── List all public functions/endpoints
  │     │     ├── For each: description, params, returns, throws, example
  │     │     ├── Group by domain/feature area
  │     │     ├── Ensure every example is copy-paste runnable
  │     │     └── [VALIDATE: every public API documented]
  │     │
  │     └─► [BRANCH C: Architecture Doc]
  │           ├── Context: what system is this? Who uses it?
  │           ├── Containers: what are the deployment units?
  │           ├── Components: how do modules interact?
  │           ├── Decision log: why were key choices made? (ADRs)
  │           └── [VALIDATE: C4 levels covered, decisions recorded]
  │
  └─► [OUTPUT: Documentation]
```

## Execution Steps

### Branch A: README

### Step 1: What
Read the entry point (`main.ts`, `index.js`, `app.ts`). Write a 1-sentence description:
```markdown
# FastCache
A Redis-backed distributed cache with automatic TTL management and LRU eviction.
```

### Step 2: Why
Find the core value. What problem does this solve? Why would someone use it?
```markdown
Reduces database load by caching frequent queries with configurable TTL. 
Supports cluster mode for high availability.
```

### Step 3: Install
Extract from `package.json`. Write exact, copy-paste commands:
```bash
npm install @company/fastcache
```

### Step 4: Usage
Write the minimal example — fewest lines that show the primary use case:
```typescript
import { FastCache } from '@company/fastcache';

const cache = new FastCache({ redis: 'redis://localhost:6379', ttl: 300 });
await cache.set('user:123', userData);
const user = await cache.get('user:123');
```

### Step 5: API Reference
List all public methods with params, returns, examples.

### Step 6: Contributing + License
```markdown
## Contributing
See [CONTRIBUTING.md](./CONTRIBUTING.md) for setup instructions.

## License
MIT
```

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| Docs go stale immediately after writing | Written separately from code, no update process | Move docs into code repo; add "docs updated?" to PR checklist |
| README is a wall of text | No structure, no headers, no code blocks | Add the 6 standard sections with clear headers |
| API docs missing examples | Written from code perspective, not user perspective | Write examples first (how would a user call this?), then fill in parameters |
| Examples don't work | Code changed, examples not updated | Run every example in docs as a test (docs testing) |
| Comments describe WHAT not WHY | Developer habit of narrating code | Delete all WHAT comments; add WHY comments only where non-obvious |

## Validation Gate

- [ ] Audience identified before writing
- [ ] README has all 6 sections: what / why / install / usage / API / contributing
- [ ] Every public API function has: description + params + returns + throws + example
- [ ] All examples are runnable (copy-paste works, no broken imports)
- [ ] No WHAT comments — only WHY comments in code
- [ ] Docs live in the repo (not external wiki)

## Output Contract

Documentation deliverable containing:
- **What + Why**: Clear statement of purpose and value (first two paragraphs)
- **Installation**: Exact copy-paste commands
- **Usage example**: Minimal working code that demonstrates the primary use case
- **API reference**: Every public function/endpoint with description, params, returns, throws, example
- **Caveats**: Known limitations, gotchas, or environment requirements
