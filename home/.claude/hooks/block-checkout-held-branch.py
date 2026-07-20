#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — enforce the git-checkout-vs-worktree cardinal rail.

CLAUDE.md's dev-speed tactics name a concrete, time-costing trap: `git checkout <branch>` (or
`git switch <branch>`) FAILS — `fatal: '<branch>' is already used by worktree at '<path>'`, exit
128 — when that branch is already checked out in another worktree. Re-verified live against git
2.54.0 (#210): every git release with `git worktree` support (2.5+, July 2015 — the protection
shipped together with the worktree feature itself, not added later) raises this fatal error rather
than silently no-opping, including against a stale/prunable worktree whose directory was deleted
out from under git first. (Older docstrings/CLAUDE.md described this as a "SILENT NO-OP — not an
error"; that premise doesn't hold for any git version that can even run this hook's target
scenario, and #210 found no evidence it ever did.) The rail still earns its keep as defense in
depth: it turns git's terse, easy-to-miss fatal error into an upfront block with concrete guidance
(work in the other worktree, or add a detached scratch worktree) before the attempt is even made,
rather than making the agent parse the raw git error and rediscover the fix itself. hooks/README.md
frames this dir as moving CLAUDE.md's cardinal rails 'from aspiration to guarantee'; this is the
first of those rails made mechanical: the delegation-model rule and the egress bump are enforced
today, and 'never checkout a branch a stale worktree holds' is the next crisp,
mechanically-checkable one (#123).

The check: parse the Bash command for a real branch SWITCH (`git checkout <branch>` / `git switch
<branch>` — NOT branch creation, path restore, or a detach), then consult `git worktree list` for
the invoking cwd. If the target branch is held by a DIFFERENT worktree, block with guidance (work
in that worktree, or make a detached scratch worktree) up front, instead of letting the attempt
run into git's own fatal error.

Deliberately narrow to keep false positives near zero — it fires ONLY when all of these hold:
  - the command word (per shell piece) is `git` with subcommand `checkout` or `switch`;
  - exactly one positional target and no `-b`/`-B`/`-c`/`-C`/`--orphan` (creation), no `--detach`
    /`-d`, no `--ignore-other-worktrees` (git itself skips the collision check, #259), and no
    `--`/multi-positional (path restore) — those aren't the held-branch-switch case;
  - that target names a branch some OTHER worktree already holds.
Anything it can't parse cleanly is allowed. Fail-open on any error — a hook bug must never wedge
the session (repo convention). Exit 2 = block; exit 0 = allow.
"""
import os
import sys

from _hookutil import git_out, git_subcommand, hook_tool_input, load_hook_input, pieces, strip_prefixes

# checkout/switch flags that create a branch (take the new name as their value) — NOT a switch into
# an existing, possibly-held branch, so never the held-branch-switch case.
CREATE_OPTS = {"-b", "-B", "-c", "-C", "--orphan"}
# flags that mean "don't land on a branch ref at all" (detached HEAD) — also not the held-branch case.
DETACH_OPTS = {"-d", "--detach"}
# tells git itself to skip the exact worktree-collision check this hook front-runs
# (git-switch(1)/git-checkout(1) --ignore-other-worktrees, audited #259) — git will NOT raise the
# fatal error in this case, so treating the target as held-and-blocked would be a false positive,
# not a conservative miss.
IGNORE_WORKTREE_OPTS = {"--ignore-other-worktrees"}


def checkout_target(argv):
    """Return the branch a `git checkout`/`git switch` argv would SWITCH to, or None.

    Returns None for anything that isn't an unambiguous single-branch switch: a non-git command,
    branch creation (`-b`/`-c`/…), a detach (`--detach`/`-d`), path restore (`--` or >1 positional),
    or an unparsable form. Conservative on purpose — a missed switch is a harmless allow; a
    mis-parsed one must never be a false block.

    `argv` is run through `strip_prefixes()` first (#193) so a wrapper/prefix word ahead of `git`
    (`command git checkout held`, `env git checkout held`, `sudo git checkout held`) still reaches
    the real `git` command word instead of silently bypassing this guard the way a bare
    `basename(argv[0]) != "git"` check would."""
    sub = git_subcommand(strip_prefixes(argv))
    if sub is None or sub[0] not in ("checkout", "switch"):
        return None
    _, rest = sub

    positionals = []
    j, n = 0, len(rest)
    while j < n:
        tok = rest[j]
        if tok == "--":
            return None              # path-restore mode, not a branch switch
        if tok in CREATE_OPTS:
            return None              # creating a branch, not switching into an existing one
        if tok in DETACH_OPTS:
            return None              # detached HEAD, holds no branch ref
        if tok in IGNORE_WORKTREE_OPTS:
            return None              # git itself skips the collision check — not our case to block
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


def check(command, cwd):
    """Dispatcher-facing predicate (#163): (command, cwd) -> full block message, or None.

    Fails open (returns None) when `cwd` can't be resolved (CLAUDE.md's documented contract for
    this hook) — the process's own cwd isn't reliably the project dir, so never substitute it.
    """
    if cwd is None:
        return None
    try:
        hit = offending(command, cwd)
    except Exception:
        return None
    if not hit:
        return None
    target, held = hit
    return (
        f"Worktree guard (PreToolUse): `git checkout {target}` / `git switch {target}` was blocked "
        f"because branch `{target}` is already checked out in another worktree ({held}). git would "
        "raise a fatal error here (exit 128, `already used by worktree at ...`) rather than switch "
        "(CLAUDE.md dev-speed tactics). Work in that worktree "
        f"directly (`cd {held}`), or if you need this branch's tree here, add a detached scratch "
        f"worktree (`git worktree add --detach <path> {target}`) instead of switching in place."
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
