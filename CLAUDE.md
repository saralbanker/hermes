# Orivon — AI Agent Manifest

This project runs the **Antigravity Kit** agent system. All agents, skills, workflows, rules, and scripts live in `.agent/`.

---

## MANDATORY: Read at Session Start

Read these two files before any work begins:

1. `.agent/ARCHITECTURE.md` — full map of agents, skills, workflows, rules, scripts
2. `.agent/rules/GEMINI.md` — master behavioral protocol (request classifier, agent routing, tier rules)

---

## Always-On Rules (inline — no extra reads needed)

### Engineering Standards
- TypeScript strict mode. Never use `any` without a comment explaining why.
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
- No output is "done" until the active skill's validation gate is fully checked.

---

## Lazy Loading Protocol

When a request arrives:

```
1. Identify domain (Frontend / Backend / Security / DB / Mobile / etc.)
2. Select agent → read .agent/agents/{name}.md
3. Check agent frontmatter "skills:" → read .agent/skills/{name}/SKILL.md
4. Apply rules from GEMINI.md + agent file + skill file
5. Max 2 skills loaded simultaneously — context window is a shared resource
```

Never pre-load agents or skills. Load only what the current request needs.

---

## Path Map

| Resource   | Path                                  | Count |
|------------|---------------------------------------|-------|
| Agents     | `.agent/agents/{name}.md`             | 23    |
| Skills     | `.agent/skills/{name}/SKILL.md`       | 49    |
| Workflows  | `.agent/workflows/{name}.md`          | 11    |
| Rules      | `.agent/rules/*.md`                   | 5     |
| Scripts    | `.agent/scripts/checklist.py` etc.    | 2 master + 18 skill-level |

### Quick Agent Lookup

| Need            | Agent                  |
|-----------------|------------------------|
| Web UI/UX       | `frontend-specialist`  |
| API / server    | `backend-specialist`   |
| Mobile          | `mobile-developer`     |
| Database        | `database-architect`   |
| Security        | `security-auditor`     |
| Testing         | `test-engineer`        |
| Debugging       | `debugger`             |
| Planning        | `project-planner`      |
| Multi-domain    | `orchestrator`         |
| Full-stack TDD  | `senior-engineer`      |
| SRE / incidents | `system-investigator`  |
| Pre-release QA  | `quality-enforcer`     |
