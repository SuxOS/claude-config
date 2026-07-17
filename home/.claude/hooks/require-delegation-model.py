#!/usr/bin/env python3
"""PreToolUse hook (matcher: Agent) — enforce cardinal rule #1: never inherit the model.

Blocks an Agent delegation that would silently inherit the orchestrator's session model
instead of picking a tier deliberately (haiku for mechanical, top for hard verify/judge) —
the exact failure rule #1 names.

That only applies to the generic default agent: subagent_type absent, "general-purpose", or
"claude" (FleetView's own default) all resolve to the session model with no model= given.
A NAMED subagent_type (Explore, Plan, code-reviewer, or any other custom agent) has its model
pinned in its own definition/frontmatter — omitting model= there means "use the agent's
deliberately-chosen tier," not "inherit the session model," and the Agent tool's own guidance
recommends omitting it in that case. So named types are exempt, same as subagent_type=fork
(which inherits the parent model by design and cannot override).

Fail-open on any parse error — a hook bug must never wedge the session.
"""
import json
import sys

GENERIC_SUBAGENT_TYPES = {"", "general-purpose", "claude"}

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

if data.get("tool_name") != "Agent":
    sys.exit(0)

ti = data.get("tool_input") or {}

subagent_type = ti.get("subagent_type") or ""
if subagent_type == "fork":
    sys.exit(0)

if subagent_type not in GENERIC_SUBAGENT_TYPES:
    sys.exit(0)

if ti.get("model"):
    sys.exit(0)

print(
    "Rule #1 (never inherit the model): this Agent delegation sets no explicit model=. "
    "Set model to the tier that fits THIS task — haiku for mechanical work, a top tier for "
    "a hard verify/judge/bug-hunt — then retry. (subagent_type=fork is exempt.)",
    file=sys.stderr,
)
sys.exit(2)
