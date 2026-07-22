#!/usr/bin/env python3
"""PreToolUse hook (matcher: `Write`) — block a full-file overwrite of a git-tracked file that
has uncommitted changes.

Every "discard uncommitted work without confirmation" guard in this repo is Bash-scoped:
block-destructive-git.py's `_reset_hard_hit`/`_discard_hit` and audit-git-consequences.py's
ref-diffing net both only fire on `tool_name == "Bash"` — `hooks.PreToolUse` had no `Write`/`Edit`
matcher at all. But `permissions.allow` grants `"Write"` unconditionally, and the Write tool fully
REPLACES a file's content with no diff-aware merge. If a target file has uncommitted tracked
changes (staged or unstaged — exactly what block-destructive-git.py's `_working_tree_dirty()`
already checks for `reset --hard`/`checkout -- .`), a Write call to that same path silently
discards those changes with zero confirmation — the same Tier-A "discard without an explicit yes"
rule the git rails enforce (work skill: "never ... do anything irreversible/destructive without an
explicit yes"), just reached through a completely different tool surface (#364).

This is distinct from the destructive-git Bash rails (a different tool, not a git subcommand) and
from a hypothetical settings/hooks tamper guard (this fires for ANY git-tracked file's uncommitted
edits, not one specific protected path). `Edit` is deliberately OUT of scope: it requires an exact
`old_string` match against the file's CURRENT content rather than a blind full-file replace, so it
can't silently clobber a change it never saw — Write's blind-overwrite shape is what makes this
rail's check meaningful.

The check: given `tool_input.file_path`, run a `git status --porcelain -- <path>` scoped to that
exact file in the file's own directory (not the hook's/session's cwd — the target path is the
authoritative repo context here, unlike a Bash rail that has no equivalent, #154's same "don't
guess the repo" lesson applied to a stronger signal). Empty output means clean-or-untracked-or-
no-repo (nothing at risk); an untracked ("??") line means Write can't discard git HISTORY for a
file git was never tracking (creating/replacing an untracked file is ordinary Write usage); any
other porcelain line means a real staged-or-unstaged tracked change that Write would blow away.

Unconditional on a hit, like block-destructive-mcp.py's Tier-A shape: there is no "would this
actually lose something worth keeping" heuristic beyond the dirty check itself, and no human to
confirm in an autonomous session. Fail-open on any error — a hook bug, an unreadable path, a
missing/relative `file_path`, or any git/subprocess quirk — must never wedge the session (repo
convention). Exit 2 = block; exit 0 = allow.
"""
import os
import sys

from _hookutil import git_out, hook_tool_input, load_hook_input


def _tracked_and_dirty(file_path):
    """True if `file_path` is a git-tracked file with uncommitted (staged or unstaged) changes.

    Scoped to the exact pathspec so an unrelated dirty file elsewhere in the repo never triggers a
    false block. `git_out()` returns None (fail-open) when `file_path`'s directory isn't inside a
    readable git repo at all — nothing to protect there."""
    directory = os.path.dirname(file_path) or "."
    out = git_out(["status", "--porcelain", "--", file_path], directory)
    if not out:
        return False  # no output: clean tracked file, or git_out couldn't tell — fail open
    line = out.splitlines()[0]
    if line.startswith("??"):
        return False  # untracked — no git history for Write to discard
    return True


def check(tool_input):
    """Dispatcher-facing predicate: tool_input -> full block message, or None."""
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    if not os.path.isabs(file_path):
        return None  # Write's own contract is an absolute path; nothing safe to resolve otherwise
    if not _tracked_and_dirty(file_path):
        return None
    return (
        f"Write-overwrite guard (PreToolUse): `{file_path}` has uncommitted tracked changes "
        "(staged or unstaged) and Write would replace its ENTIRE content with no diff-aware merge, "
        "discarding them irrecoverably. Confirm with the user first, or `git stash`/commit the "
        "existing changes before overwriting — the same Tier-A 'discard without an explicit yes' "
        "rule block-destructive-git.py enforces for `git reset --hard`/`checkout -- .` (work "
        "skill), just reached through Write instead of a Bash git command."
    )


def main():
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)

    if data.get("tool_name") != "Write":
        sys.exit(0)

    try:
        message = check(hook_tool_input(data))
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not message:
        sys.exit(0)

    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
