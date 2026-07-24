#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — single envelope dispatcher for the Bash-command rails (#163).

`block-egress.py` and `block-checkout-held-branch.py` are both PreToolUse hooks matched on
`Bash`, and each independently re-implemented the same envelope boilerplate: `json.load(sys.stdin)`
(fail-open on error), the `tool_name != "Bash"` guard, extracting/validating `tool_input.command`,
running the check inside a try/except that exits 0 on any exception, and print+exit-2 on a hit.
Wiring both as separate `hooks.PreToolUse` entries also meant every Bash tool call spawned two
Python processes that each parsed the identical stdin envelope.

This dispatcher reads the envelope ONCE and runs a registered list of pure
`check(command, cwd) -> message | None` predicates — one per rail, defined in each rail's own
module so `block-egress.py`/`block-checkout-held-branch.py` stay independently readable and
independently testable via stdin (see hooks/README.md's "Testing a hook before you trust it").
The first predicate to return a message wins; settings.json wires only this one script under
`hooks.PreToolUse` for the `Bash` matcher instead of N.

Adding a rail: give its module a `check(command, cwd) -> message | None` function (see the
existing ones for the shape) and append its module name to _RAIL_MODULES below.

Fail-open on any error — a hook bug (this dispatcher's or any one rail's) must never wedge the
session (repo convention). Exit 2 = block; exit 0 = allow. That includes a rail module that
fails to even IMPORT (a syntax error, a broken sibling import): `_load_checks()` loads each rail
module independently and drops any that raise, rather than letting one broken module crash the
whole dispatcher before `main()` is ever reached (#180) — a broken rail degrades to "not
enforced", never to "no Bash command runs".
"""
import importlib.util
import os
import sys

from _hookutil import hook_tool_input, load_hook_input

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

# Registered rail modules, in the order they're checked. Each must define
# `check(command, cwd) -> message | None`; the first to return a message wins.
#
# `block-egress` and `block-suppressed-stderr` are UNREGISTERED by Colin's direct order
# (2026-07-22): their false-positive rate on routine interactive work (LAN ssh, inline
# python reading local JSON, commit messages that merely MENTION ssh, stderr redirects)
# outweighed the speed-bump value on this account. The modules and their standalone tests
# remain in the tree — re-arm either by adding its name back to this tuple.
#
# `block-destructive-git` is UNREGISTERED by Colin's direct order (2026-07-23), same
# order-family. Its `gh pr merge` / `gh release create` / `npm publish` predicate is
# unconditional by construction: a PreToolUse hook sees only the current command's
# envelope, never the conversation, so it cannot distinguish "merge this, I just said so"
# from an unprompted merge. On an account where the user IS the reviewer and merges are
# routine, that makes every merge a hand-off to a human who already said yes — friction
# with no decision behind it. What it also guarded (force-push, reset --hard, branch -D)
# goes with it; those are recoverable from reflog, unlike the deletes `block-destructive-fs`
# covers. Re-arm by adding the name back to this tuple.
#
# `block-sleep-loop` is UNREGISTERED by Colin's direct order (2026-07-23), same
# order-family. Unlike the others it never guarded state at all — it enforced a
# dev-speed preference ("never poll in a loop, block on one --watch/wait call"), so
# its worst case is a slower command, not a lost byte. It also cannot tell a status
# poll from a legitimately rate-limited retry loop, which its own block message
# concedes. A rail whose entire downside is inefficiency does not earn the right to
# hard-fail a command. Re-arm by adding the name back to this tuple.
#
# Still armed: `block-destructive-fs` (unrecoverable local deletes — no reflog for a
# deleted file) and `block-checkout-held-branch` (worktree corruption). With
# `permissions.deny` now empty and the org security-review ruleset disabled, these two
# are the ONLY automated Bash guard left anywhere in the stack.
_RAIL_MODULES = (
    "block-checkout-held-branch",
    "block-destructive-fs",
    "prefer-structured-tools",
)

# Identity-aware arming (#440). block-egress was unregistered above for the INTERACTIVE human
# (~/.claude) because its false-positive rate on routine interactive work outweighed the
# speed-bump value — a deliberate 2026-07-22 order. But the AUTONOMOUS bot (~/.claude-bot,
# claude@) shares this exact file via the symlinked hooks tree, so that same order silently
# left the bot with no egress enforcement — and the bot runs unattended under bypassPermissions
# with reach into PHI-adjacent data, with no human to catch a false positive OR a prompt-injected
# exfiltration. Per the trust doctrine, egress is *agent-protection* for the bot (keep), not
# *user-babysitting friction* for the human (drop). So the bot ARMS block-egress on top of the
# shared set; the human's relaxed set is unchanged. Detected via CLAUDE_CONFIG_DIR ending in
# `-bot` — the same selector install.sh --bot / the launch env uses (see settings.bot.json).
# Fail-safe: if the env var is absent the bot degrades to the human set (today's state — no
# regression), never the other way.
_BOT_ONLY_RAIL_MODULES = ("block-egress",)


def _is_bot_identity():
    """True when running under the autonomous bot config dir (~/.claude-bot)."""
    return os.environ.get("CLAUDE_CONFIG_DIR", "").rstrip("/").endswith("-bot")


def _active_rail_modules():
    """The rail set for this identity: the shared set, plus bot-only rails when running as the bot."""
    if _is_bot_identity():
        return _RAIL_MODULES + _BOT_ONLY_RAIL_MODULES
    return _RAIL_MODULES


def _load(module_name):
    """Load a sibling hook module by filename (hyphenated, so not a normal `import`)."""
    path = os.path.join(_HOOKS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_checks():
    """Load every rail module's `check`, skipping (not crashing on) one that fails to load."""
    checks = []
    for module_name in _active_rail_modules():
        try:
            checks.append(_load(module_name).check)
        except Exception as e:
            # Still fail-open (#180) — just make the silent degradation visible (#314).
            print(f"pretooluse-bash: rail {module_name!r} failed to load: {e}", file=sys.stderr)
            continue
    return tuple(checks)


CHECKS = _load_checks()


def main():
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = hook_tool_input(data).get("command")
    if not isinstance(command, str):
        sys.exit(0)

    cwd = data.get("cwd") or None

    for check in CHECKS:
        try:
            message = check(command, cwd)
        except Exception:
            continue  # never let one rail's bug block a call or wedge the session
        if message:
            print(message, file=sys.stderr)
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
