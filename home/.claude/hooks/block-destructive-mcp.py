#!/usr/bin/env python3
"""PreToolUse hook (matcher: `mcp__.*__.*`) — extend the Tier-A cardinal rail to MCP tool calls.

Every destructive-action guard in this repo — `block-destructive-git.py`, the `permissions.deny`
list, docs/security-model.md — only inspects Bash argv text. None of them look at MCP `tool_use`
calls at all (#260). `home/.claude/settings.json` enables a dozen+ MCP-bundling plugins, and the
GitHub plugin's server exposes tools like `merge_pull_request`, `push_files`, `delete_file` — none
of which appear anywhere in `permissions.deny`. Under `defaultMode: bypassPermissions` an MCP tool
call with no matching deny rule and no PreToolUse hook watching it sails through with zero
enforcement, the exact gap work/SKILL.md's Tier-A cardinal rule ("never force-push, merge/publish
without confirmation, hard-delete... without an explicit yes") is supposed to close.

Rather than hand-enumerate `mcp__plugin_<plugin>_<server>__<tool>` denies per plugin (the Cloudflare
pattern, settings.json:81-89 — accurate only for the one plugin someone audited live, and silently
stale for every other plugin, exactly the gap that let the GitHub plugin go completely unenumerated)
this generalizes the "cardinal rails as code" pattern (#163) the Bash rails already use: pattern-match
Tier-A verbs in the tool name itself, the way `block-destructive-git.py` pattern-matches Bash argv.
This scales to every current and future MCP plugin with no hand-maintained enumeration to drift.

The check: split `tool_name` on `__` (the plugin-namespacing delimiter, settings.README.md) and read
only the FINAL segment — the actual tool name, not the server/plugin namespace, so a coincidentally
verb-shaped server name can't false-positive every tool from it. Split that segment on `_`/`-` into
tokens and block if any token is an exact match for a Tier-A verb: merge, delete, push, force,
publish, deploy — the same verb set work/SKILL.md's cardinal rule names ("force-push, merge/publish,
hard-delete... irreversible/destructive"). `create`/`update`/`edit`/`list`/`get` tools are
deliberately NOT in scope here (not Tier-A on their own); the Cloudflare plugin's explicit per-tool
denies remain the belt for creates until a broader audit widens this rail's verb set.

Unlike the Bash rails, there is no repo state to consult that would prove a merge/delete/push/force/
publish/deploy MCP call safe (mirrors `block-destructive-git.py`'s `_merge_publish_hit`, #242) and no
human to answer an `ask` prompt in an autonomous/`bypassPermissions` session — so a match blocks
unconditionally. A human running this interactively hits the same block and can approve manually
outside the agent loop; that's the intended outcome for a Tier-A action, not a bug.

Fail-open on any error, and on anything this can't confidently parse — a hook bug, or a tool-name
shape this doesn't recognize, must never wedge the session (repo convention). Exit 2 = block; exit
0 = allow.
"""
import re
import sys

from _hookutil import load_hook_input

TIER_A_VERBS = {"merge", "delete", "push", "force", "publish", "deploy"}

_TOKEN_SPLIT_RE = re.compile(r"[_\-]+")


def offending_verb(tool_name):
    """Return the Tier-A verb token an `mcp__...__<tool>` tool_name hits, else None.

    Only the segment AFTER THE LAST `__` (the real tool name, not the server/plugin namespace) is
    scanned — see module docstring for why. Anything that doesn't look like a namespaced MCP tool
    name (no `__` at all) returns None rather than guessing."""
    if not isinstance(tool_name, str) or "__" not in tool_name:
        return None
    tool = tool_name.rsplit("__", 1)[-1]
    tokens = _TOKEN_SPLIT_RE.split(tool.lower())
    for token in tokens:
        if token in TIER_A_VERBS:
            return token
    return None


def check(tool_name):
    """Dispatcher-facing predicate: tool_name -> full block message, or None."""
    try:
        verb = offending_verb(tool_name)
    except Exception:
        return None
    if not verb:
        return None
    return (
        f"MCP Tier-A guard (PreToolUse): `{tool_name}` looks like a '{verb}' action over MCP — no "
        "repo state can prove an MCP merge/delete/push/force/publish/deploy call safe, and there is "
        "no human to confirm in an autonomous session (work skill's Tier-A rail: 'never force-push, "
        "merge/publish without confirmation, hard-delete, or do anything irreversible/destructive "
        "without an explicit yes.'). Ask the user to run this action manually outside the agent loop."
    )


def main():
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)

    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp__"):
        sys.exit(0)

    try:
        message = check(tool_name)
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not message:
        sys.exit(0)

    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
