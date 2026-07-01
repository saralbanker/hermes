# Skill Routing Protocol

Before attempting any task free-form, check if a skill exists:

1. Scan `.agent/skills/` for semantic match to the task
2. Use `@skill-name` for explicit activation
3. Multi-step tasks: activate `task-planner` first, then specialist skills
4. Skill missing + task is complex: activate `skill-forge` to research and create it
5. Never load more than 2 skills simultaneously — context hygiene
6. Skill handoff: pass only `context_delta` (what changed/was found), never full history
7. After skill completes, run its Validation Gate before declaring done
