#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — flag a sleep-based polling loop.

CLAUDE.md's dev-speed tactics: "never poll in a loop — block on one `--watch`/`wait` call
instead." hooks/README.md named this as the first candidate the cardinal-rails architecture
(#163) invited that nobody had built yet (#181): the dispatcher/rail contract, the `check(command,
cwd) -> message | None` shape, and the fixture-corpus harness were already in place — this rail
is "write the predicate", not "build the pipeline".

The check: a shell loop keyword (`while`/`until`/`for`) opening some piece of the command, AND a
`sleep` invocation appearing in some piece of the same command. `_hookutil.pieces()` splits a
compound command like `while COND; do CHECK; sleep 5; done` into one argv per `;`-separated
segment (`["while","true"]`, `["do","check"]`, `["sleep","5"]`, `["done"]`) — so both signals are
just "does some piece open with a loop keyword" and "does some piece run sleep", not a full shell
grammar parse. That is a deliberate simplification (the same "speed bump, not a seal" tradeoff
block-egress.py takes): a `sleep` textually alongside an unrelated loop on the same command line
is a rare false positive, and a real shell-grammar parser is a lot more hook for a marginal gain.

Deliberately does NOT flag a bare `sleep N` with no loop keyword anywhere in the command — a
single delay (rate-limiting a retry the user explicitly asked for, `sleep 2 && npm run build`) is
common and legitimate; it's the poll-in-a-loop shape specifically that CLAUDE.md calls out.

Fail-open on any error — a hook bug must never wedge the session (repo convention). Exit 2 =
block; exit 0 = allow.
"""
import json
import sys

from _hookutil import basename, pieces

LOOP_KEYWORDS = {"while", "until", "for"}
# Compound-statement keywords that can glue onto the same piece as the command they introduce
# (`do sleep 5` splits to one piece since there's no `;` between `do` and `sleep`) — stripped
# before reading a piece's real command word.
LEADING_KEYWORDS = {"do", "then", "else"}


def _command_word(argv):
    """The real command word of a piece, after stripping a leading compound-statement keyword."""
    i = 0
    while i < len(argv) and argv[i] in LEADING_KEYWORDS:
        i += 1
    if i >= len(argv):
        return None
    return basename(argv[i])


def offending(command):
    """True if `command` contains both a loop-opening piece and a `sleep` piece."""
    has_loop = False
    has_sleep = False
    for argv in pieces(command):
        if not argv:
            continue
        if argv[0] in LOOP_KEYWORDS:
            has_loop = True
        if _command_word(argv) == "sleep":
            has_sleep = True
    return has_loop and has_sleep


def check(command, cwd):
    """Dispatcher-facing predicate (#163): (command, cwd) -> full block message, or None.

    `cwd` is unused here — this rail needs no repo state — but the parameter is part of the
    shared `check(command, cwd) -> reason | None` contract `pretooluse-bash.py` registers every
    rail against, so every predicate takes it even when it's ignored.
    """
    if not offending(command):
        return None
    return (
        "Polling-loop guard (PreToolUse): this Bash command looks like a `sleep`-based polling "
        "loop (a `while`/`until`/`for` loop with `sleep` in it). CLAUDE.md dev-speed tactics: "
        "'never poll in a loop — block on one `--watch`/`wait` call instead.' If there's a "
        "blocking wait/`--watch` form for whatever this loop is polling for, use that instead — "
        "it returns the instant the condition is met instead of burning turns on a timer. If "
        "this really is a rate-limited retry the user explicitly asked for (not a status poll), "
        "that's a legitimate case this speed bump can't tell apart — restructure the command so "
        "`sleep` isn't inside a `while`/`until`/`for` piece, or run it a different way."
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
