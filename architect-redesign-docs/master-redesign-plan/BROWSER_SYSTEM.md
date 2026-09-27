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

 receive a larger overall-development number.

# 31. Numeric Fields

For numeric screening:

```text
use a truthful numeric value only when field meaning is known
```

Do not insert an attractive value merely to pass a form.

Unknown required numeric semantics require a safe stop.

# 32. Resume Selection

The browser receives an already-approved resume path.

It must:

```text
exist
be readable
be an approved candidate document
match the selected role variant
remain within allowed filesystem scope
```

The browser must not discover arbitrary local files.

# 33. Resume Variants

Conceptual mapping:

```text
AI role
→ AI resume

backend role
→ backend resume

full-stack/software role
→ full-stack resume

otherwise
→ default resume
```

Final selection remains owned by workflow/configuration.

# 34. File Upload

Upload flow:

```text
identify input
→ validate field semantics
→ validate approved local path
→ upload
→ inspect result
→ confirm file state where visible
```

Successful upload is not submission confirmation.

# 35. Cover Letters

The browser receives a prevalidated cover-letter artifact.

Before insertion:

```text
artifact exists
→ opportunity association verified
→ candidate facts validated
→ generated claims validated
→ field format acceptable
→ insert
```

Browser code does not improvise application prose.

# 36. Cookie Banners

Normal cookie/consent interaction may be handled when required.

Rules:

```text
narrow
label-aware
best-effort
channel-safe
```

Do not globally click the first button containing "Accept".

Cookie handling is not a security bypass.

# 37. Navigation and Route Resolution

Conceptual path:

```text
listing
→ application target resolution
→ destination
→ application form
→ confirmation/reconciliation
```

A redirect is not proof of a valid application route.

Destination must be classified before submission.

# 38. HTTP-First Resolution

Legitimate public HTTP/API work may be used for:

```text
public discovery
public metadata
safe redirect resolution
known ATS destination discovery
```

It must not become:

```text
anti-bot bypass
private endpoint replay
generic form-post automation
challenge-token extraction
```

Generic HTTP replay of browser submission is forbidden.

# 39. Destination Classification

A destination should be classified as:

```text
known ATS
direct employer form
board account wall
security block
sponsored/tracking destination
unsupported
```

Use multiple signals:

```text
URL
host
path
form structure
known ATS signatures
page text
```

# 40. Sponsored-Link Protection

Tracking parameters do not automatically mean sponsored content.

A sponsored detector should require stronger context such as:

```text
tracking URL
+
thin/unrelated destination path
+
known promotional pattern
```

Legitimate employer job URLs can contain tracking parameters.

# 41. Account Walls

Board-owned signup/login walls are:

```text
ACCOUNT_REQUIRED
```

Hermes may use a known legitimate employer/ATS route when already resolved.

Hermes must not create fake accounts or fabricate identity.

# 42. Channel Driver Contract

A channel driver should provide focused behavior equivalent to:

```text
identify_page()
verify_session()
prepare_application()
fill_known_fields()
answer_screening()
submit()
classify_outcome()
collect_evidence()
```

Drivers call BrowserGateway.

They do not own global scheduling or daily limits.

# 43. Indeed

Indeed is an authenticated, stateful route.

Current repository behavior worth preserving includes:

```text
pure page classification
login detection
security-interstitial detection
OTP detection
confirmation detection
already-applied detection
expired-page detection
persistent profile
Applied-history verification
Gmail confirmation
screenshots
bounded form steps
```

These are migration inputs, not permission to preserve the old DrissionPage architecture.

# 44. Indeed Session Verification

Indeed driver should distinguish:

```text
authenticated
unauthenticated
ambiguous
```

Only clear authentication loss should block.

A transient session-check failure is not proof of logout.

# 45. Indeed OTP

Supported flow:

```text
OTP page
→ identify email OTP
→ request fresh code
→ verify sender and freshness
→ enter code
→ re-snapshot
```

Phone-only OTP is unsupported unless a legitimate configured retrieval route exists.

# 46. Indeed Evidence

Useful evidence:

```text
confirmation page
confirmation URL
Applied history
platform confirmation email
screenshot
```

One missing secondary signal does not automatically negate stronger evidence.

Ambiguous state still requires reconciliation.

# 47. ATS Routes

Frozen architecture covers known ATS destinations such as:

```text
Greenhouse
Lever
Ashby
```

Greenhouse has strong historical runtime evidence.

Lever requires explicit runtime verification before being treated as equally proven.

Ashby remains blocked where anti-bot controls prevent automated submission.

# 48. Greenhouse

Typical route:

```text
navigate
→ inspect form
→ fill approved fields
→ upload resume
→ screening
→ supported verification if needed
→ submit
→ confirm
→ store evidence
```

Existing Greenhouse verification-code support should be retained during migration.

# 49. Lever

Use the same browser safety boundary.

Enable broad unattended use only after runtime verification.

If live behavior differs from assumptions:

```text
capture evidence
→ classify
→ update driver
```

Do not blindly broaden selectors.

# 50. Ashby

Where anti-bot controls prevent automated submission:

```text
stop
→ return channel-blocked outcome
→ update channel health
→ preserve opportunity for another legitimate route when possible
```

No stealth, challenge solving, identity rotation, or token bypass.

# 51. Direct Employer Forms

Direct forms are supported only when:

```text
destination is confidently a legitimate employer application
form is structurally supported
required controls can be operated safely
```

Unknown pages, unsupported widgets, or security barriers produce typed failure.

# 52. Form Classification

Use structural evidence:

```text
input
select
textarea
label
autocomplete
name
type
required
role
accessible name
nearby context
button role/name
form metadata
URL/title
```

A field name alone is not enough to define semantics.

# 53. Field Mapping

Preferred order:

```text
known platform mapping
→ autocomplete/name
→ associated label
→ accessible name
→ nearby context
→ bounded semantic interpretation
```

If semantics remain ambiguous:

```text
do not guess
```

# 54. Required Fields

Required field handling:

```text
truthful value known
→ fill

optional by policy
→ leave blank

required but unknown/untruthful
→ typed failure
```

Do not insert placeholders just to unlock submission.

# 55. Page Classification

Common phases:

```text
job_page
application
login
otp
captcha
security_interstitial
form
confirmation
already_applied
expired
unsupported
unknown
```

Classification uses multiple signals.

# 56. Security Interstitial Detection

Prefer high-signal indicators:

```text
challenge-specific title
challenge-specific URL
challenge iframe
challenge-specific visible wording
very low content + challenge marker
```

Weak indicators such as a generic "Sign in" link or passive challenge scripts are insufficient.

# 57. CAPTCHA / Turnstile

A visible CAPTCHA or Turnstile is a security block.

Flow:

```text
detect
→ stop
→ capture useful evidence
→ update channel health
→ do not continue around challenge
```

# 58. Browser Action Loop

Normal interaction:

```text
snapshot
→ classify
→ choose bounded action
→ deterministic validation
→ execute
→ snapshot
→ repeat
```

Avoid giant opaque form scripts.

# 59. One Meaningful Mutation

Default:

```text
one meaningful browser mutation
→ observe resulting state
```

Short deterministic field batches are permitted when the form is known to be stable.

Navigation remains observable.

# 60. Submit Preconditions

Before final Submit:

```text
correct application phase
supported required fields complete
no blocking validation errors
approved resume present when required
candidate identity correct
generated content approved
submit control exists
submit control enabled
```

Capture pre-submit evidence where practical.

# 61. Submit Observation

After final Submit:

```text
do not retry immediately
→ wait for bounded state change
→ snapshot
→ classify
→ collect evidence
```

Possible outcomes:

```text
confirmed
already_applied
ambiguous
blocked
expired
network failure
unknown
```

Unknown after Submit is not success.

# 62. Evidence Hierarchy

Strong:

```text
explicit platform confirmation
trusted ATS confirmation
verified application-history presence
```

Supporting:

```text
confirmation URL
confirmation email
final-page text
screenshot
browser state transition
```

Weak:

```text
button-click success
network activity
local function returned normally
```

Weak evidence alone cannot confirm an application.

# 63. Evidence Record

Conceptually:

```text
attempt_id
channel
timestamp
final_url
page_phase
confirmation_signal
confirmation_excerpt
screenshot_path
email_reference
```

Keep evidence compact and durable. Do not store full HTML by default.

# 64. Screenshot Policy

Capture at useful points:

```text
final confirmation
ambiguous submit
security block
form-schema failure
OTP failure
critical browser failure
optional sampled success
```

Do not capture every action by default.

# 65. Screenshot Naming

Use attempt-centric names:

```text
<attempt_id>_<stage>.png
```

Examples:

```text
A123_confirmation.png
A123_form_changed.png
A123_antibot.png
```

# 66. Sensitive Browser State

Treat as sensitive:

```text
cookies
local/session storage
authorization state
browser profiles
screenshots
downloaded documents
```

Never commit or log secrets.

