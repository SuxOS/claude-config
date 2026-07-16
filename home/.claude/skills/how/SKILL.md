---
name: how
description: Given a goal, find the specific skill/plugin/MCP/agent combo that accomplishes it and hand back a ready-to-paste prompt — not generic advice. Use for "how do I do X", "how can I X using what I have available", "what's the best way to X with my tools", "is there a skill/MCP for X", "what would I even ask for X". Read-only unless the user says go — how finds and hands off; it doesn't execute by default.
---

# how

**means:** turn "how do I do X" into the exact prompt that fires the right skill/plugin/MCP/agent — grounded in what's actually connected right now, not a generic tutorial. `how` surveys and hands back a prompt; it only executes if the user says so.

## Step 0 — pin down X

If the goal is vague ("how do I manage my finances better") ask one clarifying question before surveying — a broad goal maps to nothing specific and wastes the survey. A concrete goal ("how do I see if any Cloudflare workers errored today") doesn't need clarification.

## Step 1 — survey what's active

Check, in order, stopping as soon as something is a clear fit:

1. **Skills** — scan the available-skills list (already in context) for name/description matches. This is the first stop: a skill packages a whole workflow, so a match here beats hand-rolling tool calls.
2. **MCP tools** — if a connected server plausibly covers it (its name or instructions mention the domain) but its tools are deferred, `ToolSearch` for it before ruling it out. Don't guess a tool doesn't exist without searching.
3. **Agents** — if the task is open-ended research/execution with no matching skill, name the right `Agent` subagent type instead.

Don't stop at the first plausible skill if a second one is a materially better fit — but don't enumerate every near-miss either. One primary recommendation, one alternate at most.

## Step 2 — if nothing active fits, check what's discoverable

Before saying "you don't have anything for this," check whether it's installable:

- MCP connector gap → `mcp-registry` (`search_mcp_registry` / `suggest_connectors`) for a connector that would cover it.
- Skill/plugin gap → say so plainly and suggest `skill-creator` if it's a recurring need, rather than inventing a fake tool name.

Only reach here after Step 1 comes up empty — most asks are already covered by something active.

## Step 3 — hand back the prompt, not a lecture

The deliverable is a single copy-pasteable prompt the user could send right now to get X done, plus one line on which skill/MCP/agent it invokes and why that one. Not:
- a survey of every tool that's tangentially related
- an explanation of how the skill/MCP works internally
- multiple alternative prompts unless two approaches are genuinely close

```
**Use:** <skill-name | MCP tool | agent type>
**Prompt:** <the exact text to send>
```

Then ask: "want me to run that now?" — if yes, send the prompt as the next turn's actual request (invoke the skill/tool directly), don't just repeat it back.

## Rails

- Never invent a skill, plugin, or MCP tool name that isn't in the current session's available list or confirmed via `mcp-registry`/marketplace search — a plausible-sounding fake name is worse than admitting a gap.
- If the fit is genuinely ambiguous between two tools, say so in one line rather than picking silently — but don't hedge when one is clearly right.
