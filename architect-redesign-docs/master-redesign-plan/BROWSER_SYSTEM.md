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

ed graphics
CPU-only AI inference
KDE / Wayland
```

The legacy Xvfb path is migration input only.

Xvfb is not a permanent global browser dependency.

If a display workaround becomes necessary, isolate it to the affected channel/profile.

# 11. Authentication

Authenticated channels use durable session handling:

```text
load profile
→ verify session
→ apply
→ preserve session
→ detect expiry
→ pause channel
```

Hermes must not silently fall back to a guest flow when authentication changes the meaning of the submission.

Hermes must not create fake accounts or fabricate identity data.

# 12. Profile Isolation

Profiles are isolated by channel or purpose.

Examples:

```text
Indeed authenticated profile
other authenticated profiles
public/disposable context
```

Do not share unrelated platform cookies.

Persistent profiles can contain sensitive data and must never be committed.

# 13. Context Strategy

Use a context according to route needs.

Authenticated route:

```text
persistent profile/session
```

Public/direct route:

```text
isolated context when useful
```

Do not require a new context for every job when that damages session continuity.

Do not keep unrelated applications in one giant permanent context.

# 14. Page and Tab Ownership

Every attempt has an active page/context reference.

Drivers must track:

```text
source page
application page
popup/new tab
confirmation page
```

When a new tab appears:

```text
detect tab delta
→ identify new page
→ validate destination
→ classify
→ continue only when expected
```

Unexpected tab creation is a navigation anomaly, not success.

# 15. BrowserState

Browser decisions consume a normalized BrowserState containing, when available:

```text
session_id
context_id
page_id
url
title
visible_text
frames[]
dialogs[]
elements[]
validation_messages[]
page_phase
load_state
timestamp
```

Unavailable values remain unknown.

No browser component may fabricate metadata.

# 16. Interactive Element Model

Each useful interactive control should expose, where available:

```text
element_ref
tag
role
accessible_name
label
placeholder
input_type
name
id
value
checked
selected
required
disabled
visible
enabled
href
accept
autocomplete
frame_ref
```

This is the core semantic substrate for deterministic browser decisions.

# 17. Element Reference Lifetime

An element reference becomes stale after material state changes such as:

```text
navigation
reload
SPA route transition
major DOM replacement
frame replacement
form-step transition
```

Correct recovery:

```text
discard reference
→ snapshot again
→ resolve a fresh reference
```

Never retry a stale reference indefinitely.

# 18. Locator Priority

Preferred evidence order:

1. current structured element reference
2. explicit associated label
3. role + accessible name
4. stable id/name
5. stable form semantics
6. constrained CSS
7. narrow XPath fallback

Avoid making these defaults:

```text
nth-child chains
generated class names
pixel coordinates
absolute screen positions
deep selectors copied from one run
```

# 19. DOM/ARIA Before Vision

Normal control path:

```text
DOM/ARIA state
→ bounded decision
→ deterministic validation
→ browser action
→ new state
```

Vision remains supplementary.

Screenshots are useful for:

```text
confirmation evidence
failure diagnostics
incident review
visual debugging
```

# 20. Frames

Frames are first-class browser state.

Represent:

```text
frame_ref
frame_url
parent_frame
visible
elements
```

An element action carries frame context when applicable.

If a frame changes:

```text
re-snapshot
→ re-resolve frame
→ re-resolve element
```

Do not bypass cross-origin or browser security boundaries.

# 21. Shadow DOM

Open and otherwise supported shadow-root structures may be inspected.

State should distinguish:

```text
normal DOM
open shadow root
unsupported/closed shadow root
```

Closed or inaccessible shadow DOM is a valid unsupported condition.

# 22. Dialog Handling

Browser/page dialogs are explicit state:

```text
alert
confirm
prompt
permission request
file chooser
download prompt
```

Unknown dialogs are not automatically accepted.

Known safe dialogs may be handled by a specific channel rule.

# 23. Readiness

No single signal is a universal page-ready signal.

Use the combination that fits the route:

```text
navigation complete
URL stable
critical frame present
required control present
critical data rendered
short state-stability window
```

Long-lived connections are not automatically failures.

network-idle is not a universal requirement.

# 24. Wait Strategy

Prefer:

```text
wait for URL
wait for element state
wait for frame
wait for navigation
wait for page phase
wait for short stability window
```

Avoid long arbitrary sleeps.

Short delays remain valid for:

```text
post-click settlement
known asynchronous rendering
OTP polling
application pacing
```

# 25. Bounded Action Vocabulary

Recommended actions:

```text
CLICK
TYPE_TEXT
SELECT
CHECK
UNCHECK
SCROLL
WAIT
UPLOAD
DONE
BLOCKED
FAIL
```

There is no unrestricted AI action for arbitrary JavaScript, shell commands, or filesystem access.

# 26. Deterministic Action Validator

Every action passes through a validator.

It checks:

```text
element exists
element belongs to current state
element is usable
action matches element type
current page phase permits action
text source is approved
file path is approved
destination is permitted
workflow state permits the mutation
```

Examples:

```text
click disabled control
→ reject

type text into non-input
→ reject

upload arbitrary path
→ reject

use stale element reference
→ reject and re-snapshot

navigate to unexpected destination
→ reject
```

The validator is the final safety gate before mutation.

# 27. Text Provenance

Typed application content must come from approved sources:

```text
candidate facts
validated generated material
approved screening answer
known job metadata
channel-required constant
```

Do not source application text from arbitrary page content, another candidate, stale unrelated records, or ungrounded model memory.

# 28. Screening Questions

Flow:

```text
inspect question
→ determine semantics
→ retrieve approved facts/policy
→ determine answerability
→ generate wording only if allowed
→ validate factual claim
→ fill
→ re-read field
→ continue
```

Required question without a truthful approved answer is a typed failure.

Do not guess.

# 29. High-Risk Fields

Treat these as high-risk:

```text
professional experience years
technology-specific experience years
salary
current compensation
work authorization
sponsorship
citizenship
visa status
degree
employment status
notice period
relocation
```

Similar wording does not make these concepts interchangeable.

# 30. Experience Truth

Hermes must preserve the distinction between:

```text
paid professional/client-facing work
formal employment
overall hands-on software development
project/coursework experience
```

A professional-years question must not silently receive a larger overall-development number.

