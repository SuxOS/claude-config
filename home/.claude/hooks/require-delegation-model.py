#!/usr/bin/env python3
"""PreToolUse hook (matcher: Agent) — enforce cardinal rule #1: never inherit the model.

Blocks an Agent delegation that sets no explicit model=, so every fork picks its tier
deliberately (haiku for mechanical, top for hard verify/judge) instead of silently
inheriting the orchestrator's session model — the exact failure rule #1 names.

Exempt: subagent_type=fork, which inherits the parent model by design and cannot override.
Fail-open on any parse error — a hook bug must never wedge the session.
"""
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

if data.get("tool_name") != "Agent":
    sys.exit(0)

ti = data.get("tool_input") or {}

if ti.get("subagent_type") == "fork":
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
