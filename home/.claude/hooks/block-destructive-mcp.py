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
verb-shaped server name can't false-positive every tool from it. Camel-case boundaries in that
segment (`mergePullRequest`) are split into `_`-separated words first, same as the existing
`_`/`-` handling, so a JS/TS-style MCP server's camelCase tool names tokenize the same way as
snake_case/kebab-case ones (#355) — otherwise the whole segment lowercases to one fused token
that never equals a bare verb. Split into tokens and block if any token is an exact match for a
Tier-A verb: merge, delete, push, force, publish, deploy — the same verb set work/SKILL.md's
cardinal rule names ("force-push, merge/publish, hard-delete... irreversible/destructive").
`create`/`update`/`edit`/`list`/`get` tools are deliberately NOT in scope here (not Tier-A on their
own); the Cloudflare plugin's explicit per-tool denies remain the belt for creates until a broader
audit widens this rail's verb set.

Unlike the Bash rails, there is no repo state to consult that would prove a merge/delete/push/force/
publish/deploy MCP call safe (mirrors `block-destructive-git.py`'s `_merge_publish_hit`, #242) and no
human to answer an `ask` prompt in an autonomous/`bypassPermissions` session — so a match blocks
unconditionally. A human running this interactively hits the same block and can approve manually
outside the agent loop; that's the intended outcome for a Tier-A action, not a bug.

Some newer MCP tools consolidate several actions behind one generic tool name, with the actual verb
living in `tool_input` instead of `tool_name` — e.g. GitHub's `pull_request_review_write` bundles
create/submit/delete(/resolve_thread/unresolve_thread), `label_write` bundles create/update/delete,
and `discussion_comment_write` bundles add/reply/update/delete(/mark_answer/unmark_answer), all
behind a `method` parameter (#358; confirmed against github/github-mcp-server's own README). A call
like `{"tool_name": "...__label_write", "tool_input": {"method": "delete", ...}}` has no destructive
token anywhere in `tool_name`, so the name-only scan above sails right past it. `offending_verb()`
covers the name; `offending_verb_from_input()` mirrors it against `tool_input["method"]`/
`["action"]` (both seen used for this purpose across MCP servers) — same tokenizing (camelCase +
`_`/`-` splitting) and the same Tier-A verb set, so a bundled `"method": "forceDelete"` is caught the
same way a name-shaped `force_delete` tool would be.

Fail-open on any error, and on anything this can't confidently parse — a hook bug, or a tool-name/
tool-input shape this doesn't recognize, must never wedge the session (repo convention). Exit 2 =
block; exit 0 = allow.
"""
import re
import sys

from _hookutil import load_hook_input

TIER_A_VERBS = {"merge", "delete", "push", "force", "publish", "deploy"}
ACTION_FIELDS = ("method", "action")

_TOKEN_SPLIT_RE = re.compile(r"[_\-]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _tier_a_token(text):
    """Return the first Tier-A verb token in `text` after camelCase/`_`/`-` splitting, else None."""
    text = _CAMEL_BOUNDARY_RE.sub("_", text)
    for token in _TOKEN_SPLIT_RE.split(text.lower()):
        if token in TIER_A_VERBS:
            return token
    return None


def offending_verb(tool_name):
    """Return the Tier-A verb token an `mcp__...__<tool>` tool_name hits, else None.

    Only the segment AFTER THE LAST `__` (the real tool name, not the server/plugin namespace) is
    scanned — see module docstring for why. Anything that doesn't look like a namespaced MCP tool
    name (no `__` at all) returns None rather than guessing."""
    if not isinstance(tool_name, str) or "__" not in tool_name:
        return None
    return _tier_a_token(tool_name.rsplit("__", 1)[-1])


def offending_verb_from_input(tool_input):
    """Return the Tier-A verb token found in a consolidated tool's `method`/`action` field, else None.

    Covers tools like `label_write`/`pull_request_review_write` that bundle several actions behind
    one generic tool name — see module docstring for why `tool_name` alone can't catch these."""
    if not isinstance(tool_input, dict):
        return None
    for field in ACTION_FIELDS:
        value = tool_input.get(field)
        if not isinstance(value, str):
            continue
        verb = _tier_a_token(value)
        if verb:
            return verb
    return None


def check(tool_name, tool_input=None):
    """Dispatcher-facing predicate: tool_name (+ tool_input) -> full block message, or None."""
    try:
        verb = offending_verb(tool_name)
        hit_in_name = verb is not None
        if not verb:
            verb = offending_verb_from_input(tool_input)
    except Exception:
        return None
    if not verb:
        return None
    where = f"`{tool_name}`" if hit_in_name else f"`{tool_name}`'s bundled action arguments"
    return (
        f"MCP Tier-A guard (PreToolUse): {where} looks like a '{verb}' action over MCP — no "
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

    tool_input = data.get("tool_input")

    try:
        message = check(tool_name, tool_input)
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not message:
        sys.exit(0)

    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
