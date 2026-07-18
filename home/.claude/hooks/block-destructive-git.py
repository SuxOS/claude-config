#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — a speed bump on destructive git commands run without
confirmation.

home/.claude/skills/work/SKILL.md's "Rails that don't bend" section states a Tier-A cardinal rule
in prose: "Never force-push, merge/publish without confirmation, hard-delete, or do anything
irreversible/destructive (Tier A) without an explicit yes." hooks/README.md frames exactly this
shape of rule — a cardinal rule stated only in prose, that a model can drift from under pressure —
as what the block-checkout-held-branch.py / block-sleep-loop.py / block-suppressed-stderr.py rails
exist to turn "from aspiration to guarantee" (#163, #181). Until now nothing mechanically enforced
the destructive-git-command class specifically: block-egress.py only looks at network egress,
block-checkout-held-branch.py only looks at branch switches into a held worktree (#230).

Six independent, narrowly-scoped predicates, each run against every `git` piece of the command.
Like every other rail here, each is a deliberate "speed bump, not a seal": a missed detection is a
harmless allow, so every predicate is conservative — anything it can't confidently resolve (a repo
it can't read, a ref it can't verify, an argv shape it doesn't recognize) is allowed, never blocked.

  - `git push (-f|--force)` (or a `+refspec` shorthand), UNLESS `--force-with-lease` is present
    (git's own safe form already guards this) OR the push is provably a fast-forward of the
    remote-tracking ref we know about locally — i.e. nothing would actually be overwritten. This is
    what lets a routine force-push to a branch you just created (CLAUDE.md's own scratch-branch/
    explicit-refspec-push tactic) through untouched: a brand-new branch has no remote-tracking ref
    yet, so `git rev-parse --verify` on it fails and the predicate allows. Only a force-push that
    would discard commits on the remote NOT reachable from your local tip — the exact case
    `--force-with-lease` exists to prevent — is flagged. Best-effort: the remote-tracking ref
    reflects the last local fetch, not a live look at the remote, same staleness `--force-with-lease`
    itself accepts.
  - `git reset --hard [<ref>]`, UNLESS the working tree has no uncommitted TRACKED changes (nothing
    to lose — untracked files are never touched by `reset --hard`, so they don't count).
  - `git clean` with a force flag (`-f`/`--force`, alone or in a combined short cluster like `-fd`/
    `-fx`) and no `-n`/`--dry-run`, UNLESS a `-n` dry run with the same flags would remove nothing.
  - `git branch -D <name>...` (or `--delete --force`), UNLESS every named branch is already merged
    into HEAD — i.e. `-d` (which refuses on unmerged branches) would have succeeded too, so `-D`
    isn't discarding anything `-d` wouldn't have let through. `--remotes`/`-r` (deleting a local
    remote-tracking ref, trivially recoverable via a re-fetch) is out of scope.
  - `git checkout -- .` / `git checkout .` / `git restore .` (default or `--worktree` mode — a
    working-tree-only `--staged` restore doesn't touch files, so it's out of scope), UNLESS the
    working tree has no uncommitted tracked changes. Deliberately narrow to exactly "discard
    EVERYTHING" (`.`, the whole tree) — `git checkout -- some/file.txt` is an ordinary, common,
    deliberate discard of one file and is left alone.
  - `git stash drop [<stash>]` / `git stash clear`, UNLESS `git stash list` is already empty
    (nothing to lose). Stashed work has no `-d`-vs-`-D` safe alternative and no dry-run preview,
    so any non-empty stash list is treated as something that could be lost (#239).

A piece's command word is read through `_hookutil.strip_prefixes()`/`git_subcommand()` (#193, #230)
— the same wrapper/prefix canonicalization and git-global-option walk block-checkout-held-branch.py
uses — so `command git push -f`, `sudo git reset --hard`, `git -c foo=bar clean -f`, etc. all reach
the real subcommand. `git_subcommand()` also refuses to look past a `-C`/`--git-dir`/`--work-tree`
global option (redirects git at a different repo than the hook-input `cwd` — inspecting cwd's state
would consult the wrong repo, #154), same as the checkout rail.

Fail-open on any error — a hook bug must never wedge the session (repo convention). Exit 2 =
block; exit 0 = allow.
"""
import json
import sys

from _hookutil import git_out, git_returncode, git_subcommand, pieces, strip_prefixes

# checkout flags that mean this isn't a blind path-restore at all (branch creation, detach,
# interactive) — never the discard-everything case.
CHECKOUT_SKIP_OPTS = {"-b", "-B", "-c", "-C", "--orphan", "-d", "--detach", "-p", "--patch"}
# `git push` flags that consume a separate following token as their value (#237) — same
# separate-vs-glued gap GIT_GLOBAL_VALUE_OPTS/WRAPPER_VALUE_OPTS/SUDO_VALUE_OPTS guard against.
# `--opt=value` forms carry their own value and need no special handling here.
PUSH_VALUE_OPTS = {"-o", "--push-option", "--receive-pack", "--repo"}


def _has_flag_char(rest, chars, long_names=()):
    """True if any token in `rest` sets one of `chars` (single-letter short flags, matched even
    inside a combined cluster like `-fd`) or exactly matches a name in `long_names`."""
    for tok in rest:
        if tok in long_names:
            return True
        if tok.startswith("--"):
            continue
        if tok.startswith("-") and any(c in chars for c in tok[1:]):
            return True
    return False


def _working_tree_dirty(cwd):
    """True if `git status --porcelain` shows any TRACKED change (staged or unstaged) — i.e.
    something a hard reset/discard could actually lose. Untracked ("??") lines don't count:
    `reset --hard`/`checkout -- .`/`restore .` never touch untracked files. None means "couldn't
    tell" (fail open — callers treat that the same as "not dirty")."""
    out = git_out(["status", "--porcelain"], cwd)
    if out is None:
        return None
    for line in out.splitlines():
        if not line.startswith("??"):
            return True
    return False


def _push_force_hit(rest, cwd):
    """True if this `git push` argv force-pushes and, from locally known remote state, is
    provably NOT a fast-forward (would discard commits on the remote we haven't merged in)."""
    if any(tok == "--force-with-lease" or tok.startswith("--force-with-lease=") for tok in rest):
        return False  # git's own safe form — it refuses server-side if the remote moved

    filtered, i, n = [], 0, len(rest)
    while i < n:
        tok = rest[i]
        filtered.append(tok)
        if tok in PUSH_VALUE_OPTS and i + 1 < n:
            i += 1  # drop the value token entirely — it can't be a flag or a real positional
        i += 1
    rest = filtered

    forced = _has_flag_char(rest, "f", ("--force",))
    positionals, out_of_scope = [], False
    for tok in rest:
        if tok in ("--all", "--mirror", "--tags", "--delete", "-d"):
            out_of_scope = True  # multi-ref or a delete-push — a different risk, not scoped here
        elif not tok.startswith("-"):
            positionals.append(tok)
    if out_of_scope or len(positionals) > 2:
        return False  # too broad/ambiguous to reason about safely — conservative allow

    if len(positionals) == 2:
        remote, refspec = positionals
        if refspec.startswith("+"):
            forced = True
            refspec = refspec[1:]
        src, _, dst = refspec.partition(":")
        dst = dst if ":" in refspec else src
        if not src or not dst:
            return False  # a delete-refspec (":branch" / "branch:") — out of scope
        push_ref, src_ref = f"refs/remotes/{remote}/{dst}", src
    elif len(positionals) == 1:
        branch = git_out(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        if not branch or branch.strip() == "HEAD":
            return False  # no branch (detached) or can't tell — conservative allow
        push_ref, src_ref = f"refs/remotes/{positionals[0]}/{branch.strip()}", "HEAD"
    else:
        push_ref, src_ref = "@{push}", "HEAD"

    if not forced:
        return False
    if not git_out(["rev-parse", "--verify", "--quiet", push_ref], cwd):
        return False  # remote-tracking ref unknown locally — likely a brand-new branch, nothing to lose
    if not git_out(["rev-parse", "--verify", "--quiet", src_ref], cwd):
        return False  # can't resolve the local side — don't risk a false block

    return git_returncode(["merge-base", "--is-ancestor", push_ref, src_ref], cwd) == 1


def _reset_hard_hit(rest, cwd):
    if "--hard" not in rest:
        return False
    return bool(_working_tree_dirty(cwd))


def _clean_force_hit(rest, cwd):
    if _has_flag_char(rest, "n", ("--dry-run",)):
        return False  # already a preview — nothing is actually deleted regardless of -f
    if not _has_flag_char(rest, "f", ("--force",)):
        return False
    dry_argv = []
    for tok in rest:
        if tok in ("-f", "--force"):
            continue
        if tok.startswith("-") and not tok.startswith("--"):
            trimmed = "-" + tok[1:].replace("f", "")
            if trimmed != "-":
                dry_argv.append(trimmed)
            continue
        dry_argv.append(tok)
    preview = git_out(["clean", "-n"] + dry_argv, cwd)
    if preview is None:
        return False  # can't tell — conservative allow
    return bool(preview.strip())


def _branch_delete_hit(rest, cwd):
    if _has_flag_char(rest, "r", ("--remotes",)):
        return False  # a local remote-tracking ref — trivially recoverable via re-fetch
    forced = _has_flag_char(rest, "D")
    if not forced:
        has_delete = "--delete" in rest or _has_flag_char(rest, "d")
        has_force = "--force" in rest or _has_flag_char(rest, "f")
        forced = has_delete and has_force
    if not forced:
        return False
    names = [tok for tok in rest if not tok.startswith("-")]
    for name in names:
        if git_returncode(["merge-base", "--is-ancestor", name, "HEAD"], cwd) == 1:
            return True  # NOT merged — `-D` discards commits `-d` would have refused to
    return False


def _checkout_discard_target(rest):
    """"." (bare, or after a `--`) means discard-everything. A pre-`--` tree-ish (`HEAD`, a branch,
    a tag) is the checkout source, not a path — it must not disqualify the match, so it's tracked
    separately from the post-`--`/no-`--` positionals that name what gets discarded."""
    seen_dashdash, positionals, pre_dashdash = False, [], []
    for tok in rest:
        if tok == "--":
            seen_dashdash = True
            continue
        if not seen_dashdash and tok in CHECKOUT_SKIP_OPTS:
            return None  # branch creation / detach / interactive — not a path-restore at all
        if not seen_dashdash and tok.startswith("-"):
            continue
        (positionals if seen_dashdash else pre_dashdash).append(tok)
    if seen_dashdash:
        return "." if positionals == ["."] else None
    if pre_dashdash == ["."]:
        return "."
    if len(pre_dashdash) == 2 and pre_dashdash[1] == ".":
        return "."  # single leading tree-ish (e.g. `HEAD`) followed by the discard-everything "."
    return None


def _restore_discard_target(rest):
    """`-S`/`--staged` (boolean, index-only) is NOT the same flag as `-s`/`--source=<tree>`
    (takes a value picking the restore source) — real git distinguishes the two despite the
    near-identical spelling (#240). `-s`/`--source` consumes a following token as its value
    unless it's already glued via `=`."""
    staged, worktree, positionals = False, False, []
    i, n = 0, len(rest)
    while i < n:
        tok = rest[i]
        if tok in ("-p", "--patch"):
            return None  # interactive — not a blind discard
        elif tok in ("-S", "--staged"):
            staged = True
        elif tok in ("-W", "--worktree"):
            worktree = True
        elif tok in ("-s", "--source"):
            if i + 1 < n:
                i += 1  # skip the separate-token source tree-ish value
        elif tok.startswith("--source=") or tok == "--" or tok.startswith("-"):
            pass
        else:
            positionals.append(tok)
        i += 1
    if staged and not worktree:
        return None  # index-only — working tree files are untouched, much less destructive
    return "." if positionals == ["."] else None


def _discard_hit(subcommand, rest, cwd):
    target = _checkout_discard_target(rest) if subcommand == "checkout" else _restore_discard_target(rest)
    if target is None:
        return False
    return bool(_working_tree_dirty(cwd))


def _stash_drop_hit(rest, cwd):
    """True if this is `git stash drop`/`git stash clear` and `git stash list` isn't already
    empty — the same "would this actually discard something" gate every other predicate here
    uses, since stashed work has no `-d`-vs-`-D` safe form and no dry-run preview to fall back on."""
    if not rest or rest[0] not in ("drop", "clear"):
        return False
    stash_list = git_out(["stash", "list"], cwd)
    if stash_list is None:
        return False  # can't tell — conservative allow
    return bool(stash_list.strip())


_MESSAGES = {
    "push": (
        "would force-push and, from locally known remote state, is NOT a fast-forward — it would "
        "discard commits on the remote you haven't merged in. Confirm with the user first, or use "
        "`--force-with-lease` so git itself refuses if the remote moved since your last fetch."
    ),
    "reset": (
        "would `git reset --hard` over uncommitted tracked changes, discarding them irrecoverably. "
        "Confirm with the user first, or `git stash` instead of resetting."
    ),
    "clean": (
        "would `git clean` with a force flag, and a dry run shows it would actually remove files. "
        "Confirm with the user first, or run `git clean -n` to review what would go before forcing it."
    ),
    "branch": (
        "would `git branch -D` a branch that is NOT fully merged into HEAD — commits only reachable "
        "from it would become unreachable. Confirm with the user first, or use `git branch -d` "
        "(which refuses exactly this case) if you only meant to delete an already-merged branch."
    ),
    "discard": (
        "would discard ALL uncommitted tracked changes in the working tree. Confirm with the user "
        "first, or `git stash` before wiping everything."
    ),
    "stash": (
        "would `git stash drop`/`git stash clear` a non-empty stash list, discarding stashed work "
        "irrecoverably — no `-d`-vs-`-D` safe form and no dry-run preview exist for stash. Confirm "
        "with the user first."
    ),
}


def offending(command, cwd):
    """Return (reason, argv) for the first piece that hits one of the six predicates, else None."""
    for argv in pieces(command):
        sub = git_subcommand(strip_prefixes(argv))
        if sub is None:
            continue
        subcommand, rest = sub
        if subcommand == "push" and _push_force_hit(rest, cwd):
            return "push", argv
        if subcommand == "reset" and _reset_hard_hit(rest, cwd):
            return "reset", argv
        if subcommand == "clean" and _clean_force_hit(rest, cwd):
            return "clean", argv
        if subcommand == "branch" and _branch_delete_hit(rest, cwd):
            return "branch", argv
        if subcommand in ("checkout", "restore") and _discard_hit(subcommand, rest, cwd):
            return "discard", argv
        if subcommand == "stash" and _stash_drop_hit(rest, cwd):
            return "stash", argv
    return None


def check(command, cwd):
    """Dispatcher-facing predicate (#163): (command, cwd) -> full block message, or None.

    Fails open (returns None) when `cwd` can't be resolved — every predicate here consults live
    repo state, same contract as block-checkout-held-branch.py (#154).
    """
    if cwd is None:
        return None
    try:
        hit = offending(command, cwd)
    except Exception:
        return None
    if not hit:
        return None
    reason, argv = hit
    shown = " ".join(argv)
    return (
        f"Destructive-git guard (PreToolUse): `{shown}` {_MESSAGES[reason]} (work skill's Tier-A "
        "rail: 'never force-push, hard-delete, or do anything irreversible/destructive without an "
        "explicit yes.')"
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
