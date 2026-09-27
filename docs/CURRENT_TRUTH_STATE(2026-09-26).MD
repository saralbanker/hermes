# Hermes — Current Truth State

**Repository:** saralbanker/hermes
**Branch:** overhaul-2026-09-23
**Purpose:** Single source of truth for future development, debugging, planning, and execution.

---

# System Purpose

Hermes is a local-first job application automation system.

Primary objective:

```text
Discover jobs
→ Filter jobs
→ Score jobs
→ Tailor application material
→ Submit applications
→ Monitor employer responses
```

The system is designed to run unattended on a Linux laptop with zero recurring API costs.

Local models are preferred over paid APIs.

---

# Runtime Architecture

```text
systemd timers
        │
        ▼
run_hermes.sh
        │
        ▼
pipeline.py
        │
        ├── discover
        ├── score
        ├── tailor
        └── apply
                │
                ├── Indeed
                ├── Greenhouse
                ├── Lever
                ├── Ashby
                └── Direct Forms

response_watcher.py
        │
        ▼
Gmail IMAP
        │
        ▼
Employer Response Tracking
```

---

# Current Proven Capabilities

## Scheduler

Verified:

* systemd timer execution
* scheduled runs
* overlap prevention
* crash recovery support

Known run schedule:

```text
08:00
13:00
19:00
```

---

## Gmail Watcher

Verified:

* Gmail App Password authentication
* IMAP access
* message polling
* employer response detection
* acknowledgement detection
* rejection detection

---

## Discovery

Verified sources:

```text
Indeed
Greenhouse
Lever
Ashby
Himalayas
Remotive
RemoteOK
```

Discovery is functional.

---

## Scoring

Verified:

* Ollama integration
* Local embedding generation
* Local LLM scoring
* Score persistence

Primary goal:

```text
Reduce application volume
Increase application quality
```

---

## Tailoring

Verified:

* Resume tailoring
* Truthfulness validation
* Project-based customization
* Profile-driven generation

Tailoring uses local models.

---

## Indeed

Verified:

* Real production submissions
* Application history verification
* Employer acknowledgement evidence
* Automated application flow

Known limitation:

```text
Some custom Indeed forms can stall.
```

---

## Greenhouse

Verified:

* Real production submission
* OTP retrieval
* OTP insertion
* Employer acknowledgement email

Greenhouse is currently the most proven ATS channel.

---

## Response Monitoring

Verified:

```text
Acknowledgements
Rejections
Employer replies
Interview detection pipeline
```

---

# Current Partially Verified Capabilities

## Direct Forms

Implemented.

Verified:

```text
Routing exists
Execution path exists
Form engine exists
Tests exist
```

Not yet verified:

```text
Confirmed production submission
```

Current status:

```text
Implemented
Not production proven
```

---

## Lever

Implemented.

Verified:

```text
Discovery
Routing
Form support
```

Not yet verified:

```text
Confirmed production submission
```

Current status:

```text
Unverified
Not known broken
```

---

# Current Known Problems

## Ashby

Current issue:

```text
Anti-bot rejection
```

Observed behavior:

```text
Submission attempt
→ Platform accepts request
→ Platform rejects as suspected automation
```

Current status:

```text
Implemented
Blocked by platform
```

---

## Throughput

Current proven throughput is significantly below target.

Primary bottleneck is not browser automation.

Primary bottlenecks are:

```text
Filtering
Scoring
Expired jobs
Unsupported forms
Platform restrictions
Job supply
```

---

## Direct Form Coverage

Current direct-form support exists but is incomplete.

Additional employer-site coverage is still required.

---

# Database Truth

Primary database:

```text
db/applications.db
```

The database is the authoritative source for:

```text
Jobs
Scores
Application state
Attempts
Responses
Daily limits
```

When documentation conflicts with database records:

```text
Database wins.
```

---

# State Machine Truth

Core progression:

```text
discovered
    ↓
scored
    ↓
tailored
    ↓
applying
    ↓
submitted
```

Common terminal states:

```text
submitted
already_applied
blocked_antibot
form_changed
failed
submission_unconfirmed
```

Maximum attempts:

```text
3
```

---

# Current Job Strategy

Primary targets:

```text
AI Engineering
Backend Engineering
Software Engineering
Founding Engineer
Technical Startup Roles
```

Secondary targets:

```text
Senior roles
Lead roles
Stretch opportunities
```

Excluded:

```text
QA
Support
Tutor
Teaching
Non-technical operations
```

---

# Local-First Constraint

Project goal:

```text
Zero recurring API cost
```

Preferred stack:

```text
Ollama
Local models
SQLite
Playwright
Systemd
Python
```

Paid APIs are not part of the intended production architecture.

---

# Load-Bearing Files

These files should be treated as critical:

```text
src/pipeline.py
src/discover.py
src/score.py
src/tailor.py
src/apply.py

src/indeed_apply.py
src/ats_apply.py
src/direct_form.py

src/redirect_resolver.py
src/otp_resolver.py

src/db.py
src/states.py

src/filters.py
src/answers.py

src/response_watcher.py

config.yaml
profile/facts.md
```

Changes to these files can affect the entire system.

---

# Repository Reality

Hermes is no longer a prototype.

Hermes currently has:

```text
Working scheduler
Working Gmail watcher
Working scoring pipeline
Working tailoring pipeline
Working Indeed submissions
Working Greenhouse submissions
Working crash recovery
Working state management
```

The primary remaining work is:

```text
Increase submission throughput
Expand direct-form success rate
Validate Lever
Handle Ashby restrictions
Improve application yield
Increase daily capacity
```

---

# Evidence Rule

Priority order:

```text
Runtime Evidence
↓
Employer Emails
↓
Application History
↓
Database Records
↓
Logs
↓
Code
↓
Documentation
```

Higher evidence overrides lower evidence.

Documentation is never considered proof by itself.
