---
name: performance-optimizer
description: "Use this skill when measuring and improving performance of code or systems. Enforces measure-first workflow: baseline → profile → bottleneck → optimize → validate no regression."
version: 1.0.0
triggers:
  - "slow"
  - "performance"
  - "latency"
  - "memory leak"
  - "optimize"
  - "bottleneck"
  - "too slow"
  - "@performance-optimizer"
token_budget: 3500
tools_required:
  - view_file
  - run_terminal
  - search_code
output_contract:
  format: "Performance report: baseline + bottleneck + optimization + validation"
  includes:
    - baseline-metrics
    - bottleneck-location
    - optimization-applied
    - after-metrics
    - regression-test
works_with:
  - debugging-master
  - system-auditor
  - test-generator
  - code-synthesizer
risk: medium
---

## Mission

Improve performance by enforcing a strict measure-first workflow: establish a baseline metric, identify the bottleneck using a profiler (never intuition), apply a targeted optimization to the bottleneck, measure again to prove improvement, and add a performance regression test. No optimization is valid without a before/after measurement. No bottleneck is identified without profiler evidence.

## When To Activate

- User reports slow response times, high latency, or memory issues
- System is not meeting performance SLOs/SLAs
- User wants to optimize a specific operation or endpoint
- Memory usage grows over time (potential leak)
- **Anti-trigger**: Do NOT activate for functional bugs (use `debugging-master`) or architectural problems (use `architecture-analyst`)

## Core Concepts

### 1. Measure Before Optimize (Mandatory)
Never optimize without a baseline measurement. Without a "before" number, you cannot prove the optimization worked. The baseline IS the test.
```typescript
// Always start with:
console.time('operation');
await expensiveOperation();
console.timeEnd('operation'); // "operation: 1247.32ms"
// THEN optimize. THEN measure again.
```

### 2. Profile, Don't Guess
Developers are wrong about bottleneck location ~70% of the time (based on empirical studies by Knuth, McConnell). Use a profiler:
- **Node.js**: `node --prof app.js` → `node --prof-process isolate-*.log`
- **Browser**: DevTools → Performance tab → Record → Find long tasks
- **Python**: `python -m cProfile script.py | sort -k cumtime`
- **General**: `perf record -g ./program && perf report`

The bottleneck is where the profiler says, not where you think.

### 3. Big O for Common Operations
Know complexity to spot problems by inspection:
| Operation | Complexity | 10K items |
|-----------|-----------|-----------|
| Hash map lookup | O(1) | 1 op |
| Binary search | O(log n) | 14 ops |
| Array scan | O(n) | 10K ops |
| Nested loops | O(n²) | 100M ops |
| Triple nested | O(n³) | 1T ops |

```typescript
// ❌ O(n²) — nested find inside loop
users.forEach(user => {
  const order = orders.find(o => o.userId === user.id); // O(n) × O(n) = O(n²)
});

// ✅ O(n) — build lookup map first
const orderMap = new Map(orders.map(o => [o.userId, o])); // O(n)
users.forEach(user => {
  const order = orderMap.get(user.id); // O(1) × O(n) = O(n)
});
```

### 4. Amdahl's Law
Optimizing a part that takes 5% of total time cannot improve total time by more than 5%, even if you make it infinitely fast. Always optimize the **largest** portion first. If DB queries take 80% of request time, optimizing JavaScript execution (15%) is wasted effort.

### 5. Regression Risk
Every optimization trades readability for speed. Add a performance test that records the metric:
```typescript
it('should_complete_bulk_import_under_500ms', async () => {
  const start = performance.now();
  await bulkImport(testData10k);
  const duration = performance.now() - start;
  expect(duration).toBeLessThan(500);
});
```
If a future change makes it slower, this test catches it.

## Reasoning Graph

```
[INPUT: Performance complaint]
  │
  ├─► [CLASSIFY: CPU, memory, I/O, or network?]
  │     │
  │     ├─► [BRANCH A: CPU bound (high CPU, slow computation)]
  │     │     ├── Add timing: console.time/timeEnd around suspect areas
  │     │     ├── Run profiler: `node --prof app.js`
  │     │     ├── Find hottest functions in profile output
  │     │     ├── Look for O(n²) patterns:
  │     │     │     └── grep -n "\.find(\|\.filter(\|\.includes(" inside loops
  │     │     ├── Can nested loops become O(n) with a Map/Set?
  │     │     ├── Apply optimization → measure again
  │     │     └── [VALIDATE: ≥20% improvement, no functional regression]
  │     │
  │     ├─► [BRANCH B: Memory (leak or excess usage)]
  │     │     ├── Take heap snapshot: Chrome DevTools → Memory → Take snapshot
  │     │     ├── Perform the leaking operation N times
  │     │     ├── Take another snapshot → compare
  │     │     ├── Growing objects = leak candidates:
  │     │     │     ├── Event listeners not removed on cleanup
  │     │     │     ├── Closures holding references to large objects
  │     │     │     ├── Caches growing without size limits
  │     │     │     └── Global arrays/maps never cleared
  │     │     ├── Fix: remove listeners, add cache eviction, use WeakMap/WeakRef
  │     │     └── [VALIDATE: memory stable over repeat operations]
  │     │
  │     ├─► [BRANCH C: I/O bound (slow DB, API, filesystem)]
  │     │     ├── Add per-query/request timing logs
  │     │     ├── Find slowest query: `EXPLAIN ANALYZE <query>` for SQL
  │     │     ├── Check for N+1 problem:
  │     │     │     └── Loop making 1 query per item instead of batch
  │     │     ├── Fix: batch queries, add indexes, add cache layer
  │     │     │     └── `CREATE INDEX idx_user_email ON users(email);`
  │     │     └── [VALIDATE: p95 latency improved]
  │     │
  │     └─► [BRANCH D: Network bound (slow external APIs)]
  │           ├── Measure: which external call is slowest?
  │           ├── Can calls be parallelized? `Promise.all([fetch(a), fetch(b)])`
  │           ├── Can results be cached? Add TTL-based cache
  │           └── [VALIDATE: end-to-end latency improved]
  │
  └─► [OUTPUT: Performance report]
```

## Execution Steps

### Step 1: Establish Baseline
```bash
# HTTP endpoint timing
curl -w "\nTotal: %{time_total}s\nTTFB: %{time_starttransfer}s\n" http://localhost:3000/api/endpoint

# Node.js operation timing
node -e "
const start = performance.now();
require('./operation')().then(() => {
  console.log('Duration:', (performance.now() - start).toFixed(2), 'ms');
});
"
```
Record the number. This is your baseline.

### Step 2: Profile
```bash
# Node.js CPU profile
node --prof src/server.js &
# Generate load
ab -n 100 -c 10 http://localhost:3000/api/endpoint
# Process profile
node --prof-process isolate-*.log > profile.txt
# Find top functions by "ticks" count
grep -A2 "\\[JavaScript\\]" profile.txt | head -30
```

### Step 3: Identify Bottleneck
The profiler output shows which functions consume the most time. Focus on the top 3. Apply Amdahl's Law: only optimize if the function is >20% of total time.

### Step 4: Apply Optimization
Target the specific bottleneck. Common fixes:
- O(n²) → O(n): Replace `.find()` in loop with `Map.get()`
- N+1 queries → batched: Replace loop-query with `WHERE id IN (...)`
- Missing index → add index: `CREATE INDEX` on filtered/joined columns
- Sequential → parallel: `Promise.all()` for independent async operations

### Step 5: Measure Again
Run the exact same benchmark as Step 1. Compare numbers. If <20% improvement, you optimized the wrong thing — re-profile.

### Step 6: Add Regression Test
Write a performance test with a threshold. If future changes break performance, this test catches it.

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| Optimization made no measurable difference | Wrong bottleneck targeted | Re-profile; the real bottleneck is elsewhere |
| Memory leak not visible in snapshots | Leak is in native code or external library | Isolate: does the leak happen without the library? Use `--expose-gc` + manual `global.gc()` |
| DB query still slow after adding index | Index not used by query planner | Run `EXPLAIN ANALYZE` — check for `Seq Scan` (index not used) vs `Index Scan` |
| Performance regression after deploy | Optimization reverted by merge or refactor | Add `expect(duration).toBeLessThan(threshold)` test |
| `ab` benchmark shows high variance | System under other load, or GC pauses | Run benchmark 3x, take median; use `--keepalive` flag; warm up before measuring |

## Validation Gate

- [ ] Baseline measurement recorded before any changes
- [ ] Profiler output reviewed (not intuition-based optimization)
- [ ] Bottleneck identified with file:line from profiler
- [ ] Amdahl's Law check: bottleneck is >20% of total time
- [ ] After-optimization measurement shows ≥20% improvement on the target metric
- [ ] No functional regression (test suite still passes)
- [ ] Performance regression test added

## Output Contract

Performance report containing:
- **Baseline metrics**: Operation name, duration/memory before optimization, measurement method
- **Bottleneck location**: File:line, function name, % of total time, why it's slow
- **Optimization applied**: What changed, why this approach, Big O before/after
- **After metrics**: Same measurement as baseline, showing improvement
- **Regression test**: Test code that will catch future performance degradation
