---
name: test-generator
description: "Use this skill when writing tests for any function, module, or system. Applies test pyramid ratios, boundary value analysis, and arrange-act-assert to produce minimal but complete test suites."
version: 1.0.0
triggers:
  - "write tests"
  - "add tests"
  - "test coverage"
  - "test this"
  - "unit test"
  - "integration test"
  - "@test-generator"
token_budget: 2000
tools_required:
  - view_file
  - run_terminal
output_contract:
  format: "Test file(s) with passing tests"
  includes:
    - happy-path
    - edge-cases
    - error-cases
    - test-names
works_with:
  - code-synthesizer
  - debugging-master
  - refactoring-specialist
  - security-auditor
risk: low
---

## Mission

Produce minimal but complete test suites by applying the test pyramid (70/20/10), boundary value analysis, and Arrange-Act-Assert pattern. Every test has a descriptive name, tests one behavior, and covers happy path, edge cases, and error cases. The test suite is the executable specification of the code.

## When To Activate

- User asks to write tests for existing or new code
- User wants to improve test coverage
- User needs a test for a specific bug (capture-before-fix)
- Test suite is missing or incomplete
- **Anti-trigger**: Do NOT activate for debugging (use `debugging-master`) — but DO write the bug-capturing test if asked during a debug session

## Core Concepts

### 1. Test Pyramid
- **70% Unit tests**: Fast, isolated, no I/O, no network, no DB. Test one function/method. Mock dependencies.
- **20% Integration tests**: Two real components together (e.g., service + real DB, handler + middleware). Slower but validates contracts.
- **10% E2E tests**: Full system from user action to response. Slowest, most brittle. Only test critical user flows.

Inverting this ratio (many E2E, few units) = slow, flaky, expensive-to-maintain suite that developers skip running.

### 2. Arrange-Act-Assert (AAA)
Every test has exactly 3 sections:
```typescript
it('should_return_discount_when_order_exceeds_100', () => {
  // Arrange — set up inputs and dependencies
  const order = createOrder({ total: 150 });
  const calculator = new DiscountCalculator();

  // Act — call the thing being tested
  const discount = calculator.apply(order);

  // Assert — verify the output
  expect(discount).toEqual({ percent: 10, amount: 15 });
});
```
One assertion per test (strongly preferred). Multiple assertions = multiple failure reasons = harder to diagnose.

### 3. Boundary Value Analysis
Bugs live at boundaries. For a function accepting `1-100`:
- Test: `0` (just below min → should reject)
- Test: `1` (min boundary → should accept)
- Test: `50` (typical middle → should accept)
- Test: `100` (max boundary → should accept)
- Test: `101` (just above max → should reject)
- Test: `null`, `undefined`, `NaN` (invalid types → should reject)

### 4. Test Naming Convention
`should_<expected_behavior>_when_<condition>` or `<function>_<scenario>_<expected>`:
```
✅ should_return_empty_array_when_no_users_found
✅ should_throw_ValidationError_when_email_is_invalid
✅ calculateTax_withZeroIncome_returnsZero
❌ test1
❌ testHappyPath
❌ it works
```
The name IS the documentation. When a test fails in CI, the name alone should explain what broke.

## Reasoning Graph

```
[INPUT: Function/module to test]
  │
  ├─► [CLASSIFY: Unit, integration, or E2E?]
  │     │
  │     ├─► [BRANCH A: Unit test (pure function or isolated module)]
  │     │     ├── List all inputs: valid, boundary, null/undefined, wrong type
  │     │     ├── List all outputs: success variants, error variants
  │     │     ├── Write one test per input/output combination
  │     │     ├── Mock all external dependencies (DB, HTTP, filesystem)
  │     │     ├── Verify: each test has max 1 assertion
  │     │     └── [VALIDATE: all tests pass, coverage > 80%]
  │     │
  │     ├─► [BRANCH B: Integration test (2+ components)]
  │     │     ├── Identify the integration boundary (what two things are connected?)
  │     │     ├── Test the CONTRACT between components, not internal logic
  │     │     ├── Use REAL implementations, not mocks
  │     │     │     └── DB: use test database. API: use test server.
  │     │     ├── Setup/teardown: clean state before each test
  │     │     └── [VALIDATE: contract holds under normal and error conditions]
  │     │
  │     └─► [BRANCH C: E2E test (full system)]
  │           ├── Test only critical user flows (login, checkout, data creation)
  │           ├── Use Playwright/Cypress for web, Supertest for API
  │           ├── Keep count low (< 20 E2E tests for most apps)
  │           └── [VALIDATE: tests are stable, not flaky]
  │
  └─► [OUTPUT: Test file(s)]
```

## Execution Steps

### Branch A: Unit Test

### Step 1: List Inputs and Boundaries
For each parameter, list:
- Valid typical value
- Min boundary (smallest valid)
- Max boundary (largest valid)
- Just-below-min (should reject)
- Just-above-max (should reject)
- Null / undefined / empty string / empty array

### Step 2: List Outputs
- Success return value(s)
- Error throw(s) — which error type and when?

### Step 3: Write Happy Path Test
```typescript
it('should_return_user_when_valid_id_provided', () => {
  const mockRepo = { findById: jest.fn().mockResolvedValue(mockUser) };
  const service = new UserService(mockRepo);

  const result = await service.getUser('valid-id');

  expect(result).toEqual(mockUser);
  expect(mockRepo.findById).toHaveBeenCalledWith('valid-id');
});
```

### Step 4: Write Boundary Tests
```typescript
it('should_throw_ArgumentError_when_id_is_empty_string', () => {
  expect(() => service.getUser('')).rejects.toThrow(ArgumentError);
});

it('should_throw_NotFoundError_when_user_does_not_exist', () => {
  mockRepo.findById.mockResolvedValue(null);
  expect(() => service.getUser('nonexistent')).rejects.toThrow(NotFoundError);
});
```

### Step 5: Write Null/Undefined Tests
```typescript
it('should_throw_ArgumentError_when_id_is_null', () => {
  expect(() => service.getUser(null)).rejects.toThrow(ArgumentError);
});
```

### Step 6: Write Error Case Tests
Test every error path the function can take.

### Step 7: Name and Run
Verify every test name describes behavior. Run: `npm test` — all must pass.

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| Tests pass but bugs still occur | Tests don't cover real usage paths | Add tests from bug reports — every bug gets its own test |
| Tests are slow (>30s for unit suite) | Too many integration/E2E tests, or unit tests hit real I/O | Push logic to unit tests; mock at I/O boundaries |
| Mock becomes out of sync with real implementation | No contract test validates the mock matches reality | Add contract test: call real impl with same inputs, verify same output shape |
| `Cannot find module '../src/thing'` in test | Jest `moduleNameMapper` or `tsconfig paths` misconfigured | Check `jest.config.ts` for `moduleNameMapper` and `roots` settings |
| Flaky test (passes sometimes, fails others) | Shared state between tests, or async timing | Add `beforeEach` cleanup; use `await` properly; never depend on test execution order |

## Validation Gate

- [ ] Happy path tested with representative valid input
- [ ] Boundary values tested (min, max, just-outside-boundary)
- [ ] Null/undefined/empty inputs tested
- [ ] Error cases tested (every throw/reject path)
- [ ] All test names describe behavior: `should_<behavior>_when_<condition>`
- [ ] All tests pass: `npm test` exits 0
- [ ] No test depends on another test's state (independent, isolated)

## Output Contract

Test file(s) containing:
- At least one happy path test per public function
- Boundary value tests for numeric/string/array parameters
- Null/undefined guard tests
- Error case tests for every documented error path
- All tests named descriptively — no `test1` or `it works`
- All tests passing on first run
