---
name: code-synthesizer
description: "Use this skill when writing new production code from requirements. Enforces TDD, SOLID principles, and clean code constraints before generating any implementation."
version: 1.0.0
triggers:
  - "write this"
  - "implement"
  - "build this feature"
  - "create a"
  - "add a"
  - "I need a function"
  - "@code-synthesizer"
token_budget: 3000
tools_required:
  - view_file
  - search_code
  - run_terminal
output_contract:
  format: "Working code + tests + brief decision log"
  includes:
    - implementation
    - tests
    - decision-log
    - usage-example
works_with:
  - test-generator
  - architecture-analyst
  - debugging-master
  - refactoring-specialist
risk: medium
---

## Mission

Generate production-quality code from requirements by enforcing TDD (test before implementation), SOLID principles (each one explicitly), cyclomatic complexity limits, and explicit type contracts. Every function produced has tests, typed parameters, typed returns, and a usage example. No implementation exists without a test written first.

## When To Activate

- User asks to write a new function, module, class, or feature
- User provides requirements and expects working code
- User says "implement," "build," "create," or "I need a function that..."
- **Anti-trigger**: Do NOT activate for fixing existing code (use `debugging-master`) or refactoring without behavior change (use `refactoring-specialist`)

## Core Concepts

### 1. TDD Cycle: Red → Green → Refactor
Write a failing test first (**Red**). Implement the simplest code that makes it pass (**Green**). Then improve the code without breaking the test (**Refactor**). Never write implementation before a test. The test defines the contract; the implementation fulfills it.

### 2. SOLID Principles (Encoded)
- **(S) Single Responsibility**: One module = one reason to change. If a class handles both user validation AND email sending, split it.
- **(O) Open/Closed**: Extend behavior via new code (strategy pattern, plugin), not by modifying existing code with `if/else` chains.
- **(L) Liskov Substitution**: Any subtype must be usable wherever its parent type is expected without breaking behavior. If `AdminUser extends User`, every function accepting `User` must work with `AdminUser`.
- **(I) Interface Segregation**: Small, specific interfaces over large general ones. `Readable` + `Writable` > `ReadWriteDeleteArchiveStream`.
- **(D) Dependency Inversion**: Depend on abstractions, not concrete implementations. `UserService` imports `IUserRepository` (interface); `PostgresUserRepo` implements it. Swap the DB without touching the service.

### 3. Rule of Three
Do not abstract on first use. Do not abstract on second use. Abstract on third use. Premature abstraction creates wrong abstractions that are harder to remove than the duplication they replaced. Wait for the pattern to emerge.

### 4. Cyclomatic Complexity
If a function has more than 10 decision branches (`if`/`else`/`switch`/`&&`/`||`/`for`/`while`/ternary), split it. Each branch is a test case you must write. A function with complexity 15 needs 15 test paths — that's a sign it does too much.

```typescript
// BAD: complexity ~12
function processOrder(order: Order): Result {
  if (!order) throw new Error('No order');
  if (!order.items.length) return { status: 'empty' };
  if (order.total > 10000) { /* discount logic */ }
  if (order.user.isPremium) { /* premium logic */ }
  // ... 8 more branches
}

// GOOD: split by responsibility
function validateOrder(order: Order): void { /* 2 branches */ }
function calculateDiscount(order: Order): number { /* 2 branches */ }
function applyPremiumBenefits(order: Order): Order { /* 2 branches */ }
```

### 5. Explicit Contracts
Every function's signature is a contract. Parameters must be typed. Return values must be typed. Unexpected inputs must throw a typed error or return a typed error variant — never silently return `undefined`.

```typescript
// BAD: implicit contract
function getUser(id) { return db.find(id); }

// GOOD: explicit contract
function getUser(id: string): Promise<User> {
  if (!id) throw new ArgumentError('id is required');
  const user = await db.user.findUnique({ where: { id } });
  if (!user) throw new NotFoundError(`User ${id} not found`);
  return user;
}
```

## Reasoning Graph

```
[INPUT: Feature/function requirement]
  │
  ├─► [CLASSIFY: Pure function, stateful module, or integration?]
  │     │
  │     ├─► [BRANCH A: Pure function (no side effects, no I/O)]
  │     │     ├── Define input types + output type + error types
  │     │     ├── Write 3 tests: happy path, edge case, error case
  │     │     ├── Implement simplest code that passes all 3
  │     │     ├── Check complexity ≤ 10 → split if over
  │     │     ├── Refactor for clarity (names, structure)
  │     │     └── [VALIDATE: tests pass + complexity ok]
  │     │
  │     ├─► [BRANCH B: Stateful module (class, store, state machine)]
  │     │     ├── Define state shape (TypeScript interface)
  │     │     ├── Define all valid state transitions
  │     │     ├── Write tests for each transition (including invalid ones)
  │     │     ├── Implement with explicit state management
  │     │     └── [VALIDATE: all transitions tested]
  │     │
  │     └─► [BRANCH C: Integration (API / DB / external service)]
  │           ├── Define interface contract first (input/output/errors)
  │           ├── Mock external dependency with typed interface
  │           ├── Write tests against mock
  │           ├── Implement real adapter matching the interface
  │           ├── Write integration test with real dependency
  │           └── [VALIDATE: unit + integration tests pass]
  │
  └─► [OUTPUT: Code + tests + decision log]
```

## Execution Steps

### Branch A: Pure Function

### Step 1: Define the Signature
Name (verb-noun), input types, output type, throwable errors:
```typescript
function calculateShippingCost(weight: number, destination: Country): Money
  throws ArgumentError // if weight <= 0
```

### Step 2: Write 3 Tests
```typescript
describe('calculateShippingCost', () => {
  it('should_return_standard_rate_when_domestic', () => {
    expect(calculateShippingCost(2.5, 'US')).toEqual({ amount: 5.99, currency: 'USD' });
  });
  
  it('should_return_zero_when_weight_is_zero', () => {
    expect(() => calculateShippingCost(0, 'US')).toThrow(ArgumentError);
  });
  
  it('should_return_international_rate_when_foreign', () => {
    expect(calculateShippingCost(2.5, 'DE')).toEqual({ amount: 15.99, currency: 'USD' });
  });
});
```

### Step 3: Implement
Write the simplest code that passes all 3 tests. Resist adding logic for cases not covered by a test.

### Step 4: Check Complexity
Count decision branches. If > 10, extract sub-functions with descriptive names.

### Step 5: Refactor
Improve naming, extract constants, align with SOLID. Run tests after each change.

### Step 6: Write Usage Example
```typescript
// Usage:
const cost = calculateShippingCost(order.totalWeight, order.shippingAddress.country);
console.log(`Shipping: ${cost.amount} ${cost.currency}`);
```

### Step 7: Run Full Suite
`npm test` — confirm no regressions from new code.

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| Test passes but wrong output | Test assertion too loose (truthy instead of strict equality) | Use `toEqual()` / `toStrictEqual()`, not `toBeTruthy()` |
| Function too long to understand | Violates single responsibility | Find the "and" in what it does — that's the split point |
| `Type 'X' is not assignable to type 'Y'` | Interface mismatch between producer and consumer | Align the types at the interface boundary; never `as any` to suppress |
| Works in isolation, fails when integrated | Implicit dependencies (global state, env vars, singletons) | Make all dependencies explicit parameters or constructor-injected |
| Tests are brittle, break on refactors | Tests test implementation details, not behavior | Test inputs → outputs, not internal method calls |

## Validation Gate

- [ ] Tests written before implementation (TDD Red → Green → Refactor)
- [ ] All 3 test types present: happy path, edge case, error case
- [ ] Function does exactly one thing (single responsibility)
- [ ] Cyclomatic complexity ≤ 10
- [ ] All parameters and return values are typed (no `any` without justification)
- [ ] Full test suite passes with new code: `npm test` exits 0

## Output Contract

Deliverable for every code synthesis:
- **Implementation file**: Production code with typed signatures and explicit error handling
- **Test file**: Tests covering happy path, edge case, and error case — named `should_<action>_when_<condition>`
- **Decision log**: 3-line log explaining key choices (e.g., "Used strategy pattern because requirement implies multiple calculation methods")
- **Usage example**: 5-10 lines showing how a caller uses the new code
