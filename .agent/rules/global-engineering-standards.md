# Global Engineering Standards

Always apply across every project, every stack:

- TypeScript strict mode when available. Never use `any` without a comment explaining why.
- Functions: max 50 lines. If longer, split at the single responsibility boundary.
- No silent failures. Every error must be thrown, logged, or explicitly swallowed with a comment.
- No hardcoded secrets, API keys, passwords, or environment-specific values in source files.
- Every async function that can reject must have error handling at the call site or propagate explicitly.
- Prefer explicit over implicit. Prefer readable over clever. Code is read 10x more than written.
- No dead code in commits. Remove it; git history preserves it.
- Naming: variables are nouns, functions are verbs, booleans are `is/has/can/should` prefixed.
