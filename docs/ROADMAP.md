# Hermes — Development Roadmap

**Repository:** `saralbanker/hermes`
**Branch baseline:** `overhaul-2026-09-23`
**Goal:** Make the existing Hermes pipeline reliably operational, increase useful application throughput, and avoid unnecessary architectural complexity.

---

# Roadmap Rule

Do not rewrite Hermes from scratch.

Work from the existing pipeline:

```
discover
→ score
→ tailor
→ apply
→ response monitoring
```

Prioritize verified production reliability over adding new features.

Do not add enterprise infrastructure unless the existing architecture is proven insufficient.

---

# Stage 1 — Production Reliability

## Current truth state

Hermes already has a functioning end-to-end baseline.

Verified:

* scheduled execution
* discovery
* local scoring
* local tailoring
* Indeed submission
* Greenhouse submission with OTP
* Gmail response monitoring
* duplicate prevention
* attempt limits
* application state management

Known reliability problems include:

* complex Indeed forms can stall
* some application channels remain unverified
* some platforms reject automation
* browser/runtime recovery must remain reliable

## Evidence hierarchy

1. Live runtime behavior
2. Database state
3. Application confirmation / employer email
4. Logs and screenshots
5. Automated tests
6. Source code
7. Documentation

## Investigation objective

Identify the smallest set of production reliability defects that can interrupt unattended operation or waste application capacity.

Focus on:

```text
browser lifecycle
timeouts
stale application states
channel failures
unexpected exceptions
queue interruption
database consistency
```

Do not redesign working components without evidence.

## Forbidden assumptions

* A passing unit test means the production channel works.
* A successful dry run means a live submission works.
* A browser timeout automatically means the website is broken.
* `submission_unconfirmed` means the application failed.
* An unverified channel is necessarily broken.
* A platform anti-bot rejection can be solved by bypassing its security controls.

## Required deliverable

A verified list of production reliability defects with:

```text
problem
affected module
reproduction evidence
minimal fix
verification method
```

---

# Stage 2 — Application Coverage

## Current truth state

Application support exists for:

```
Indeed
Greenhouse
Lever
Ashby
Redirect targets
Direct employer forms
```

But production confidence is uneven.

Greenhouse and Indeed have real submission evidence.

Lever has not yet been sufficiently production-verified.

Direct employer forms are implemented but not production-proven.

Ashby is currently blocked by platform-side anti-bot behavior.

## Evidence hierarchy

1. Confirmed live submission
2. Employer acknowledgement
3. Platform application history
4. Database submission evidence
5. Runtime logs/screenshots
6. Dry-run results
7. Unit tests
8. Source-code support

## Execution objective

Increase the number of application destinations that Hermes can reliably complete without weakening verification.

Priority:

```text
validate existing supported channels
→ improve existing failures
→ expand direct-form coverage
```

Treat anti-bot rejection as a channel limitation rather than a requirement to bypass security controls.

## Forbidden assumptions

* Every ATS uses the same form structure.
* Every direct employer form can be handled by the generic engine.
* Redirect resolution guarantees successful submission.
* A successful field fill guarantees successful submission.
* Ashby can be made reliable by defeating its anti-bot controls.
* More supported channels automatically means more successful applications.

## Required deliverable

For each application channel:

```text
supported
verified
failure modes
known form limitations
next required improvement
```

with live evidence wherever possible.

---

# Stage 3 — Throughput Optimization

## Current truth state

Hermes has a configured capacity of:

```text
100 applications/day
```

but measured successful submission throughput is substantially lower.

The bottleneck is therefore not the configured cap itself.

Potential sources of lost capacity include:

```text
insufficient eligible jobs
stale jobs
duplicate roles
scoring limits
tailoring limits
slow browser interactions
form failures
timeouts
unsupported destinations
platform restrictions
```

## Evidence hierarchy

1. Measured runtime metrics
2. Database counts
3. Application results
4. Stage timing
5. Logs
6. Configuration
7. Assumptions

## Investigation objective

Measure where available application capacity is actually lost.

Track:

```text
discovered
eligible
scored
tailored
queued
attempted
submitted
failed
expired
duplicate
unsupported
blocked
timed out
```

Separate:

```text
job-supply bottleneck
from
processing bottleneck
from
application-success bottleneck
```

## Forbidden assumptions

* Increasing the daily cap increases throughput.
* Increasing scraping volume automatically increases submissions.
* Faster LLM inference automatically improves daily output.
* Every failed application is worth retrying.
* More aggressive browser automation is automatically better.
* A high raw-job count means Hermes has enough usable jobs.

## Required deliverable

A measured throughput breakdown showing:

```text
where jobs are lost
time spent at each stage
successful submissions/day
failed submissions/day
avoidable losses
highest-value bottleneck
```

---

# Stage 4 — Final Production Optimization

## Current truth state

The core architecture is intentionally small:

```text
Python
SQLite
Ollama
Playwright / Chrome
Xvfb
systemd
```

This is sufficient as the default architecture for a non-enterprise single-machine system unless evidence proves otherwise.

## Evidence hierarchy

1. Production measurements
2. Runtime failures
3. Database evidence
4. Tests
5. Code inspection
6. Design preference

## Final objective

Turn Hermes into a stable unattended system by improving only the parts that materially affect:

```text
submission reliability
application coverage
throughput
response tracking
recovery
```

Keep the architecture simple.

Remove dead or obsolete code only after confirming it is not required by runtime paths.

Keep documentation synchronized with actual behavior.

## Forbidden assumptions

* Hermes needs microservices.
* Hermes needs Redis/PostgreSQL.
* Hermes needs cloud workers.
* Hermes needs a paid LLM API.
* Hermes needs a multi-agent architecture.
* A large refactor is inherently an improvement.
* Architectural complexity is a substitute for fixing production defects.

## Required deliverable

A production baseline that can demonstrate:

```text
scheduled unattended execution
+
reliable discovery
+
reliable scoring
+
reliable tailoring
+
verified application submission
+
safe retry/recovery
+
daily-cap enforcement
+
employer-response monitoring
```

with measured evidence for the resulting system.

---

# Definition of Done

Hermes is considered operationally complete when the existing pipeline can run unattended and:

```text
1. Discover usable jobs consistently.
2. Reject unsuitable jobs deterministically.
3. Score eligible jobs locally.
4. Generate truthful application material.
5. Apply through verified channels.
6. Never blindly duplicate or resubmit uncertain applications.
7. Recover safely from ordinary failures.
8. Respect application limits.
9. Continue processing when individual jobs or sources fail.
10. Detect and surface meaningful employer responses.
```

The target is a reliable working system, not an enterprise platform.
