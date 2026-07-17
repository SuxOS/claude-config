#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — flag a command that redirects stderr to /dev/null.

CLAUDE.md's dev-speed tactics: "Don't suppress a command's stderr if you might need it to
diagnose — `2>/dev/null` on a step you'll have to re-debug just moves the cost, it doesn't remove
it." hooks/README.md named a suppressed-stderr rail as one of the cardinal-rails candidates the
#163 architecture invited that nobody had built yet (#181).

The check: does the command redirect file descriptor 2 (`2>`/`2>>`), or both 1 and 2 together
(`&>`/`&>>`), to `/dev/null`? This is done with a regex over the raw command text rather than
`_hookutil.pieces()`'s tokenizer, deliberately: POSIX shell only treats a leading digit as an
fd-redirect target (an "IO_NUMBER") when it is immediately adjacent to the `>` — no whitespace —
so `2>/dev/null` and `2> /dev/null` both redirect fd 2, but `2 > /dev/null` (space before the
`>`) does NOT: there `2` is just an ordinary word/argument and the unnumbered `>` redirects fd 1
(e.g. `ffmpeg -loglevel 2 > /dev/null`, a numeric option value that happens to precede an
unrelated stdout redirect). Tokenizing first loses that adjacency, so the regex runs directly on
the command string: `2`/`&` must be glued to the following `>`/`>>` with no space, while
whitespace between the operator and `/dev/null` is fine (it's optional either way in the shell).

Deliberately narrow to the two forms CLAUDE.md and hooks/README.md name (`2>/dev/null`,
`&>/dev/null`, plus their `>>`-appending variants) — NOT the equivalent-but-differently-shaped
`>/dev/null 2>&1` idiom (redirect stdout to null, then duplicate stderr onto wherever stdout now
points), which needs order-sensitive fd tracking to detect correctly and is a separate, larger
predicate. A command that only does `2>&1` (stderr duplicated onto stdout, not discarded) is not
suppression and is left alone.

Fail-open on any error — a hook bug must never wedge the session (repo convention). Exit 2 =
block; exit 0 = allow.
"""
import json
import re
import sys

# `2` or `&` immediately (no whitespace) before `>`/`>>`, then optional whitespace, then the
# literal redirect target. `(?<![\w])` before the `2` requires it to be its own word — not the
# tail of a longer word/number (`foo2>x` redirects fd 1 via the unnumbered `>`, not fd 2; `22>x`
# targets fd 22, not fd 2) — matching the shell's own "digits-only preceding word" IO_NUMBER rule.
NULL_REDIRECT_RE = re.compile(r"(?:(?<![\w])2|&)>>?[ \t]*/dev/null")


def offending(command):
    return bool(NULL_REDIRECT_RE.search(command))


def check(command, cwd):
    """Dispatcher-facing predicate (#163): (command, cwd) -> full block message, or None.

    `cwd` is unused here — this rail needs no repo state — but the parameter is part of the
    shared `check(command, cwd) -> reason | None` contract `pretooluse-bash.py` registers every
    rail against, so every predicate takes it even when it's ignored.
    """
    if not offending(command):
        return None
    return (
        "Suppressed-stderr guard (PreToolUse): this Bash command redirects stderr to /dev/null "
        "(`2>/dev/null` or `&>/dev/null`). CLAUDE.md dev-speed tactics: \"don't suppress a "
        "command's stderr if you might need it to diagnose — `2>/dev/null` on a step you'll have "
        "to re-debug just moves the cost, it doesn't remove it.\" If this command is already "
        "known-good and just noisy, that's a legitimate case this speed bump can't tell apart — "
        "otherwise drop the redirect so a failure stays visible."
    )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = (data.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        sys.exit(0)

    try:
        message = check(command, data.get("cwd") or None)
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not message:
        sys.exit(0)

    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
