# Agent MAP — keyword → file
# Read this file. Load ONLY the row that matches. Do not read the whole .agent/ folder.

## Skills → .agent/skills/{name}/SKILL.md

| Keywords | SKILL.md path |
|---|---|
| debug, error, bug, crash, not working | `systematic-debugging/SKILL.md` |
| api, rest, graphql, endpoint, route | `api-patterns/SKILL.md` |
| database, sql, schema, migration, query | `database-design/SKILL.md` |
| test, tdd, jest, vitest, e2e, coverage | `testing-patterns/SKILL.md` |
| nextjs, react, component, hooks, frontend | `nextjs-react-expert/SKILL.md` |
| performance, slow, optimize, speed, vitals | `performance-optimizer/SKILL.md` |
| security, pentest, owasp, vuln, exploit | `red-team-tactics/SKILL.md` |
| plan, breakdown, roadmap, tasks | `plan-writing/SKILL.md` |
| brainstorm, discover, ideate, questions | `brainstorming/SKILL.md` |
| clean, refactor, quality, standards | `clean-code/SKILL.md` |
| architecture, pattern, system design | `architecture-analyst/SKILL.md` |
| review, audit, checklist, code-review | `code-review-checklist/SKILL.md` |
| mcp, model context protocol, tool | `mcp-builder/SKILL.md` |
| lint, validate, format, eslint | `lint-and-validate/SKILL.md` |
| deps, packages, npm, dependencies | `dependency-analyzer/SKILL.md` |
| seo, geo, ranking, search, meta | `geo-fundamentals/SKILL.md` |
| audit, compliance, system check | `system-auditor/SKILL.md` |
| code gen, synthesize, scaffold | `code-synthesizer/SKILL.md` |

## Agents → .agent/agents/{name}.md

| Keywords | Agent file |
|---|---|
| ui, ux, design, web, tailwind, css | `frontend-specialist.md` |
| api, server, backend, node, express | `backend-specialist.md` |
| mobile, ios, android, react native, flutter | `mobile-developer.md` |
| security audit, threat, vulnerability | `security-auditor.md` |
| pentest, offensive, red team | `penetration-tester.md` |
| debug, fix, root cause, diagnose | `debugger.md` |
| test, qa, automation, playwright | `test-engineer.md` |
| deploy, docker, ci/cd, devops, nginx | `devops-engineer.md` |
| speed, web vitals, profiling | `performance-optimizer.md` |
| multi-agent, orchestrate, coordinate | `orchestrator.md` |
| plan, discovery, roadmap, pm | `project-planner.md` |
| game, unity, godot, phaser | `game-developer.md` |
| docs, documentation, readme | `documentation-writer.md` |

## Workflows → .agent/workflows/{name}.md (slash commands)

| Command | When to use |
|---|---|
| `/plan` | Task breakdown before any complex work |
| `/create` | Build a new feature or app |
| `/debug` | Systematic issue diagnosis |
| `/enhance` | Improve existing code quality |
| `/test` | Run or write tests |
| `/deploy` | Deployment procedure |
| `/brainstorm` | Socratic discovery for unclear requirements |
| `/orchestrate` | Multi-agent coordination |
| `/preview` | Preview changes before applying |
| `/status` | Project health check |
| `/ui-ux-pro-max` | Design with 50 styles, 21 palettes |

## Master files (always read before complex tasks)

| Purpose | Path |
|---|---|
| Full orchestration rules | `.agent/rules/GEMINI.md` |
| Full index (agents + skills + scripts) | `.agent/ARCHITECTURE.md` |
| Quick validate | `python .agent/scripts/checklist.py .` |
| Full pre-deploy verify | `python .agent/scripts/verify_all.py .` |
