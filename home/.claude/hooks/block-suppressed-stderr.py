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

Also catches the common `>/dev/null 2>&1` idiom (redirect stdout to null, then duplicate stderr
onto wherever stdout now points — fully silencing both streams) via a second, order-sensitive
regex anchored on that exact literal sequence (#201): stdout-to-null (`>`/`1>`, optionally
appending) immediately followed by `2>&1`. This is NOT general fd tracking — a reordered form
like `2>&1 >/dev/null` (dup stderr onto the ORIGINAL stdout, then redirect stdout to null — stderr
stays visible) is a different, larger predicate that's still out of scope; only the specific,
overwhelmingly common literal ordering is matched. A command that only does `2>&1` (stderr
duplicated onto stdout, not discarded) is not suppression and is left alone.

Also catches `2>&-` (#205), the POSIX idiom that closes fd 2 outright rather than redirecting it
to `/dev/null` — same practical effect (a later stderr write errors out or is silently dropped),
just the other spelling for "make stderr go away." Same digit-adjacency guard as the `/dev/null`
form: the `2` must be its own word, glued to the `>`.

Scanning the raw string has a corollary the regexes alone can't fix: they have zero awareness of
shell quoting, so they also match `2>/dev/null` sitting inside a QUOTED argument — plain text
there, not a redirect (`grep -rn "2>/dev/null" hooks/`, a benign search for that exact literal, or
`git commit -m "docs: explain the 2>/dev/null idiom"`) (#330). Before running the three regexes,
`_mask_quoted()` blanks out the interior of every single-/double-quoted span (same quote-tracking
shape as `_hookutil.substitution_inners()`, applied here to suppress rather than surface quoted
text) so a redirect-shaped substring that's actually quoted text can't match. A real redirect
whose TARGET happens to be quoted (`2>"/dev/null"`, valid but rare) is masked away too and so goes
undetected — an accepted false-negative tradeoff for closing the far more common false-positive.

Fail-open on any error — a hook bug must never wedge the session (repo convention). Exit 2 =
block; exit 0 = allow.
"""
import re
import sys

from _hookutil import hook_tool_input, load_hook_input

# `2` or `&` immediately (no whitespace) before `>`/`>>`, then optional whitespace, then the
# literal redirect target. `(?<![\w])` before the `2` requires it to be its own word — not the
# tail of a longer word/number (`foo2>x` redirects fd 1 via the unnumbered `>`, not fd 2; `22>x`
# targets fd 22, not fd 2) — matching the shell's own "digits-only preceding word" IO_NUMBER rule.
NULL_REDIRECT_RE = re.compile(r"(?:(?<![\w])2|&)>>?[ \t]*/dev/null")
# The `>/dev/null 2>&1` idiom (#201): stdout redirected to null (bare `>` or explicit `1>`, with
# the same "own word" guard as above so `21>/dev/null` isn't misread as fd 1), then a literal
# `2>&1` afterward, in that order.
STDOUT_NULL_THEN_DUP_RE = re.compile(r"(?<![\w])(?:1)?>>?[ \t]*/dev/null[ \t]+2>&1")
# `2>&-` (#205): closes fd 2 outright instead of redirecting it — same "own word" digit-adjacency
# guard as NULL_REDIRECT_RE, with optional whitespace before the `-` target (same as `/dev/null`).
FD_CLOSE_RE = re.compile(r"(?<![\w])2>&[ \t]*-")


def _mask_quoted(command):
    """Return `command` with the interior of every single-/double-quoted span blanked out (spaces),
    quote characters and everything outside quotes left untouched — so the redirect regexes above
    can no longer match a `2>/dev/null`-shaped substring that's actually quoted text, not a real
    redirect (#330). Same quote-tracking shape as `_hookutil.substitution_inners()`; best-effort on
    an unbalanced quote (masks to the end of the string) since this must fail open like every
    other rail, never raise."""
    out = []
    quote = None  # None | "'" | '"'
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\" and quote != "'" and i + 1 < n:
            out.append(c if quote is None else " ")
            out.append(command[i + 1] if quote is None else " ")
            i += 2
            continue
        if quote is None and c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            continue
        if quote is not None and c == quote:
            quote = None
            out.append(c)
            i += 1
            continue
        out.append(" " if quote is not None else c)
        i += 1
    return "".join(out)


def offending(command):
    masked = _mask_quoted(command)
    return bool(
        NULL_REDIRECT_RE.search(masked)
        or STDOUT_NULL_THEN_DUP_RE.search(masked)
        or FD_CLOSE_RE.search(masked)
    )


def check(command, cwd):
    """Dispatcher-facing predicate (#163): (command, cwd) -> full block message, or None.

    `cwd` is unused here — this rail needs no repo state — but the parameter is part of the
    shared `check(command, cwd) -> reason | None` contract `pretooluse-bash.py` registers every
    rail against, so every predicate takes it even when it's ignored.
    """
    if not offending(command):
        return None
    return (
        "Suppressed-stderr guard (PreToolUse): this Bash command redirects or closes stderr "
        "(`2>/dev/null`, `&>/dev/null`, `>/dev/null 2>&1`, or `2>&-`). CLAUDE.md dev-speed tactics: \"don't suppress a "
        "command's stderr if you might need it to diagnose — `2>/dev/null` on a step you'll have "
        "to re-debug just moves the cost, it doesn't remove it.\" If this command is already "
        "known-good and just noisy, that's a legitimate case this speed bump can't tell apart — "
        "otherwise drop the redirect so a failure stays visible."
    )


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
