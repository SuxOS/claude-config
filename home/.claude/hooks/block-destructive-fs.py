#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — a speed bump on destructive NON-GIT filesystem operations
run without confirmation (#345).

home/.claude/skills/work/SKILL.md's "Rails that don't bend" section states the Tier-A cardinal
rule in general terms: "Never force-push, merge/publish without confirmation, hard-delete, or do
anything irreversible/destructive (Tier A) without an explicit yes." Every enforcement mechanism
that exists so far is git- or network-scoped: `block-destructive-git.py` (#230) only inspects
`git ...` argv, `block-destructive-mcp.py` (#260) only inspects MCP tool calls, `block-egress.py`
only inspects network primitives. Nothing mechanically enforces the same rule against a plain
`rm -rf ~/some-important-dir`, or an `mv`/`cp -f` that silently clobbers a file outside of git —
under `defaultMode: bypassPermissions` those ran with zero confirmation until now.

Two independent, deliberately narrow predicates — a first version, not a seal (see #345's own
"genuinely open design question" framing of what "safe to delete" means):

  - `rm` with BOTH a recursive flag (`-r`/`-R`/`--recursive`) and a force flag (`-f`/`--force`,
    bundled or separate — `-rf`/`-fr`/`-Rf`/... all recognized via `has_flag_char()`), UNLESS EVERY
    named target is already provably safe to lose: it doesn't exist, it's an empty file/directory,
    it resolves under a known scratch root (`tempfile.gettempdir()`, `/tmp`, `/var/tmp`, a
    `.claude/worktrees/` scratch segment — CLAUDE.md's own scratch-worktree convention, ci.yml's
    "gitignored .claude/worktrees copies"), or `git check-ignore` confirms cwd's repo already
    ignores it (routine `node_modules`/`dist`/`.venv` build-artifact cleanup, #345's own explicit
    false-positive concern). A target this rail can't clear as junk blocks the WHOLE command — one
    real target among several throwaway ones is enough to ask first.
  - `mv <src> <dst>` / `cp -f <src> <dst>` (or `--force`; a bare `cp` with no `-f` is left alone —
    #345 scopes this to `cp -f` specifically) clobbering an EXISTING, non-empty regular file at
    `<dst>`, UNLESS `-n`/`--no-clobber` or `-b`/`--backup`/`--backup=CONTROL` is present (either
    means the prior content isn't actually lost). Deliberately narrow to the plain
    one-source/one-destination shape: a directory destination, `-t`/`--target-directory`, or more
    than one source is too ambiguous to reason about safely here and is left alone — conservative
    allow, same posture every predicate in block-destructive-git.py takes on an argv shape it can't
    confidently resolve.

A piece's command word is read through `_hookutil.strip_prefixes()` (#193) — the same wrapper/
prefix canonicalization every other rail here uses — so `command rm -rf x`, `sudo mv a b`, etc. all
reach the real command word. `_hookutil.strip_redirects()` is applied before any positional is
counted (#359) so a trailing `> log 2>&1` can't inflate `rm`'s target list or `mv`/`cp`'s positional
count. Every target token is then run through ONE shell-style expansion pass (`_expand_target()`:
command substitution `` `...` ``/`$(...)`, brace expansion `{a,b}`/`{1..5}`, tilde, `$env`/`${env}`,
then globs) BEFORE it is classified — expand first, classify the result, never the literal token —
so `rm -rf ~/dir`, `$HOME/dir`, `*`, `{realdir1,realdir2}`, or `rm -rf "$(cat manifest)"` can't be
misread as a literally-nonexistent "nothing to lose" path and silently allowed while the shell
expands/substitutes and deletes the real data. A target the pass can't confidently expand (a
`` `...` ``/`$(...)` substitution whose result is only known at shell-run time, a brace expansion
wider than `_BRACE_MAX_WORDS`, an unknown `~user`, an env var this process lacks, a glob
matching nothing) is treated AS unsafe — fail-SAFE toward blocking, never toward allow. For
`mv`/`cp -f`, EVERY operand (source as well as destination) goes through that same pass, so a
substituted source (`cp -f `id` dst`) blocks too — a source the shell runs is as unresolvable as a
substituted destination.

Fail-open on any error, a `cwd` that can't be resolved, or a path this rail can't confidently
classify (missing cwd means a relative target can't even be resolved to check) — a hook bug or an
unresolved case must never wedge the session or false-block routine cleanup, same contract as
block-destructive-git.py (#230).
"""
import glob
import os
import re
import sys
import tempfile

from _hookutil import (
    basename,
    git_returncode,
    has_flag_char,
    hook_tool_input,
    load_hook_input,
    pieces,
    strip_prefixes,
    strip_redirects,
)


def _positionals_after_dashdash(rest):
    """Every real positional argument: everything after a literal `--` (which ends flag parsing
    for every coreutils tool used here), or any earlier token that doesn't start with `-`."""
    seen_dashdash, positionals = False, []
    for tok in rest:
        if not seen_dashdash and tok == "--":
            seen_dashdash = True
            continue
        if not seen_dashdash and tok.startswith("-") and tok != "-":
            continue
        positionals.append(tok)
    return positionals


def _resolve(path, cwd):
    """Absolute-ize `path` against `cwd` (the hook-input cwd, never the hook process's own cwd,
    #123) so relative targets are checked against the right directory."""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(cwd, path))


_GLOB_META_RE = re.compile(r"[*?\[]")


def _has_command_substitution(token):
    """True if `token` carries an UNESCAPED command substitution — a backtick (`` `...` ``) or a
    `$(` — that the shell runs and substitutes into the argument before the fs op executes. A
    backslash escapes the next character, so a literal `a\\`b` / `\\$(...)` filename is NOT flagged
    (its backtick/`$` is escaped, exactly the escaped-literal case that must keep behaving as
    before). Scans the post-shlex token: quoting is already resolved, but shlex never runs
    substitutions, so a genuine `` `...` ``/`$(...)` still arrives with its metacharacters intact."""
    i, n = 0, len(token)
    while i < n:
        c = token[i]
        if c == "\\":
            i += 2  # escaped next char (incl. \` and \$) — never a substitution
            continue
        if c == "`":
            return True
        if c == "$" and i + 1 < n and token[i + 1] == "(":
            return True
        i += 1
    return False


# Breadth cap on one token's brace expansion. Brace expansion is statically decidable (pure text
# rewriting, unlike a `$(...)` whose result only exists at shell-run time), so up to this many
# words the pass EXPANDS and classifies each result like tilde/glob; past it (`{1..999999}`) the
# token is treated as unresolvable -> None -> block, the fail-SAFE direction — never "too big to
# check, assume fine," and never an unbounded enumeration inside a PreToolUse hook.
_BRACE_MAX_WORDS = 512

_SEQ_INT_RE = re.compile(r"^(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?$")
_SEQ_CHAR_RE = re.compile(r"^([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d+))?$")


class _BraceOverflow(Exception):
    """A brace expansion would exceed _BRACE_MAX_WORDS — caught at `_brace_expand()`'s boundary
    and surfaced as None (unresolvable -> block), never propagated further."""


def _brace_alternatives(token, start):
    """Parse the brace expression opening at `token[start] == '{'`: find its matching unescaped
    `}` (nested braces tracked by depth) and split the inside on TOP-LEVEL commas only (a comma
    inside a nested `{...}` belongs to the inner expression). Returns (index_of_closing_brace,
    [alternatives]), or (None, None) when no matching `}` exists — an unbalanced `{` is literal
    in bash, same as here."""
    depth, i, n = 0, start, len(token)
    alts, buf = [], []
    while i < n:
        c = token[i]
        if c == "\\":
            buf.append(token[i:i + 2])  # escaped char (incl. \{ \, \}) — never syntax
            i += 2
            continue
        if c == "{":
            depth += 1
            if depth > 1:
                buf.append(c)
            i += 1
            continue
        if c == "}":
            depth -= 1
            if depth == 0:
                alts.append("".join(buf))
                return i, alts
            buf.append(c)
            i += 1
            continue
        if c == "," and depth == 1:
            alts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    return None, None


def _brace_sequence(body):
    """Expand a bash sequence expression — `x..y` / `x..y..incr`, integer (`{1..5}`, `{01..10}`
    zero-padded, `{5..1}` descending) or single-letter (`{a..e}`) — into its word list. Returns
    None when `body` isn't a sequence form at all (bash leaves `{a}`/`{}`/`{..}` literal);
    raises _BraceOverflow when the range is real but wider than _BRACE_MAX_WORDS."""
    m = _SEQ_INT_RE.match(body)
    if m:
        lo_s, hi_s = m.group(1), m.group(2)
        lo, hi = int(lo_s), int(hi_s)
        step = abs(int(m.group(3))) if m.group(3) else 1
        step = step or 1  # bash treats a 0 increment as 1
        if abs(hi - lo) // step + 1 > _BRACE_MAX_WORDS:
            raise _BraceOverflow()
        width = 0
        if any(len(s.lstrip("-")) > 1 and s.lstrip("-").startswith("0") for s in (lo_s, hi_s)):
            width = max(len(lo_s), len(hi_s))  # {01..10} zero-pads every word to the wider endpoint
        direction = 1 if hi >= lo else -1
        return [str(v).zfill(width) for v in range(lo, hi + direction, direction * step)]
    m = _SEQ_CHAR_RE.match(body)
    if m:
        lo, hi = ord(m.group(1)), ord(m.group(2))
        step = abs(int(m.group(3))) if m.group(3) else 1
        step = step or 1
        if abs(hi - lo) // step + 1 > _BRACE_MAX_WORDS:
            raise _BraceOverflow()
        direction = 1 if hi >= lo else -1
        return [chr(v) for v in range(lo, hi + direction, direction * step)]
    return None


def _brace_expand(token):
    """Expand bash brace expressions in `token` — `{a,b}` alternation and `{x..y[..incr]}`
    sequences, with preamble/postscript (`dir{1,2}`, `{track,untrack}ed`) and nesting
    (`{a,b{c,d}}`) — into the word list the shell will actually hand the command. Brace expansion
    is bash's FIRST expansion (before tilde/$var/glob), so each resulting word re-enters the rest
    of `_expand_target()`'s pass — `~/{a,b}` becomes `~/a` `~/b` and only THEN tilde-expands,
    matching the shell's own order. Returns [token] unchanged when no valid expression is present
    (`{a}`, `{}`, and `${VAR}` are literal, exactly bash's rule — a `{` preceded by `$` is
    parameter expansion, not brace expansion), or None when a real expansion is wider than
    _BRACE_MAX_WORDS — callers treat None as unresolvable -> block, fail-SAFE."""
    try:
        return _brace_expand_words(token)
    except _BraceOverflow:
        return None


def _brace_expand_words(token):
    i, n = 0, len(token)
    while i < n:
        c = token[i]
        if c == "\\":
            i += 2  # escaped next char (incl. \{) — literal, never an expression opener
            continue
        if c == "$" and i + 1 < n and token[i + 1] == "{":
            i += 2  # ${...} parameter expansion — not brace expansion, bash's own rule
            continue
        if c == "{":
            end, alts = _brace_alternatives(token, i)
            if end is None:
                i += 1  # unbalanced `{` — literal from here on, keep scanning
                continue
            if len(alts) == 1:
                seq = _brace_sequence(alts[0])
                if seq is None:
                    i += 1  # `{a}`/`{}` — no top-level comma, no sequence: literal in bash too
                    continue
                alts = seq
            pre, post = token[:i], token[end + 1:]
            out = []
            for alt in alts:
                out.extend(_brace_expand_words(pre + alt + post))  # left-to-right, like bash
                if len(out) > _BRACE_MAX_WORDS:
                    raise _BraceOverflow()
            return out
        i += 1
    return [token]


def _expand_target(token, cwd):
    """Expand ONE rm/mv/cp target token the way the shell will BEFORE the command runs — command
    substitution (`` `...` ``, `$(...)`), brace expansion (`{a,b}`, `{1..5}` — bash's FIRST
    expansion), tilde (`~`, `~user`), env vars (`$HOME`, `${VAR}`), then globs (`*`/`?`/`[...]`)
    — into the concrete filesystem path(s) to classify. Returns a LIST of resolved absolute
    paths, or None when the token can't be confidently expanded: a command substitution (its
    result is only known at shell-run time), a brace expansion wider than _BRACE_MAX_WORDS, an
    unknown `~user`, an env var this process doesn't have (a leftover `$` after expansion), or a
    glob that matches nothing here.

    This is the SINGLE canonicalization pass (block-egress.py's strip_prefixes/inline_payloads
    design, CLAUDE.md #129): expand once, up front, then classify the RESULT — never classify the
    literal, unexpanded token. It closes the literal-target bypass a security review confirmed —
    and re-confirmed per missing expansion form: `_resolve()`/`_path_provably_safe_to_delete()`
    on a raw `~/dir`, `$HOME/dir`, `*`, `{realdir1,realdir2}`, or a `` `...` ``/`$(...)` command
    substitution sees a path that doesn't literally exist and reads it as "nothing to lose" ->
    ALLOW, while the real shell expands/substitutes it and deletes the actual data
    (`rm -rf ~/some-important-dir`, `rm -rf {realdir1,realdir2}`, or `rm -rf \"$(cat manifest)\"`).
    An unresolvable token is therefore NEVER "nothing to lose": callers must treat None as "not
    provably safe" (block), the fail-SAFE direction — the same posture
    `_path_provably_safe_to_delete` already takes on any target it can't clear as junk."""
    if _has_command_substitution(token):
        return None  # a `...`/$(...) the shell will run — the real target is unknowable here, block
    words = _brace_expand(token)
    if words is None:
        return None  # a brace expansion too wide to enumerate — can't prove safe, block
    out = []
    for word in words:
        expanded = os.path.expanduser(word)
        if expanded.startswith("~"):
            return None  # unknown user / unresolved tilde — can't prove it's safe to lose
        expanded = os.path.expandvars(expanded)
        if "$" in expanded:
            return None  # an env var absent from this process stayed literal — unresolved, block
        if _GLOB_META_RE.search(expanded):
            pattern = expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded)
            matches = glob.glob(pattern)
            if not matches:
                return None  # a glob resolving to nothing here — can't prove safe, block
            out.extend(os.path.normpath(m) for m in matches)
        else:
            out.append(_resolve(expanded, cwd))
    return out


def _under_scratch_root(path):
    """True for a path under a known throwaway location — deleting it is routine cleanup, not
    data loss, regardless of what's inside."""
    roots = (tempfile.gettempdir(), "/tmp", "/var/tmp", "/private/tmp", "/private/var/tmp")
    for root in roots:
        root = os.path.normpath(root)
        if path == root or path.startswith(root + os.sep):
            return True
    return "/.claude/worktrees/" in path or path.endswith("/.claude/worktrees")


def _path_provably_safe_to_delete(path, cwd):
    """True only if losing `path` is provably NOT real data loss. Any case this can't resolve
    (can't stat it, no cwd, git can't tell) is NOT treated as safe — false positives (blocking
    routine `rm -rf node_modules`-style cleanup) are the failure mode #345 explicitly warns
    against, so every check here is generous about recognizing "already disposable," not about
    guessing something is fine when it can't tell."""
    if _under_scratch_root(path):
        return True
    if not os.path.lexists(path):
        return True  # nothing there to lose
    if os.path.isdir(path) and not os.path.islink(path):
        try:
            if not os.listdir(path):
                return True  # empty directory
        except OSError:
            pass
    elif os.path.isfile(path) and not os.path.islink(path):
        try:
            if os.path.getsize(path) == 0:
                return True  # empty file
        except OSError:
            pass
    if git_returncode(["check-ignore", "-q", path], cwd) == 0:
        return True  # gitignored — routine build-artifact cleanup (node_modules, dist, .venv, ...)
    return False


def _rm_targets(rest):
    """Return this `rm` argv's target paths if it's BOTH recursive and forced (any bundled/glued
    combination), else None."""
    if not (has_flag_char(rest, "rR", ("--recursive",)) and has_flag_char(rest, "f", ("--force",))):
        return None
    return _positionals_after_dashdash(rest) or None


def _rm_hit(rest, cwd):
    targets = _rm_targets(rest)
    if not targets or cwd is None:
        return None  # no -rf shape, or no cwd to resolve relative targets against (#123)
    unsafe = []
    for t in targets:
        resolved = _expand_target(t, cwd)  # tilde/$var/glob expansion BEFORE classification
        if resolved is None or any(
            not _path_provably_safe_to_delete(p, cwd) for p in resolved
        ):
            # unresolvable (fail-safe -> block), or an expanded path that isn't provably junk
            unsafe.append(t)
    return unsafe or None


def _clobber_target(cmd, rest, cwd):
    """Return the resolved destination path if `mv`/`cp -f` would clobber an existing non-empty
    regular file there, else None."""
    if any(
        tok in ("-t", "--target-directory") or tok.startswith("--target-directory=")
        for tok in rest
    ):
        return None  # explicit target-directory form — a different shape, out of scope
    if has_flag_char(rest, "n", ("--no-clobber",)):
        return None
    if has_flag_char(rest, "b", ("--backup",)) or any(tok.startswith("--backup=") for tok in rest):
        return None  # a backup of the prior destination is made — nothing is actually lost
    if cmd == "cp" and not has_flag_char(rest, "f", ("--force",)):
        return None  # #345 scopes this to cp -f, not cp's ordinary default overwrite
    if cwd is None:
        return None
    positionals = _positionals_after_dashdash(rest)
    resolved_positionals = [_expand_target(p, cwd) for p in positionals]
    for pos, resolved in zip(positionals, resolved_positionals):
        if resolved is None:
            # ANY operand (source OR destination) whose expansion can't be resolved — an unset
            # $var, unknown ~user, empty glob, or a `...`/$(...) command substitution the shell will
            # run — means this rail can't reason about what gets moved/overwritten (a substituted
            # source can even fragment the positional count, e.g. `mv $(echo x) dst`). Fail-safe
            # toward block, the same posture the destination check took and #365's target handling.
            return pos
    if len(positionals) != 2:
        return None  # multi-source / directory-destination form — too ambiguous here
    for dst_path in resolved_positionals[1]:  # destination's resolved path(s), known non-None
        if os.path.islink(dst_path) or not os.path.isfile(dst_path):
            continue  # missing, a directory, or a symlink — not a plain-file clobber
        try:
            if os.path.getsize(dst_path) == 0:
                continue  # empty file — nothing to lose
        except OSError:
            continue
        return dst_path  # an existing, non-empty regular file would be overwritten
    return None


_MESSAGES = {
    "rm": (
        "would `rm -rf` {targets} — this rail can't confirm {plural} already safe to lose (does "
        "it exist, is it empty, is it under a scratch root, or is it gitignored). Confirm with the "
        "user first, or narrow the target if it really is disposable."
    ),
    "clobber": (
        "would overwrite the existing, non-empty file `{dst}`, discarding its current contents "
        "irrecoverably. Confirm with the user first, or add `-n`/`--no-clobber` (skip) or "
        "`-b`/`--backup` (keep a copy) if that's not the intent."
    ),
}


def offending(command, cwd):
    """Return (reason, argv, detail) for the first piece that hits one of the two predicates,
    else None."""
    for argv in pieces(command):
        stripped = strip_prefixes(argv)
        if not stripped:
            continue
        cmd = basename(stripped[0])
        rest = strip_redirects(stripped[1:])  # a trailing redirect must not inflate positionals (#359)
        if cmd == "rm":
            unsafe = _rm_hit(rest, cwd)
            if unsafe:
                return "rm", argv, unsafe
        elif cmd in ("mv", "cp"):
            dst = _clobber_target(cmd, rest, cwd)
            if dst:
                return "clobber", argv, dst
    return None


def check(command, cwd):
    """Dispatcher-facing predicate (#163): (command, cwd) -> full block message, or None."""
    try:
        hit = offending(command, cwd)
    except Exception:
        return None
    if not hit:
        return None
    reason, argv, detail = hit
    shown = " ".join(argv)
    if reason == "rm":
        body = _MESSAGES["rm"].format(
            targets=", ".join(f"`{t}`" for t in detail),
            plural="it's" if len(detail) == 1 else "they're",
        )
    else:
        body = _MESSAGES["clobber"].format(dst=detail)
    return (
        f"Destructive-filesystem guard (PreToolUse): `{shown}` {body} (work skill's Tier-A rail: "
        "'never force-push, merge/publish without confirmation, hard-delete, or do anything "
        "irreversible/destructive without an explicit yes.')"
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
