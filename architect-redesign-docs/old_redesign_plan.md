The core architectural problem is visible directly in the code:

DB = jobs table
        ↓
status = discovered/scored/tailored
        ↓
tailor only qualifying scored jobs
        ↓
apply only tailored jobs

There is no first-class concept of:

opportunity
freshness
open/closed
last_seen
last_revalidated
age bucket
application target
application attempt history
requeue eligibility
channel health

upsert_job() is INSERT OR IGNORE, so an existing URL does not get refreshed. get_all_urls() considers every historical URL a permanent duplicate. collapse_duplicates() operates only on currently active statuses. apply.py only constructs its queue from tailored. And pipeline.py uses raw DB status counts as its reserve mechanism.

That's why the system has effectively become:

seen once = remember forever
scored once = scored forever
filtered once = filtered forever
expired once = expired forever

That is fundamentally wrong for a job-search system.

The latest database evidence makes the consequence obvious: 5,571 filtered, 1,436 expired, 795 scored, but only 50 confirmed submissions.

And the current run demonstrated the exact funnel collapse:

4,447 scraped
→ 115 new
→ 49 eligible
→ 12 qualifying
→ 5 tailored
→ 6 queued

before application execution.

2. The redesign should not be “fresh vs old jobs”

It should be an aging opportunity scheduler.

Your idea is correct, but I would formalize it as:

AGE BAND A
0–3 days       Fresh

        ↓ if A insufficient

AGE BAND B
4–7 days       Recent

        ↓ if B insufficient

AGE BAND C
8–14 days      Mature

        ↓ if C insufficient

AGE BAND D
15–21 days     Aging / final chance

        ↓

Discard only after confirmed closed / invalid

Every day:

Target = 100

Take all available eligible A
↓
if <100:
  consume B
↓
if still <100:
  consume C
↓
if still <100:
  consume D

So the scheduler never says:

“This job is old, therefore don't apply.”

Instead:

“This job is old, therefore it has lower temporal priority, but it remains an opportunity while it is still open and has never been applied to.”

That is a much stronger model.

3. The critical change: separate an Opportunity from a Listing

Right now a database row is essentially both.

That causes the tombstone problem.

Redesign conceptually to:

                   OPPORTUNITY
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
    Indeed listing   WWR listing   ATS listing
        │              │              │
        └──────────────┼──────────────┘
                       ↓
                canonical employer job
                       ↓
             application target resolver
                       ↓
            Greenhouse / Lever / Direct

One job can appear on five boards.

Hermes should store:

canonical opportunity
+
source observations

rather than treating every URL as a separate permanent record.

Canonical identity

Prefer:

ATS + job ID

then:

normalized employer + normalized title + location

then:

content fingerprint

rather than URL alone.

Thus:

Indeed URL
WWR URL
Himalayas URL
employer careers URL
Greenhouse URL

can all resolve to one opportunity.

4. Historical jobs should become recyclable

This is the part Gemini still didn't architect deeply enough.

Don't do:

filtered → tailored
expired → tailored

blindly.

Instead:

historical opportunity
        ↓
re-evaluation policy
        ↓
is it worth reconsidering?
        ↓
revalidate
        ↓
open?
        ↓
still eligible?
        ↓
still not applied?
        ↓
score/rerank
        ↓
queue

For example:

Reconsider
score 6.2
not applied
posting still open
age 9 days

→ eligible for Age Band C.

Do not reconsider
confirmed closed

→ permanently closed.

Reconsider after new evidence
location_unknown

→ re-fetch/resolve location.

Reconsider after rule correction
date metadata malformed

→ revalidate actual posting.

Do not reconsider
submitted
already_applied
hard excluded role
confirmed residency restriction

That gives you a living inventory, rather than a dead ledger.

5. The DB needs a real opportunity lifecycle

I would redesign the schema around this idea:

opportunities
sources
application_targets
application_attempts
daily_runs

You don't necessarily need five completely separate databases/tables immediately, but conceptually these are distinct entities.

An opportunity should have fields approximately like:

id
canonical_key
company
title
location
description
date_posted
first_seen_at
last_seen_at
last_revalidated_at
last_revalidated_status
age_bucket
fit_score
fit_confidence
tier
salary_status
application_target_id
current_state
next_recheck_at

And an application attempt should be append-only:

opportunity_id
attempt_id
channel
started_at
finished_at
result
evidence
screenshot
browser_profile
failure_reason

This is much stronger than incrementing attempts on the job row forever.

6. Two independent fallback systems

This is the part I think is most important.

You actually need two fallback dimensions.

A. Opportunity-age fallback
Fresh 0–3d
   ↓
4–7d
   ↓
8–14d
   ↓
15–21d
B. Application-channel fallback

For a single opportunity:

Known direct ATS
      ↓
Greenhouse
      ↓
Lever
      ↓
Direct employer form
      ↓
Indeed external application
      ↓
supported redirect
      ↓
unsupported / blocked

But this must be capability-driven.

Example:

WWR
 ↓
employer URL
 ↓
Greenhouse
 ↓
Greenhouse applier

not:

WWR
 ↓
WWR application
 ↓
account wall
 ↓
dead

This is exactly where the current resolver architecture needs to evolve.

7. Browser automation: this is where the interesting research matters

I've researched the current alternatives.

Laya / Jev-style architecture

The project you're referring to appears to be laya-browser-agent.

The important thing is that Laya is not another general LLM. It is a browser-specific decision model.

It receives structured page state and decides things like:

CLICK element 17
TYPE_TEXT element 4
SELECT element 8
WAIT
DONE
BLOCKED

rather than generating arbitrary prose or selectors. The current browser-tuned v17s checkpoint is a 322M model, and the project reports 17–23 ms decision latency in its benchmark environment.

The project also explicitly separates:

model decides:
  what action?
  which element?

host program decides:
  is this action allowed?
  what does element N map to?
  should it execute?

That is exactly the architecture Hermes needs.

And its authors explicitly warn that screenshots are unnecessary for the normal decision loop; structured DOM state is the preferred path.

The catch

Laya does not solve everything.

Known limitations include:

closed/collapsed UI
shadow-root edge cases
frames
canvas
uploads
nested scrolling
keyboard widgets

and zero-shot performance is domain dependent. The current benchmark is also primarily the project's own evaluation, so Hermes must run its own real-form benchmark.

Verdict

Yes, Laya is worth integrating.

But:

Laya ≠ browser replacement

Use:

CDP/browser
   ↓
structured DOM/ARIA state
   ↓
Laya decision
   ↓
validated action

not:

Laya
↓
replace entire browser
8. I would change the browser substrate too

You currently have:

DrissionPage
+
Playwright
+
Xvfb

That's workable, but unnecessarily fragmented.

One interesting current option is Vercel's agent-browser.

It is a native Rust CLI/daemon using direct Chrome DevTools Protocol, supports persistent browser state, and can connect to existing Chrome instances over CDP. It does not require Node.js for its runtime daemon.

Browser Use's current low-level Actor API is also CDP-based rather than Playwright and is specifically designed for precise deterministic browser control alongside AI features.

So my browser stack would become:
Chrome/Chromium
      ↓
       CDP
      ↓
Browser Transport Layer
      ↓
State Extractor
      ↓
┌─────────────────────────────┐
│ deterministic form engine  │
│            ↓                │
│ Laya browser decider       │
│            ↓                │
│ visual fallback            │
└─────────────────────────────┘
      ↓
Action Validator
      ↓
Browser
      ↓
Outcome Verifier

Playwright can remain as a compatibility adapter for existing ATS code, but it should no longer be Hermes' architectural center.

9. What about Stagehand and Skyvern?

Stagehand is interesting, but it's primarily an AI layer around browser automation and can operate through Playwright/CDP. It doesn't eliminate the fundamental browser-control layer Hermes already has.

Skyvern is considerably more ambitious: LLM + computer vision + browser automation, with a Playwright-compatible interface. It is powerful, but its open-source core is AGPL-3.0 and the stack is much heavier than what Hermes needs on a 16GB CPU-only laptop.

So:

Laya + CDP
        ↑
primary recommendation

Stagehand
        ↑
experimental adapter

Skyvern
        ↑
research/fallback laboratory, not core Hermes
10. The screenshot problem should be solved differently

Right now screenshots are too deeply associated with browser verification.

I would make the browser state hierarchy:

LEVEL 1
DOM / ARIA / labels / values

LEVEL 2
DOM mutation + URL + network responses

LEVEL 3
Laya structured decision

LEVEL 4
visual model

LEVEL 5
screenshot evidence

Notice:

screenshot ≠ control mechanism

Screenshot becomes:

evidence
diagnostics
visual fallback

rather than the thing Hermes fundamentally depends on.

Jev itself follows the same philosophy: structured browser state is the primary loop, screenshots are auxiliary.

11. The visual fallback is where Qwen3.5 becomes interesting

Your current Qwen3 4B is being forced to do too much:

job scoring
answer generation
cover letters

I wouldn't replace it with one bigger model.

I would replace the monolith with a model cascade.

Current Qwen3.5 has official 0.8B, 2B, 4B and 9B sizes, with multimodal support. Qwen3.5-4B is currently a particularly interesting middle point for local deployment.

The published Qwen3.5-4B results show:

MMLU-Pro       79.1
IFEval         89.8
BFCL-V4        50.3
TAU2-Bench     79.9
DeepPlanning   17.6
LiveCodeBench  55.8

while 9B is stronger in several areas but substantially larger.

For Hermes on 16GB RAM + CPU-only + Chrome, I would test Qwen3.5-4B quantized first, not jump to 9B.

12. Multiple SLMs: yes, but NOT six simultaneously

This is where I disagree with the naive "6 models" idea.

Six concurrently resident models would be counterproductive on your machine.

Instead:

                HERMES MODEL ROUTER

                 ┌─────────────┐
                 │ deterministic│
                 │ rules        │
                 └──────┬──────┘
                        ↓
              ┌─────────────────┐
              │ Embed / Rerank  │
              └────────┬────────┘
                       ↓
                ┌──────────────┐
                │ Laya 322M    │
                │ browser      │
                └──────────────┘

                ┌──────────────┐
                │ Qwen3.5 0.8B │
                │ cheap classify│
                └──────────────┘

                ┌──────────────┐
                │ Qwen3.5 4B   │
                │ fit/answers/ │
                │ cover/vision │
                └──────────────┘

So effectively:

Model 1 — Embedding

Cheap retrieval.

Model 2 — Reranker

Use a true reranker instead of asking a generative LLM to do everything.

Jina Reranker v3.5 is currently a 0.6B listwise reranker designed specifically for ranking many documents jointly, and its authors report better BEIR results than their v3 predecessor and similar-sized alternatives.

There is one licensing concern: Jina v3.5 is CC BY-NC 4.0, so I would avoid making it a hard dependency if Hermes might become commercial.

Model 3 — Laya v17s

Browser actions only.

Model 4 — Qwen3.5-0.8B/2B

Ultra-cheap extraction/classification.

Model 5 — Qwen3.5-4B

The general "thinking" brain:

job-fit adjudication
application questions
cover letters
ambiguous text
visual fallback

That's enough.

13. New scoring architecture

This is another major redesign.

Stop:

Qwen → 1–10 → if >=6.5

Instead:

               HARD GATE
                   ↓
        legally / geographically
         / role-wise eligible?
                   ↓
             RETRIEVAL
                   ↓
              RERANKER
                   ↓
            FIT ADJUDICATOR
                   ↓
     ┌──────────────────────────┐
     │ skills                   │
     │ seniority                │
     │ role alignment           │
     │ experience gap           │
     │ location confidence      │
     │ salary confidence        │
     │ project relevance        │
     │ application friction     │
     │ confidence               │
     └──────────────────────────┘
                   ↓
             PRIORITY SCORE

And crucially:

priority score ≠ automatic rejection

The score ranks opportunities.

The hard gates decide whether something is actually impossible.

That solves the current 6.0/6.5/7.0 artificial cliff.

14. The resulting daily scheduler

Every day:

TARGET = 100

POOL A
0–3 days
──────────────
take highest-ranked eligible
until A exhausted

POOL B
4–7 days
──────────────
if target remains

POOL C
8–14 days
──────────────
if target remains

POOL D
15–21 days
──────────────
if target remains

Within each age bucket:

fit
× role priority
× source quality
× application-channel reliability
× salary quality
× application friction
× evidence confidence

But age bucket always has precedence because that is your explicit business rule.

15. Continuous discovery becomes independent from application

This is another important difference.

Don't do:

discover
→ score
→ tailor
→ apply
→ repeat

Do:

             DISCOVERY PLANE
                    │
          continuously ingest
                    ↓
             opportunity DB
                    │
          revalidation engine
                    ↓
              ranking pool
                    │
                    ↓
             APPLICATION PLANE
                    │
          continuously drain
                    ↓
             evidence ledger

Discovery can be running while applications are happening.

Revalidation can run while the browser is idle.

Response watcher is separate.

That is what makes 24/7 actually meaningful.

16. The final architecture
                         HERMES
                           │
                 ┌─────────┴──────────┐
                 │                    │
          DISCOVERY PLANE       APPLICATION PLANE
                 │                    │
        ┌────────┴────────┐     ┌─────┴──────────┐
        │                 │     │                │
     Indeed             ATS   Age Scheduler    Channel Router
     WWR              Greenhouse│                │
     Arbeitnow        Lever     │          ┌─────┴──────┐
     Remotive         Direct    │          │            │
     Himalayas        etc.      │       Greenhouse   Indeed
     RemoteOK                  │       Lever         Direct
        │                       │
        └──────────┬────────────┘
                   ↓
             Opportunity DB
                   │
        ┌──────────┼───────────┐
        ↓          ↓           ↓
     Seen data  Open state   Age state
        │          │           │
        └──────────┼───────────┘
                   ↓
              FIT PIPELINE
                   │
        deterministic gates
                   ↓
              embeddings
                   ↓
               reranker
                   ↓
             Qwen3.5-4B
                   ↓
             priority rank
                   ↓
           age-band scheduler
                   ↓
          application channel
                   ↓
             Browser Gateway
                   │
              Chrome + CDP
                   │
        ┌──────────┼──────────┐
        ↓          ↓          ↓
    DOM engine   Laya      Visual Qwen
        │          │          │
        └──────────┼──────────┘
                   ↓
             action validator
                   ↓
                submit
                   ↓
           evidence verifier
                   ↓
            attempts ledger
                   ↓
            Gmail / responses

This is the architecture I'd build.

It is considerably more resilient than the current status-driven pipeline while still staying within your constraints:

Python
SQLite
Ollama
Chrome
CDP
Xvfb
systemd
Gmail
local SLMs

No Kubernetes. No Redis. No Postgres. No paid browser API.

17. Most important conclusion

The redesign should not be:

“Lower the threshold and apply to 202 more jobs.”

It should be:

Turn Hermes from a batch job scraper into a continuously aging opportunity scheduler with reusable historical inventory, dynamic application-channel fallback, structured-browser control, specialized local models, and independent evidence verification.

That is the version capable of surviving depleted fresh supply.

And the Laya research gives us a particularly good way to attack the current browser weakness: keep Chrome/CDP as the execution substrate, but replace brittle selector-centric reasoning with a small browser-specific decision model.
