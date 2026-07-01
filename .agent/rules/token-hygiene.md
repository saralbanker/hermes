# Token Hygiene

Manage context window efficiently on every task:

- Never re-inject information already established in the conversation — reference it ("as above")
- Summarize current state before loading a new skill (context delta, not full recap)
- If context window is filling: summarize → pick path → continue. Never truncate silently.
- Long files: load only the relevant section, not the entire file
- Tool call results: extract only the needed data, don't echo full output back into context
- Between skill handoffs: use SkillHandoff interface — completed_skill, output_summary, artifacts, context_delta only
