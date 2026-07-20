#!/usr/bin/env python3
"""PreToolUse hook (matcher: Edit|Write) — guards the LIVE installed hook/config surface from
being silently weakened by a direct Edit/Write tool call, in the same session those files are
meant to constrain (#243).

Every enforcement mechanism this repo has built (block-egress.py, block-destructive-git.py,
block-checkout-held-branch.py, block-sleep-loop.py, block-suppressed-stderr.py,
require-delegation-model.py) is wired through `~/.claude/settings.json`'s `hooks.PreToolUse`
block and lives in `~/.claude/hooks/*.py` (install.sh symlinks this repo's `hooks/` dir there,
and copies `settings.json` since Claude Code rewrites it in place). Until now nothing stopped an
`Edit`/`Write` tool call from directly rewriting that live settings.json to drop a hook entry, or
overwriting a live `hooks/*.py` file with a no-op stub, bypassing every other rail in this file
in one step, before anything is ever committed or reviewed — CI's config-integrity linters only
catch that at merge time for a PR that goes through review, not a live in-session rewrite.

Scope, and why: this rail matches ONLY the live installed path — `~/.claude/settings.json` and
`~/.claude/hooks/*.py`, resolved from this hook process's own `$HOME` (the same `$HOME`
install.sh installs into) — never a repo's tracked source under some `.../home/.claude/...`
subtree. That is deliberate, not an oversight. This repo's own normal workflow (every other
issue this build touches is exactly this) is to edit the TRACKED source in a git checkout and
land it via a reviewed PR; install.sh is what re-syncs that source to the live path afterward.
A direct live edit through the `~/.claude/...` path is the one case with no review step at all —
the exact gap #243 named — so scoping on that path draws the line at the one place the two
workflows are actually distinguishable, without trying to heuristically guess "is this session
the trusted build pipeline" (a build pipeline operates on a git checkout, never on `~/.claude`
directly, so it never touches the live path either — this rail is inert for that normal case by
construction, not by carve-out).

Unconditional once matched — like `_merge_publish_hit()` in block-destructive-git.py (#242),
there is no repo state that makes a live rewrite of the enforcement surface itself safe, so this
fires every time, with no allow-if-safe path; the fix is to make the change in a PR instead, not
to retry the same Edit/Write call. Fail-open on any other error — a hook bug must never wedge
the session (repo convention). Exit 2 = block; exit 0 = allow.
"""
import fnmatch
import os
import sys

from _hookutil import hook_tool_input, load_hook_input

TOOL_NAMES = {"Edit", "Write"}


def _live_targets():
    """(settings.json path, hooks/*.py glob) under this process's own $HOME/.claude — the same
    live path install.sh installs into and settings.json's own hook commands reference via
    `$HOME/.claude/hooks/...`."""
    claude_dir = os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(claude_dir, "settings.json"), os.path.join(claude_dir, "hooks", "*.py")


def check(tool_name, file_path):
    """(tool_name, file_path) -> block message, or None. Pure/testable, mirrors the Bash rails'
    `check(command, cwd)` shape (#163)."""
    if tool_name not in TOOL_NAMES:
        return None
    if not isinstance(file_path, str) or not file_path:
        return None
    try:
        resolved = os.path.abspath(os.path.expanduser(file_path))
        settings_path, hooks_glob = _live_targets()
        if resolved != settings_path and not fnmatch.fnmatch(resolved, hooks_glob):
            return None
    except Exception:
        return None
    return (
        f"Config-tamper guard (PreToolUse): editing `{resolved}` directly rewrites the LIVE "
        "installed hook/config surface every other rail in this session depends on — doing so "
        "in-session could silently disable enforcement before anything is ever committed or "
        "reviewed. Edit the tracked source in a git checkout instead (this repo's own "
        "home/.claude/settings.json / home/.claude/hooks/*.py) and land the change via a "
        "reviewed PR; install.sh re-syncs the live path from there."
    )


def main():
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)

    tool_name = data.get("tool_name")
    file_path = hook_tool_input(data).get("file_path")

    try:
        message = check(tool_name, file_path)
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not message:
        sys.exit(0)

    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
