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
count.

Fail-open on any error, a `cwd` that can't be resolved, or a path this rail can't confidently
classify (missing cwd means a relative target can't even be resolved to check) — a hook bug or an
unresolved case must never wedge the session or false-block routine cleanup, same contract as
block-destructive-git.py (#230).
"""
import os
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
    unsafe = [t for t in targets if not _path_provably_safe_to_delete(_resolve(t, cwd), cwd)]
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
    if len(positionals) != 2:
        return None  # multi-source / directory-destination form — too ambiguous here
    _src, dst = positionals
    dst_path = _resolve(dst, cwd)
    if os.path.islink(dst_path) or not os.path.isfile(dst_path):
        return None  # missing, a directory, or a symlink — not a plain-file clobber
    try:
        if os.path.getsize(dst_path) == 0:
            return None  # empty file — nothing to lose
    except OSError:
        return None
    return dst_path


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
