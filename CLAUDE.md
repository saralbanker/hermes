# Orivon

---

## Always-On Rules (inline — no extra reads needed)

### Engineering Standards
- Python: type-hint all function signatures. Never use `Any` without a comment explaining why.
- Functions: max 50 lines. Split at single responsibility boundary if longer.
- No silent failures. Every error must be thrown, logged, or explicitly swallowed with a comment.
- No hardcoded secrets, API keys, or environment-specific values in source files.
- No dead code in commits. Remove it — git history preserves it.
- Naming: variables = nouns, functions = verbs, booleans = `is/has/can/should` prefixed.

### Token Hygiene
- Never re-inject information already in the conversation — reference it.
- Long files: load only the relevant section, not the full file.
- Between skill handoffs: pass `context_delta` only — new info, not full history.
- If context is filling: summarize → pick path → continue. Never truncate silently.

### Output Quality
- **Code**: working code + explanation of non-obvious decisions + test/usage example.
- **Debug**: root cause identified (not symptom) + fix applied + validation result.
- **Architecture**: structure description + decision rationale + trade-offs noted.
- **Research**: conclusion first + supporting evidence + confidence level.
- No output is "done" until it has been validated (tests run or behavior verified).

---
