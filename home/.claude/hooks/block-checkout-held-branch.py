#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — enforce the git-checkout-vs-worktree cardinal rail.

CLAUDE.md's dev-speed tactics name a concrete, time-costing trap: `git checkout <branch>` (or
`git switch <branch>`) is a SILENT NO-OP — not an error — when that branch is already checked out
in another worktree. The shell prints nothing useful, the working tree doesn't move, and the next
commands run against the wrong branch. hooks/README.md frames this dir as moving CLAUDE.md's
cardinal rails 'from aspiration to guarantee'; this is the first of those rails made mechanical:
the delegation-model rule and the egress bump are enforced today, and 'never checkout a branch a
stale worktree holds' is the next crisp, mechanically-checkable one (#123).

The check: parse the Bash command for a real branch SWITCH (`git checkout <branch>` / `git switch
<branch>` — NOT branch creation, path restore, or a detach), then consult `git worktree list` for
the invoking cwd. If the target branch is held by a DIFFERENT worktree, block with guidance (work
in that worktree, or make a detached scratch worktree) instead of letting the no-op happen.

Deliberately narrow to keep false positives near zero — it fires ONLY when all of these hold:
  - the command word (per shell piece) is `git` with subcommand `checkout` or `switch`;
  - exactly one positional target and no `-b`/`-B`/`-c`/`-C`/`--orphan` (creation), no `--detach`
    /`-d`, and no `--`/multi-positional (path restore) — those aren't the silent-no-op case;
  - that target names a branch some OTHER worktree already holds.
Anything it can't parse cleanly is allowed. Fail-open on any error — a hook bug must never wedge
the session (repo convention). Exit 2 = block; exit 0 = allow.
"""
import json
import os
import re
import shlex
import subprocess
import sys

PUNCT = ";|&<>()"
OPERATOR_RE = re.compile(r"^[;|&]+$")
SPLIT_RE = re.compile(r"&&|\|\||[;|&]")

# git global options that consume a following value, so we can walk past them to the subcommand
# (`git -C /path checkout foo`, `git -c k=v switch foo`). `--opt=value` forms carry their own value
# and are skipped as ordinary flags below.
GIT_GLOBAL_VALUE_OPTS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
}
# checkout/switch flags that create a branch (take the new name as their value) — NOT a switch into
# an existing, possibly-held branch, so never the silent-no-op case.
CREATE_OPTS = {"-b", "-B", "-c", "-C", "--orphan"}
# flags that mean "don't land on a branch ref at all" (detached HEAD) — also not the no-op case.
DETACH_OPTS = {"-d", "--detach"}


def basename(word):
    return word.rsplit("/", 1)[-1]


def pieces(command):
    """Yield the argv of each simple command, splitting on shell operators outside quotes.

    Mirrors block-egress.py's splitter so `foo && git checkout main` is inspected piece-by-piece.
    Falls back to a raw regex split when shlex can't tokenize (unbalanced quotes)."""
    for line in command.split("\n"):
        if not line.strip():
            continue
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=PUNCT)
            lex.whitespace_split = True
            toks = list(lex)
        except ValueError:
            for raw in SPLIT_RE.split(line):
                if raw.strip():
                    yield raw.split()
            continue
        argv = []
        for tok in toks:
            if OPERATOR_RE.match(tok):
                if argv:
                    yield argv
                argv = []
            else:
                argv.append(tok)
        if argv:
            yield argv


def checkout_target(argv):
    """Return the branch a `git checkout`/`git switch` argv would SWITCH to, or None.

    Returns None for anything that isn't an unambiguous single-branch switch: a non-git command,
    branch creation (`-b`/`-c`/…), a detach (`--detach`/`-d`), path restore (`--` or >1 positional),
    or an unparsable form. Conservative on purpose — a missed switch is a harmless allow; a
    mis-parsed one must never be a false block."""
    if not argv or basename(argv[0]) != "git":
        return None
    i, n = 1, len(argv)
    while i < n:                      # walk past git global options to the subcommand
        tok = argv[i]
        if tok in GIT_GLOBAL_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= n or argv[i] not in ("checkout", "switch"):
        return None

    positionals = []
    j = i + 1
    while j < n:
        tok = argv[j]
        if tok == "--":
            return None              # path-restore mode, not a branch switch
        if tok in CREATE_OPTS:
            return None              # creating a branch, not switching into an existing one
        if tok in DETACH_OPTS:
            return None              # detached HEAD, holds no branch ref
        if tok.startswith("-"):
            j += 1                   # some other flag (-f/-q/--track/…); value-taking forms are rare
            continue                 # and only cause a harmless miss, never a false block
        positionals.append(tok)
        j += 1
    if len(positionals) != 1:        # 0 = nothing to switch to; >1 = likely `checkout <ref> <paths>`
        return None
    target = positionals[0]
    if target.startswith("refs/heads/"):
        target = target[len("refs/heads/"):]
    return target


def git_out(args, cwd):
    """Run a git command in cwd and return stdout, or None on any failure (fail-open)."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def holding_worktree(target, cwd):
    """Return the path of a worktree OTHER than cwd's that has `target` checked out, else None."""
    listing = git_out(["worktree", "list", "--porcelain"], cwd)
    if listing is None:
        return None
    top = git_out(["rev-parse", "--show-toplevel"], cwd)
    if not top:
        return None                  # can't identify the current worktree — don't risk a false block
    current = os.path.realpath(top.strip())

    wt_path = None
    for line in listing.splitlines():
        if line.startswith("worktree "):
            wt_path = line[len("worktree "):]
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            name = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
            if name == target and wt_path and os.path.realpath(wt_path) != current:
                return wt_path
    return None


def offending(command, cwd):
    """Return (target, worktree_path) for a checkout of a branch another worktree holds, else None."""
    for argv in pieces(command):
        target = checkout_target(argv)
        if not target:
            continue
        held = holding_worktree(target, cwd)
        if held:
            return target, held
    return None


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

    cwd = data.get("cwd") or None

    try:
        hit = offending(command, cwd)
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not hit:
        sys.exit(0)

    target, held = hit
    print(
        f"Worktree guard (PreToolUse): `git checkout {target}` / `git switch {target}` was blocked "
        f"because branch `{target}` is already checked out in another worktree ({held}). git makes "
        "this a SILENT NO-OP — not an error — so the working tree would not move and later commands "
        "would run against the wrong branch (CLAUDE.md dev-speed tactics). Work in that worktree "
        f"directly (`cd {held}`), or if you need this branch's tree here, add a detached scratch "
        f"worktree (`git worktree add --detach <path> {target}`) instead of switching in place.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
