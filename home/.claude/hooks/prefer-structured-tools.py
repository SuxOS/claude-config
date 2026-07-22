#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — flag two recurring Bash-tool mistake shapes CLAUDE.md
already documents in prose but that kept recurring anyway (three times in one session on
2026-07-22, including inside the very Bash tool call this hook now guards): manual loop +
jq/awk aggregation where nu/python was sitting right there, and the classic zsh
unquoted-parameter-expansion word-split footgun.

Prose in CLAUDE.md is the weakest enforcement (see hooks/README.md's opening line) — this
rail exists because the prose alone had already been written, and read, and still didn't
stick under pressure.

## Check 1: loop + jq/awk aggregation

A shell loop keyword (`while`/`until`/`for`) opening some piece of the command, AND a `jq` or
`awk` invocation appearing in some piece of the same command — the exact shape of "hand-roll a
bash loop that aggregates JSON/text field-by-field" instead of `nu -c '... | reduce ...'` or a
short `python3` script. Same piece-level, not-a-full-parser approach as block-sleep-loop.py
(loop keyword + sleep) — a real shell-grammar parse is a lot more hook for a marginal gain, and
a `jq`/`awk` textually alongside an unrelated loop on the same command line is a rare false
positive.

Deliberately does NOT flag a bare single-shot `... | jq '.foo'` with no loop keyword anywhere —
one-shot filtering of already-fetched JSON is still fine in jq. It's the "loop that aggregates"
shape specifically that recurred (2026-07-22: a 12-repo `while IFS='|' read` loop computing
issue/PR drain-rate sums via jq+awk field-splitting, when `nu -c '$table | reduce ...'` or
`python3` would have done it in one shot with no shell-loop machinery at all).

## Check 2: zsh unquoted-parameter-expansion word-split

zsh does NOT word-split an unquoted parameter expansion the way bash does — `for x in $csv`
loops ONCE over the whole string in zsh where bash would split on IFS. This has broken loops
live at least twice (a `gh issue create` label loop that mangled 9/12 calls; this session's own
`set -- $x` that silently collapsed a two-field repo/PR-number pair into one token). Flags the
two shapes actually hit: `for VAR in $OTHER` and `set -- $OTHER` where `$OTHER`/`${OTHER}` is
NOT wrapped in double quotes. This is necessarily a textual/regex check, not a `pieces()`-based
one — `pieces()` tokenizes via `shlex`, which strips quotes entirely, so an already-tokenized
argv can no longer tell you whether the original text quoted the expansion or not. Checked
against the RAW command string before any tokenization for exactly this reason.

Both checks are best-effort text/piece-level heuristics, not a real shell parser — same
"speed bump, not a seal" tradeoff every rail in this dispatcher takes (see block-egress.py).

Fail-open on any error — a hook bug must never wedge the session (repo convention). Exit 2 =
block; exit 0 = allow.
"""
import re
import sys

from _hookutil import hook_tool_input, load_hook_input, pieces, strip_prefixes

LOOP_KEYWORDS = {"while", "until", "for"}
LEADING_KEYWORDS = {"do", "then", "else"}
AGGREGATOR_COMMANDS = {"jq", "awk"}

# `for x in $var` / `for x in ${var}` with no surrounding double quotes. Deliberately anchored
# to "in $" immediately (not "in .*\$" anywhere in the piece) so `for x in "$var" other "$thing"`
# — a real multi-item, already-safe loop — doesn't false-positive just because a later word also
# happens to be a bare expansion; the unsafe shape is specifically the loop's iterable being a
# single bare expansion.
_FOR_UNQUOTED = re.compile(r'\bfor\s+\w+\s+in\s+\$\{?\w+\}?(?!["\'])')
# `set -- $var` / `set -- ${var}` unquoted (the positional-params variant of the same footgun).
_SET_UNQUOTED = re.compile(r'\bset\s+--\s+\$\{?\w+\}?(?!["\'])')


def _has_loop_keyword(piece):
    stripped = strip_prefixes(piece)
    if not stripped:
        return False
    word = stripped[0]
    if word in LEADING_KEYWORDS and len(stripped) > 1:
        word = strip_prefixes(stripped[1:])[0] if strip_prefixes(stripped[1:]) else word
    return word in LOOP_KEYWORDS


def _has_aggregator(piece):
    stripped = strip_prefixes(piece)
    if not stripped:
        return False
    return stripped[0] in AGGREGATOR_COMMANDS


def check(command, cwd):
    if _FOR_UNQUOTED.search(command):
        return (
            "zsh does NOT word-split an unquoted parameter expansion (bash does) — "
            "`for x in $var` loops ONCE over the whole string in the Bash tool's zsh shell, "
            "not once per token. Quote it (`for x in \"$var\"` if $var is genuinely one token) "
            "or split explicitly (`for x in $(printf '%s' \"$var\" | tr ',' ' ')`), or better: "
            "use `nu -c '$list | each { |x| ... }'` over an actual list. "
            "(Blocked by prefer-structured-tools.py; see CLAUDE.md dev-speed tactics.)"
        )
    if _SET_UNQUOTED.search(command):
        return (
            "zsh does NOT word-split an unquoted parameter expansion — `set -- $var` sets "
            "$1 to the WHOLE string, not one positional param per word. Quote it if $var is "
            "one token, or use `nu`/`python3` to work with the actual fields instead of "
            "positional-param splitting. "
            "(Blocked by prefer-structured-tools.py; see CLAUDE.md dev-speed tactics.)"
        )

    piece_list = list(pieces(command))
    has_loop = any(_has_loop_keyword(p) for p in piece_list)
    has_aggregator = any(_has_aggregator(p) for p in piece_list)
    if has_loop and has_aggregator:
        return (
            "This looks like a hand-rolled bash loop aggregating data via jq/awk across "
            "multiple items. Prefer `nu -c '... | each {...} | reduce ...'` or a short "
            "python3 script instead — no shell-loop machinery, no zsh/bash word-splitting "
            "footguns, and the aggregation math happens in a real interpreter instead of "
            "string-glued shell arithmetic. A single one-shot `... | jq '.foo'` with no loop "
            "is still fine — this only fires on loop-plus-aggregator together. "
            "(Blocked by prefer-structured-tools.py; see CLAUDE.md dev-speed tactics.)"
        )
    return None


def main():
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = hook_tool_input(data).get("command")
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
