---
name: research-engine
description: "Use this skill when investigating an unfamiliar technology, evaluating options, or synthesizing information from multiple sources into a definitive answer with citations."
version: 1.0.0
triggers:
  - "research"
  - "investigate"
  - "best way to"
  - "compare options"
  - "what is the difference"
  - "should I use"
  - "@research-engine"
token_budget: 2500
tools_required:
  - web_search
  - view_file
output_contract:
  format: "Research synthesis: conclusion + evidence + sources + confidence"
  includes:
    - conclusion
    - supporting-evidence
    - sources
    - confidence-level
    - caveats
works_with:
  - task-planner
  - architecture-analyst
  - dependency-analyzer
risk: low
---

## Mission

Investigate unfamiliar technologies, evaluate competing options, and synthesize information from multiple sources into definitive answers with cited evidence. Every factual claim has a source. Every recommendation has a confidence level. The output is a synthesis (new conclusion from combined evidence), not a summary (restatement of sources). Answer the question first, then provide the evidence.

## When To Activate

- User asks "which is better: X or Y?"
- User needs to evaluate a technology, library, or approach
- User asks "what's the best way to do X?"
- User needs information synthesis from multiple sources
- **Anti-trigger**: Do NOT activate for known, established patterns (use domain-specific skills). Activate when the answer requires investigation, not recall.

## Core Concepts

### 1. Source Hierarchy
Not all sources are equal. Rank by authority:

| Tier | Source Type | Trust Level | Example |
|------|-----------|-------------|---------|
| 1 | Official documentation | High | React docs, MDN, RFC specs |
| 2 | Peer-reviewed / official blogs | High | Google SRE book, Martin Fowler's blog |
| 3 | Established tech blogs | Medium | CSS-Tricks, Smashing Magazine, LogRocket |
| 4 | Stack Overflow (high votes) | Medium | Answers with 100+ votes, accepted answers |
| 5 | Individual blogs / tutorials | Low | Personal blogs, Medium articles |
| 6 | AI-generated content | Very Low | Verify against Tier 1-3 before citing |

Never cite a single Tier 5 source as authoritative. Corroborate with Tier 1-3.

### 2. Recency Bias Awareness
A 2019 article about React hooks may be dangerously outdated. For fast-moving domains:
- **LLMs/AI**: Prefer content from last 6 months
- **Frameworks (React, Next.js, Vue)**: Prefer content from last 12 months
- **Languages (JS, Python, Rust)**: Content from last 2 years is usually fine
- **Computer Science fundamentals**: Evergreen — age doesn't matter

Always check publication date. Prefix old sources with their date: "As of March 2023, ..."

### 3. Lateral Reading
Before trusting a source, check what OTHER sources say about the same claim. Experts don't read one article deeply — they check multiple sources quickly to triangulate the truth. If 3 independent sources agree, confidence is high. If only 1 source makes a claim, confidence is low.

### 4. Claim-Source-Confidence Format
Every factual claim must include:
```
Claim: Next.js App Router uses React Server Components by default.
Source: https://nextjs.org/docs/app/building-your-application/rendering
Confidence: HIGH (official documentation, current version)
```
Never state a claim without attribution. "I think..." or "It's generally accepted that..." without a source = unverified claim.

### 5. Synthesis vs Summary
- **Summary**: "Source A says X. Source B says Y. Source C says Z." (This is a book report.)
- **Synthesis**: "Based on evidence from A, B, and C, the answer is Q because of the pattern P that emerges when combining their findings." (This is research.)

Always synthesize. Answer the question in the first paragraph. Provide evidence after.

## Reasoning Graph

```
[INPUT: Research question]
  │
  ├─► [CLASSIFY: Factual lookup or decision/comparison?]
  │     │
  │     ├─► [BRANCH A: Factual lookup ("what is X", "how does Y work")]
  │     │     ├── Search official docs first (Tier 1)
  │     │     ├── Verify with 1 secondary source (Tier 2-3)
  │     │     ├── Check publication date — is this current?
  │     │     ├── State answer with source + confidence
  │     │     └── [VALIDATE: answer sourced, confidence stated]
  │     │
  │     └─► [BRANCH B: Decision/comparison ("should I use X or Y")]
  │           ├── Form 3 search queries:
  │           │     ├── "X vs Y [current year]"
  │           │     ├── "when to use X" / "X use cases"
  │           │     └── "X limitations" / "X problems"
  │           ├── Read top 3 results per query
  │           ├── Extract: where X wins, where Y wins, consensus points
  │           ├── Check recency of ALL sources
  │           ├── Apply lateral reading: do sources agree?
  │           ├── Synthesize: for THIS user's context, which fits better?
  │           ├── State: Recommendation + Why + Caveats + Sources
  │           └── [VALIDATE: synthesis, not summary]
  │
  └─► [OUTPUT: Research synthesis]
```

## Execution Steps

### Branch B: Decision/Comparison (Most Common)

### Step 1: Form Search Queries
For "Should I use Prisma or Drizzle?":
- Query 1: `"Prisma vs Drizzle 2025"`
- Query 2: `"when to use Drizzle ORM"`
- Query 3: `"Prisma ORM problems limitations"`

### Step 2: Read and Extract
For each of the top 3 results per query:
- Note the source tier (official? blog? forum?)
- Note the publication date
- Extract key claims with evidence

### Step 3: Triangulate
What do most sources agree on? What's contested? Contested claims get lower confidence.

### Step 4: Check Dates
Discard articles >2 years old for framework comparisons. Flag anything >1 year as "as of [date]."

### Step 5: Synthesize
Combine findings into a recommendation for the user's specific context:
```
Conclusion: For your use case (serverless, TypeScript, simple CRUD), Drizzle is the better fit.
Evidence: Drizzle's SQL-like syntax has lower abstraction overhead (Source 1), faster cold starts 
  in serverless (Source 2), and type-safe queries without code generation (Source 3).
Caveat: Prisma has a larger ecosystem and more mature migration tooling (Source 4).
Confidence: MEDIUM — most sources agree, but the ecosystem gap may matter for complex schemas.
```

### Step 6: Cite Sources
Every factual claim links to a source. No unsourced assertions.

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| Sources contradict each other | Different versions, contexts, or use cases | Note the version/context dependency; provide conditional answer |
| No authoritative sources found | Very new or niche topic | State confidence as "LOW"; use first-principles reasoning; mark as experimental |
| Research is outdated | Used old articles without checking dates | Re-search with `[topic] [current year]`; filter by date |
| User gets paralyzed by options | Too many alternatives presented without clear recommendation | Always lead with ONE recommendation + why; alternatives are secondary |

## Validation Gate

- [ ] Conclusion stated first (directly answers the question)
- [ ] Every factual claim has a cited source with URL
- [ ] Source tiers noted (official docs vs blog vs forum)
- [ ] Sources checked for recency (dates noted, old sources flagged)
- [ ] Confidence level stated (HIGH / MEDIUM / LOW)
- [ ] At least 1 caveat or limitation acknowledged
- [ ] Output is synthesis (new conclusion), not summary (restated sources)

## Output Contract

Research synthesis containing:
- **Conclusion**: Direct answer to the question (1-2 sentences, first paragraph)
- **Supporting evidence**: Key findings from sources, organized by argument
- **Sources**: Numbered list with URL, source tier, publication date
- **Confidence level**: HIGH (official sources agree) / MEDIUM (mixed sources) / LOW (sparse data)
- **Caveats**: Conditions under which the recommendation changes
