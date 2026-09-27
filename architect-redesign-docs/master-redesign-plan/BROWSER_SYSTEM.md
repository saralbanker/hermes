# Hermes — Browser System

**Document ID:** HERMES-BROWSER-SYSTEM-2026-09-27  
**Status:** ACTIVE IMPLEMENTATION SPECIFICATION  
**Document:** 5/8  
**Parent:** ARCHITECTURE_REDESIGN_FINAL-2026-09-27-FROZEN.md + MASTER_PLAN.md + SYSTEM_RULES.md + DATA_MODEL.md + WORKFLOW_ENGINE.md  
**Repository:** saralbanker/hermes  
**Baseline branch:** overhaul-2026-09-23

> Purpose: define the browser automation boundary, runtime lifecycle, page-state model, action model, channel behavior, evidence collection, failure handling, resource controls, and migration contract.
>
> This document makes the frozen browser architecture implementable. It does not redefine the architecture, add new platform scope, or introduce a security-evasion layer.

---

# 1. Objective

The browser subsystem performs legitimate application work that cannot be completed safely through a simpler interface.

It is not the owner of:

- canonical opportunity identity
- candidate facts
- eligibility
- fit scoring
- scheduling
- daily limits
- response classification
- application-history truth

It owns:

- browser lifecycle
- session and context handling
- navigation
- structured page observation
- bounded actions
- file uploads
- supported OTP interaction
- evidence capture
- browser-specific failure reporting
- browser recovery

Priority order:

```text
correctness
→ evidence quality
→ duplicate safety
→ deterministic behavior
→ resource efficiency
→ throughput
```

# 2. Non-Negotiable Rules

1. All browser automation goes through BrowserGateway.
2. Channel code must not depend directly on Playwright, CDP, Chromium, or another concrete browser library.
3. Structured DOM/ARIA state is the primary control input.
4. Screenshots are evidence and diagnostics, not the normal control primitive.
5. Every externally mutating action is validated before execution.
6. AI may propose bounded actions but never receives unrestricted browser authority.
7. CAPTCHA, Turnstile, Cloudflare challenges, rate limits, account walls, and verification barriers are respected, not bypassed.
8. Persistent sessions are used only where a channel genuinely requires them.
9. Baseline concurrency is one browser worker and one active application.
10. Browser restart never implies that an application may be replayed.
11. Submit-click success is not submission confirmation.
12. Ambiguous submit becomes submission-unconfirmed and is reconciled before another attempt.
13. Browser failures before external work must be distinguishable from failures after submission may have started.
14. Browser timing is configurable and channel-aware.
15. Resource thresholds are measured on the real host.
16. Hermes has no Laya dependency.
17. Hermes has no stealth browser core dependency.
18. Generic private-API or HTTP replay is not a browser-submission substitute.
19. Browser behavior remains replaceable behind the gateway.

# 3. Target Architecture

```text
Workflow Engine
      |
      v
BrowserGateway
      |
      +---------------------+
      |                     |
      v                     v
Playwright Adapter      CDP Adapter
      |                     |
      +-----------+---------+
                  |
                  v
             Browser Runtime
                  |
          +-------+-------+
          |               |
          v               v
   Authenticated       Isolated
      profiles        contexts
          |               |
          +-------+-------+
                  |
                  v
           Channel Driver
                  |
          +-------+-------+
          |               |
          v               v
  Structured State      Evidence
```

Workflow creates the attempt and lease.

The channel driver executes the channel-specific route.

BrowserGateway provides generic browser primitives.

Concrete browser libraries remain behind adapters.

# 4. Responsibility Boundaries

## 4.1 Workflow Engine

Owns:

```text
claim
lease
attempt number
daily cap
retry policy
channel selection
result persistence
reconciliation
```

## 4.2 BrowserGateway

Owns:

```text
browser process
profile/context lifecycle
pages/tabs
navigation
frames
structured state
element references
validated action execution
uploads
screenshots
health
restart
```

## 4.3 Channel Driver

Owns:

```text
page classification
session checks
channel navigation
known form semantics
channel-specific confirmation interpretation
channel-specific OTP behavior
```

## 4.4 AI Layer

May provide:

```text
bounded semantic interpretation
screening-answer wording
bounded next-action proposal
```

AI does not receive unrestricted browser execution.

# 5. Gateway Contract

The concrete programming interface may differ, but the semantics should support operations equivalent to:

```text
open_session(profile, mode)
close_session(session)
new_context(session, policy)
close_context(context)

navigate(context, url)
reload(context)
back(context)
forward(context)

snapshot(context)
wait_for_state(context, condition)
wait_for_url(context, matcher)
wait_for_navigation(context)

click(context, element_ref)
type_text(context, element_ref, text)
select(context, element_ref, option)
check(context, element_ref)
uncheck(context, element_ref)
scroll(context, direction, amount)
upload_file(context, element_ref, path)

screenshot(context, path)

health(context)
restart_session(session, reason)
```

The gateway returns normalized Hermes objects, not raw browser-library objects.

# 6. Browser Object Model

Hermes distinguishes:

```text
browser process
profile
context
page/tab
element reference
```

A browser process is expensive and should normally be reused.

A profile stores persistent session state.

A context provides isolation.

A page/tab is a document surface.

An element reference is valid only for its current state lifetime.

# 7. Process Reuse

Default lifecycle:

```text
start
→ verify health
→ use
→ observe health
→ continue
→ restart only when justified
```

Do not create a new browser process for every application.

Reuse lowers startup cost, RAM churn, protocol setup cost, and login/session churn.

# 8. Baseline Concurrency

First production baseline:

```text
one browser worker
one active application attempt
```

Additional concurrency requires measured evidence that:

- CPU remains usable
- browser RSS remains bounded
- local models remain responsive
- SQLite contention is acceptable
- channel rate limits permit it
- duplicate safety is unchanged

Concurrency is an optimization, not a prerequisite for the 100/day target.

# 9. Browser Modes

Supported modes are conceptually:

```text
headless
headful
```

Mode is channel-specific.

If a channel demonstrably rejects headless mode, that channel may use headful mode.

A channel must not inherit another channel's display requirement.

Browser mode is an operational compatibility setting, not an anti-detection technique.

# 10. Host Environment

The real deployment target is:

```text
Arch Linux
Ryzen 7 7730U
16 GB RAM
Vega 8 integrated graphics
CPU-only inference
KDE / Wayland
```

The browser competes for CPU and RAM with Python, SQLite, Ollama/local models, source discovery, and the desktop.

The subsystem therefore prefers low process count, browser reuse, bounded tabs, bounded contexts, and measurable resource behavior.

