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

Eight independent, narrowly-scoped predicates, each run against every relevant piece of the
command. Like every other rail here, each is a deliberate "speed bump, not a seal": a missed
detection is a harmless allow, so seven of the eight are conservative — anything they can't
confidently resolve (a repo they can't read, a ref they can't verify, an argv shape they don't
recognize) is allowed, never blocked.

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
  - `git checkout -- .` / `git checkout .` / `git restore .` / `git switch --discard-changes`
    (default or `--worktree` mode — a working-tree-only `--staged` restore doesn't touch files, so
    it's out of scope), UNLESS the working tree has no uncommitted tracked changes. Deliberately
    narrow to exactly "discard EVERYTHING" (`.`, the whole tree, or switch's equivalent
    `--discard-changes` flag, audited #259) — `git checkout -- some/file.txt` is an ordinary, common,
    deliberate discard of one file and is left alone.
  - `git stash drop [<stash>]` / `git stash clear`, UNLESS `git stash list` is already empty
    (nothing to lose). Stashed work has no `-d`-vs-`-D` safe alternative and no dry-run preview,
    so any non-empty stash list is treated as something that could be lost (#239).
  - `gh pr merge` (any form), `gh release create` (UNLESS `--draft`, which stays invisible until a
    later publish step), or `npm publish` (UNLESS `--dry-run`, which publishes nothing) (#242).
    Unlike the other seven, this predicate has no repo state to consult that would prove the action
    safe — the Tier-A rule requires an explicit yes before ANY merge/publish, not just a risky one
    — so, once matched, it fires unconditionally rather than being gated on "would this actually
    lose something."
  - `git push` straight to a branch GitHub reports as protected (bypassing PR review entirely),
    UNLESS the destination can't be resolved from the argv (a delete-push, a multi-ref
    `--all`/`--mirror`/`--tags` form, or a detached HEAD) or `gh api
    repos/<owner>/<repo>/branches/<branch>/protection` doesn't confirm it (#252). `<owner>`/`<repo>`
    are resolved from the SPECIFIC remote the push argv actually targets (`git remote get-url
    <remote>`, parsed against github.com URL forms), not `gh`'s own ambient default-repo context —
    those can diverge in a fork workflow (`origin` = your fork, `upstream` = the real repo,
    possibly gh-configured as the default), where trusting gh's ambient resolution instead of the
    push's actual destination could check the wrong repo's protection (#264). This hook installs
    into every repo the user works in (install.sh symlinks hooks/ into `~/.claude/hooks/` globally),
    and plenty of ordinary repos push straight to `main` with no PR workflow at all — #242 itself
    warned that a blanket "push to main/master" name match would be false-positive-prone there, so
    this asks GitHub whether the branch is ACTUALLY protected rather than guessing from its name.
    Same fail-open convention as every state-consulting predicate here: no `gh` on PATH, no auth, an
    unparsable/non-GitHub remote URL, or any API error reads as "not protected," never as a block.

A piece's command word is read through `_hookutil.strip_prefixes()`/`git_subcommand()` (#193, #230)
— the same wrapper/prefix canonicalization and git-global-option walk block-checkout-held-branch.py
uses — so `command git push -f`, `sudo git reset --hard`, `git -c foo=bar clean -f`, etc. all reach
the real subcommand. `git_subcommand()` also refuses to look past a `-C`/`--git-dir`/`--work-tree`
global option (redirects git at a different repo than the hook-input `cwd` — inspecting cwd's state
would consult the wrong repo, #154), same as the checkout rail.

Fail-open on any error — a hook bug must never wedge the session (repo convention). Exit 2 =
block; exit 0 = allow.
"""
import os
import re
import subprocess
import sys
from urllib.parse import quote

from _hookutil import (
    basename,
    gh_skip_repo_flag,
    gh_subcommand,
    git_out,
    git_returncode,
    git_subcommand,
    hook_tool_input,
    load_hook_input,
    pieces,
    strip_prefixes,
    strip_redirects,
    walk_past_flags,
)

# checkout flags that mean this isn't a blind path-restore at all (branch creation, detach,
# interactive) — never the discard-everything case.
CHECKOUT_SKIP_OPTS = {"-b", "-B", "-c", "-C", "--orphan", "-d", "--detach", "-p", "--patch"}
# `git push` flags that consume a separate following token as their value (#237) — same
# separate-vs-glued gap GIT_GLOBAL_VALUE_OPTS/WRAPPER_VALUE_OPTS/SUDO_VALUE_OPTS guard against.
# `--opt=value` forms carry their own value and need no special handling here. `--exec` is a
# documented exact synonym of `--receive-pack` (man git-push) — same separate-token-value grammar
# — and its omission let its value token slip into `positionals`, tripping the `len(positionals) >
# 2` conservative-allow branch below on an otherwise ordinary `git push --exec <path> -f origin
# main` (#288).
PUSH_VALUE_OPTS = {"-o", "--push-option", "--receive-pack", "--repo", "--exec"}

# Matches the github.com URL forms `git remote get-url` can hand back: https (with an optional
# userinfo, e.g. a token-authenticated CI remote), the git@host: scp-like shorthand, ssh://, and
# the plain git:// protocol — capturing owner/repo with an optional trailing `.git` (#264).
GITHUB_REMOTE_RE = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/|git://github\.com/)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


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


def _current_branch(cwd):
    """Return the current branch name, or None for a detached HEAD or an unresolvable repo state."""
    branch = git_out(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if not branch or branch.strip() == "HEAD":
        return None
    return branch.strip()


def _strip_push_value_opts(rest):
    """Filter `PUSH_VALUE_OPTS` (and bundled short `-o`) out of a `git push` argv, leaving only
    tokens relevant to the force-flag/positional scan. Handles three shapes of `-o`/
    `--push-option` (and friends): the fully-glued `-ofield=1`, the bare separate-token `-o
    field=1`, and `-o` BUNDLED with boolean short flags in one token (`-fo field=1`, `-fofield=1`,
    #253) — git's own short-option-cluster grammar, where a value-taking short flag consumes
    everything after it in the same token as a glued value, or the next token if nothing follows
    in that token. Boolean flags preceding `o` in a bundled cluster are preserved as their own
    `-`-prefixed token so `_has_flag_char()` still sees them; anything at or after `o` is dropped
    as `-o`'s value, never exposed to the force-flag/positional scan (mirrors the #246 rationale
    for why a glued value's stray "f" byte must not false-trigger `forced`)."""
    filtered, i, n = [], 0, len(rest)
    while i < n:
        tok = rest[i]
        if tok.startswith("-") and not tok.startswith("--") and "o" in tok[1:]:
            o_idx = tok.index("o", 1)
            booleans = tok[1:o_idx]
            if booleans:
                filtered.append("-" + booleans)
            if o_idx + 1 >= len(tok) and i + 1 < n:
                i += 1  # nothing follows 'o' in this token — its value is the next token
            i += 1
            continue
        filtered.append(tok)
        if tok in PUSH_VALUE_OPTS and i + 1 < n:
            i += 1  # drop the value token entirely — it can't be a flag or a real positional
        i += 1
    return filtered


def _resolve_refspec(remote, refspec, cwd):
    """Resolve one `git push` refspec token to `(dst_branch, src_ref, push_ref, leading_plus)`,
    or None if it can't be confidently read as a content-pushing ref (a delete-refspec, or a
    non-branch fully-qualified ref). Shared by `_push_force_hit`/`_push_dest_branches` so a
    multi-refspec push (`git push <remote> <refspec1> <refspec2> ...`, real git grammar, #327)
    can check every refspec the same way the single-refspec case already did."""
    leading_plus = refspec.startswith("+")
    if leading_plus:
        refspec = refspec[1:]
    src, _, dst = refspec.partition(":")
    dst = dst if ":" in refspec else src
    if not src or not dst:
        return None  # a delete-refspec (":branch" / "branch:") — out of scope
    if ":" not in refspec and dst in ("HEAD", "@"):
        # bare `HEAD` (no colon) resolves to the current branch's actual name, not a literal
        # branch called "HEAD" — same resolution the 1-positional implicit-push case uses (#319);
        # `@` is git's documented synonym for `HEAD` in revision/refspec contexts
        # (git-rev-parse(1)) and hits the exact same literal-branch-name bug (#326)
        branch = _current_branch(cwd)
        if branch is None:
            return None  # detached HEAD, or can't tell — conservative allow
        dst = branch
    # a refspec destination may be fully-qualified (`git push origin +feature:refs/heads/main`),
    # not just a short branch name — fail open on any other `refs/...` namespace (tags, notes, ...)
    # rather than build a bogus `refs/remotes/{remote}/refs/heads/...` ref that `rev-parse
    # --verify` can never resolve, which would otherwise misread as "brand-new branch, nothing to
    # lose" (#261)
    heads_prefix = "refs/heads/"
    if dst.startswith(heads_prefix):
        dst = dst[len(heads_prefix):]
    elif dst.startswith("refs/"):
        return None  # non-branch fully-qualified ref — out of scope, conservative allow
    return dst, src, f"refs/remotes/{remote}/{dst}", leading_plus


def _push_force_hit(rest, cwd):
    """True if this `git push` argv force-pushes and, from locally known remote state, is
    provably NOT a fast-forward (would discard commits on the remote we haven't merged in)."""
    if any(tok == "--force-with-lease" or tok.startswith("--force-with-lease=") for tok in rest):
        return False  # git's own safe form — it refuses server-side if the remote moved

    rest = strip_redirects(rest)  # a trailing `> file`/`2>&1` must not inflate positionals (#359)
    rest = _strip_push_value_opts(rest)

    forced = _has_flag_char(rest, "f", ("--force",))
    # `-d`/`--delete` is checked via `_has_flag_char` (not exact-token, like `--all`/`--mirror`/
    # `--tags`) so a bundled `-fd` is recognized as a delete-push too, not just a standalone `-d`
    # (#245) — the same bundling `_has_flag_char` already gives `forced` above, mirroring the
    # `-r`/`--remotes` pattern in `_branch_delete_hit`.
    out_of_scope = _has_flag_char(rest, "d", ("--delete",))
    positionals = []
    for tok in rest:
        if tok in ("--all", "--mirror", "--tags"):
            out_of_scope = True  # multi-ref push — a different risk, not scoped here
        elif not tok.startswith("-"):
            positionals.append(tok)
    if out_of_scope:
        return False  # too broad to reason about safely — conservative allow

    if len(positionals) >= 2:
        # real `git push` accepts multiple ordinary refspecs after the remote (`git push <remote>
        # <refspec1> <refspec2> ...`, git-push(1)) — a common, unremarkable form, not just the
        # --all/--mirror/--tags case handled above. Check every refspec, not just a pair, so a
        # throwaway extra refspec can't hide a force-push on another one (#327).
        remote = positionals[0]
        for refspec in positionals[1:]:
            resolved = _resolve_refspec(remote, refspec, cwd)
            if resolved is None:
                continue
            _dst, src_ref, push_ref, leading_plus = resolved
            if not (forced or leading_plus):
                continue
            if not git_out(["rev-parse", "--verify", "--quiet", push_ref], cwd):
                continue  # remote-tracking ref unknown locally — likely brand-new, nothing to lose
            if not git_out(["rev-parse", "--verify", "--quiet", src_ref], cwd):
                continue  # can't resolve the local side — don't risk a false block
            if git_returncode(["merge-base", "--is-ancestor", push_ref, src_ref], cwd) == 1:
                return True
        return False

    if not forced:
        return False
    if len(positionals) == 1:
        branch = _current_branch(cwd)
        if branch is None:
            return False  # no branch (detached) or can't tell — conservative allow
        push_ref, src_ref = f"refs/remotes/{positionals[0]}/{branch}", "HEAD"
    else:
        push_ref, src_ref = "@{push}", "HEAD"

    if not git_out(["rev-parse", "--verify", "--quiet", push_ref], cwd):
        return False  # remote-tracking ref unknown locally — likely a brand-new branch, nothing to lose
    if not git_out(["rev-parse", "--verify", "--quiet", src_ref], cwd):
        return False  # can't resolve the local side — don't risk a false block

    return git_returncode(["merge-base", "--is-ancestor", push_ref, src_ref], cwd) == 1


def _push_dest_branches(rest, cwd):
    """Return every destination branch name this `git push` argv would push to (usually one, but
    real git accepts multiple refspecs in a single push — see `_push_force_hit`, #327), or `[]` if
    none can be confidently resolved (a delete-push, a multi-ref `--all`/`--mirror`/`--tags` form,
    or a detached/unresolvable HEAD on an implicit push). Same `_strip_push_value_opts` filtering
    `_push_force_hit` applies before reading positionals (#246); a bare `git push` or `git push
    <remote>` (no refspec) is resolved as pushing the current branch under its own name — git's
    push.default=simple/current behavior (the default since git 2.0) — mirroring the implicit-push
    branch resolution `_push_force_hit` already does for its own fast-forward check (#252)."""
    rest = strip_redirects(rest)  # a trailing `> file`/`2>&1` must not inflate positionals (#359)
    rest = _strip_push_value_opts(rest)

    if _has_flag_char(rest, "d", ("--delete",)):
        return []  # a branch delete-push — no content pushed, out of scope
    positionals = []
    for tok in rest:
        if tok in ("--all", "--mirror", "--tags"):
            return []  # multi-ref push — not resolvable to specific destinations
        elif not tok.startswith("-"):
            positionals.append(tok)

    if len(positionals) >= 2:
        remote, branches = positionals[0], []
        for refspec in positionals[1:]:
            resolved = _resolve_refspec(remote, refspec, cwd)
            if resolved is not None:
                branches.append(resolved[0])
        return branches

    branch = _current_branch(cwd)
    return [branch] if branch else []


def _remote_owner_repo(remote, cwd):
    """Resolve (owner, repo) from `remote`'s OWN configured URL (`git remote get-url`) — NOT `gh
    api`'s ambient default-repo context, which `gh` resolves from cwd's git remotes using its own
    heuristic and which need not agree with the specific remote a push argv names (#264). In a
    fork workflow (`origin` = your fork, `upstream` = the real repo, possibly gh-configured as the
    default via `gh repo set-default`), trusting gh's ambient resolution instead of the push's
    actual destination remote could check the wrong repo's protection — a false BLOCK on a safe
    push to your own fork, or a missed block the other direction. None if `remote` is unset, its
    URL can't be read, or it isn't a github.com URL this can parse — same fail-open contract as
    every other repo-state check in this file: an unresolved answer must never be read as
    "protected"."""
    url = git_out(["remote", "get-url", remote], cwd)
    if not url:
        return None
    m = GITHUB_REMOTE_RE.match(url.strip())
    if not m:
        return None
    return m.group("owner"), m.group("repo")


def _push_remote(rest, cwd):
    """Return the remote name a `git push` argv actually pushes to — the explicit positional if
    one is given, otherwise the current branch's configured push remote (`branch.<name>.remote`,
    the same implicit-push remote git itself resolves to) — or None if neither can be determined."""
    rest = strip_redirects(rest)
    rest = _strip_push_value_opts(rest)
    positionals = [tok for tok in rest if not tok.startswith("-")]
    if positionals:
        return positionals[0]
    branch = _current_branch(cwd)
    if branch is None:
        return None
    remote = git_out(["config", "--get", f"branch.{branch}.remote"], cwd)
    return remote.strip() if remote else None


def _branch_protected(branch, owner_repo, cwd):
    """True only if GitHub confirms `branch` is a protected branch of the SPECIFIC repo
    `owner_repo` resolves to (#264). False for everything else — not protected, `owner_repo`
    unresolved, no `gh` on PATH, `gh` unauthenticated, a network hiccup, ... — same fail-open
    contract as every other repo-state check in this file: an unresolved answer must never be
    read as "protected" (#252). The branch name is substituted literally (percent-encoded, since
    GitHub's branch-protection endpoint requires a literal `/` in a branch name to be escaped as
    `%2F`) since we're checking the push's actual destination, not necessarily the branch checked
    out in cwd."""
    if owner_repo is None:
        return False
    owner, repo = owner_repo
    endpoint = (
        f"repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        f"/branches/{quote(branch, safe='')}/protection"
    )
    try:
        r = subprocess.run(
            ["gh", "api", endpoint], cwd=cwd, capture_output=True, timeout=5,
        )
    except Exception:
        return False
    return r.returncode == 0


def _push_protected_hit(rest, cwd):
    """True if ANY destination branch this push resolves to (there can be more than one — a
    multi-refspec push, #327) is GitHub-protected on the repo the PUSHED-TO remote actually points
    at (#264, `_push_remote()`/`_remote_owner_repo()`) — a throwaway extra refspec must not shield
    a protected-branch push hiding among the others."""
    branches = _push_dest_branches(rest, cwd)
    if not branches:
        return False
    remote = _push_remote(rest, cwd)
    owner_repo = _remote_owner_repo(remote, cwd) if remote else None
    return any(_branch_protected(branch, owner_repo, cwd) for branch in branches)


def _reset_hard_hit(rest, cwd):
    if "--hard" not in rest:
        return False
    return bool(_working_tree_dirty(cwd))


def _clean_boolean_view(rest):
    """Return `rest` with each short-cluster token's glued `-e<pattern>` value (git-clean(1)'s
    only short glued-value flag, alone or bundled behind other boolean chars like `-fe<pattern>`)
    truncated to just the flag letters up to and including 'e' — so a scan for a BOOLEAN flag
    character can't be spoofed by an arbitrary byte sitting inside the exclude pattern's own text
    (#248: `-en*.log` contains the byte 'n', which must not be misread as `-n`/--dry-run). Mirrors
    the identical truncation `_clean_force_hit()` already applies when building the `-n` preview's
    own argv (#258/#299), but as a read-only view used purely for `_has_flag_char()` scans — the
    real pattern text passed to git itself must stay verbatim, so this is never used for that."""
    out = []
    for tok in rest:
        if tok.startswith("-") and not tok.startswith("--"):
            e_idx = tok.find("e", 1)
            if e_idx != -1:
                out.append(tok[:e_idx + 1])
                continue
        out.append(tok)
    return out


def _clean_force_hit(rest, cwd):
    flags = _clean_boolean_view(rest)
    if _has_flag_char(flags, "n", ("--dry-run",)):
        return False  # already a preview — nothing is actually deleted regardless of -f
    if not _has_flag_char(flags, "f", ("--force",)):
        return False
    dry_argv = []
    for tok in rest:
        if tok in ("-f", "--force"):
            continue
        if tok.startswith("-") and not tok.startswith("--"):
            cluster = tok[1:]
            e_idx = cluster.find("e")
            if e_idx != -1:
                # `-e` (git-clean(1)'s only short glued-value flag) can itself be bundled behind
                # other boolean short flags in the same token (`-fe*.staff` = `-f` + `-e*.staff`,
                # #299) — everything from the FIRST 'e' onward is that flag's arbitrary-text
                # value, not more boolean-flag chars, so it must reach git verbatim; the blanket
                # 'f'-strip below would otherwise silently corrupt any 'f' byte in the pattern
                # itself (`-e*.staff` -> `-e*.sta`), changing what the -n preview matches (#258).
                booleans = cluster[:e_idx].replace("f", "")
                if booleans:
                    dry_argv.append("-" + booleans)
                dry_argv.append("-" + cluster[e_idx:])
                continue
            trimmed = "-" + cluster.replace("f", "")
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


def _pathspec_from_file_hit(rest, cwd):
    """`--pathspec-from-file=<file>`/`--pathspec-from-file <file>` (real flags on both
    git-checkout(1) and git-restore(1)) supply the discard pathspec via a file instead of argv —
    `git checkout --pathspec-from-file=discard.txt` with a bare '.' inside the file discards the
    whole tree with zero pathspec tokens for the argv scan to see (#347). Only recognized before a
    `--`: real git stops option parsing there (live-verified — after `--` the same token is read
    as a literal, unmatched pathspec and git errors out with nothing discarded), so scanning past
    it would false-block a command git itself rejects. `<file>` is `-` for stdin — not read here
    (no stdin content available to the hook, and nothing safe to read it from) — same conservative
    fail-open as any repo state this hook can't resolve: unreadable or stdin reads as "no match",
    never a block. `--pathspec-file-nul` switches the element separator from LF to NUL, same as
    real git."""
    file_arg, nul_separated = None, False
    for i, tok in enumerate(rest):
        if tok == "--":
            break
        if tok == "--pathspec-file-nul":
            nul_separated = True
        elif tok.startswith("--pathspec-from-file="):
            file_arg = tok.split("=", 1)[1]
        elif tok == "--pathspec-from-file" and i + 1 < len(rest):
            file_arg = rest[i + 1]
    if not file_arg or file_arg == "-":
        return None
    path = file_arg if os.path.isabs(file_arg) else os.path.join(cwd, file_arg)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    entries = content.split("\0") if nul_separated else content.splitlines()
    return "." if any(entry.strip() == "." for entry in entries) else None


def _checkout_discard_target(rest, cwd):
    """"." (bare, or after a `--`) means discard-everything. A pre-`--` tree-ish (`HEAD`, a branch,
    a tag) is the checkout source, not a path — it must not disqualify the match, so it's tracked
    separately from the post-`--`/no-`--` positionals that name what gets discarded."""
    rest = strip_redirects(rest)  # a trailing `> file`/`2>&1` must not inflate positionals (#366)
    seen_dashdash, positionals, pre_dashdash = False, [], []
    i, n = 0, len(rest)
    while i < n:
        tok = rest[i]
        if tok == "--":
            seen_dashdash = True
            i += 1
            continue
        if not seen_dashdash and tok in CHECKOUT_SKIP_OPTS:
            return None  # branch creation / detach / interactive — not a path-restore at all
        if not seen_dashdash and tok == "--pathspec-from-file" and i + 1 < n:
            i += 2  # skip the flag and its separate-token file argument (#347)
            continue
        if not seen_dashdash and tok.startswith("-"):
            i += 1
            continue
        (positionals if seen_dashdash else pre_dashdash).append(tok)
        i += 1
    if _pathspec_from_file_hit(rest, cwd) == ".":
        return "."
    if seen_dashdash:
        # "." is unioned with any other pathspec, not intersected — `. README.md` still discards
        # everything `.` alone would, so "." anywhere in the list is sufficient (#320)
        return "." if "." in positionals else None
    if pre_dashdash[:1] == ["."]:
        return "."  # bare "." (optionally followed by more pathspecs) — already discards everything
    if len(pre_dashdash) >= 2 and "." in pre_dashdash[1:]:
        return "."  # single leading tree-ish (e.g. `HEAD`) followed by "." among the pathspecs
    return None


def _switch_discard_target(rest):
    """`git switch --discard-changes` throws away ALL local modifications when switching branches —
    the same destructive semantics as `checkout .`/`restore .`, but expressed as a boolean flag
    instead of a `.` pathspec (switch takes a branch, not paths), so it needs its own recognizer
    rather than reusing `_checkout_discard_target`'s pathspec scan (audited #259)."""
    return "." if "--discard-changes" in rest else None


def _restore_discard_target(rest, cwd):
    """`-S`/`--staged` (boolean, index-only) is NOT the same flag as `-s`/`--source=<tree>`
    (takes a value picking the restore source) — real git distinguishes the two despite the
    near-identical spelling (#240). `-s`/`--source` consumes a following token as its value
    unless it's already glued via `=`."""
    rest = strip_redirects(rest)  # a trailing `> file`/`2>&1` must not inflate positionals (#366)
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
        elif tok == "--pathspec-from-file" and i + 1 < n:
            i += 1  # skip the separate-token file argument (#347)
        elif tok.startswith("--source=") or tok == "--" or tok.startswith("-"):
            pass
        else:
            positionals.append(tok)
        i += 1
    if staged and not worktree:
        return None  # index-only — working tree files are untouched, much less destructive
    if _pathspec_from_file_hit(rest, cwd) == ".":
        return "."
    # "." is unioned with any other pathspec, not intersected — "." anywhere in the list already
    # discards everything, same as `_checkout_discard_target`'s post-`--` case (#320)
    return "." if "." in positionals else None


def _discard_hit(subcommand, rest, cwd):
    if subcommand == "checkout":
        target = _checkout_discard_target(rest, cwd)
    elif subcommand == "switch":
        target = _switch_discard_target(rest)
    else:
        target = _restore_discard_target(rest, cwd)
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


# npm global flags known to take a separate/glued value, so `_merge_publish_hit()` can walk past
# one sitting ahead of the subcommand (`npm --registry=https://... publish`, #284) the same way
# `gh_subcommand()` walks past `-R`/`--repo`. npm (a yargs-style CLI, not a fixed-position parser)
# accepts its global config flags before OR after the subcommand — this is npm's own documented
# `npm <flags> <command> [args]` usage, not an edge case. A flag NOT in this set is treated as
# boolean (see `_npm_subcommand()`), so a real value-taking flag missing from here would have its
# value token misread as the subcommand and the actual `publish` past it would go undetected (#287).
# Every entry below is every config npm itself (`@npmcli/config`'s `definitions.js`, npm 10.9.8)
# defines with a non-boolean type — i.e. every flag that ALWAYS consumes a following token as its
# value, generated from npm's own source rather than hand-audited against docs. Deliberately
# excludes `--browser`/`--color`: npm defines both as EITHER boolean OR a value (`--color always`
# vs. bare `--color`), so unlike every flag below, whether the next token is a value can't be
# decided without knowing what that token is — treating them as always-boolean (i.e. leaving them
# out, same as before this audit) is the safe default: it correctly reads `npm --color publish` as
# subcommand `publish`, whereas always-consuming would misread `publish` itself as `--color`'s
# value and miss the subcommand entirely.
NPM_GLOBAL_VALUE_OPTS = {
    "--_auth", "--access", "--also", "--audit-level", "--auth-type", "--before", "--ca", "--cache",
    "--cache-max", "--cache-min", "--cafile", "--call", "-c", "--cert", "--cidr", "--cpu", "--depth",
    "--diff", "--diff-dst-prefix", "--diff-src-prefix", "--diff-unified", "--editor",
    "--expect-result-count", "--fetch-retries", "--fetch-retry-factor", "--fetch-retry-maxtimeout",
    "--fetch-retry-mintimeout", "--fetch-timeout", "--git", "--globalconfig", "--heading",
    "--https-proxy", "--include", "--init-author-email", "--init-author-name", "--init-author-url",
    "--init-license", "--init-module", "--init-version", "--init.author.email", "--init.author.name",
    "--init.author.url", "--init.license", "--init.module", "--init.version", "--install-strategy",
    "--key", "--libc", "--local-address", "--location", "-L", "--lockfile-version", "--loglevel",
    "--logs-dir", "--logs-max", "--maxsockets", "--message", "-m", "--node-options", "--noproxy",
    "--omit", "--only", "--os", "--otp", "--pack-destination", "--package", "--prefix", "-C",
    "--preid", "--provenance-file", "--proxy", "--registry", "--replace-registry-host",
    "--save-prefix", "--sbom-format", "--sbom-type", "--scope", "--script-shell", "--searchexclude",
    "--searchlimit", "--searchopts", "--searchstaleness", "--shell", "--tag", "--tag-version-prefix",
    "--umask", "--user-agent", "--userconfig", "--viewer", "--which", "--workspace", "-w",
}


def _npm_subcommand(argv):
    """Return (subcommand, rest_argv) for an `npm ...` argv, walking past known global value
    flags to find it — or None for a non-npm command or one with no subcommand at all. Delegates
    the walk itself to `_hookutil.walk_past_flags()` (#300), same shared shape
    `git_subcommand()`/`gh_subcommand()` use — only `NPM_GLOBAL_VALUE_OPTS` stays local here."""
    if not argv or basename(argv[0]) != "npm":
        return None
    idx = walk_past_flags(argv, 1, NPM_GLOBAL_VALUE_OPTS)
    if idx is None:
        return None
    return argv[idx], argv[idx + 1:]


def _merge_publish_hit(argv):
    """Return "merge"/"publish" if `argv` (already run through `strip_prefixes()`) is a `gh pr
    merge`, `gh release create`, or `npm publish` — else None. Unconditional, not state-gated
    (#242): there's no repo state that proves a merge/publish safe, so any match is a hit."""
    if not argv:
        return None
    cmd = basename(argv[0])
    if cmd == "gh":
        sub = gh_subcommand(argv)
        if sub is None:
            return None
        subcommand, rest = sub
        rest = gh_skip_repo_flag(rest)  # `gh pr -R owner/repo merge 123` (#301)
        if subcommand == "pr" and len(rest) >= 1 and rest[0] == "merge":
            return "merge"
        if subcommand == "release" and len(rest) >= 1 and rest[0] == "create":
            if _has_flag_char(rest[1:], "d", ("--draft", "--draft=true")):
                return None  # a draft stays invisible until a later, separate publish step
            return "publish"
        return None
    if cmd == "npm":
        sub = _npm_subcommand(argv)
        if sub is None:
            return None
        subcommand, rest = sub
        if subcommand == "publish":
            if "--dry-run" in rest:
                return None  # prints what would be published; nothing actually goes out
            return "publish"
        return None
    return None


_MESSAGES = {
    "push": (
        "would force-push and, from locally known remote state, is NOT a fast-forward — it would "
        "discard commits on the remote you haven't merged in. Confirm with the user first, or use "
        "`--force-with-lease` so git itself refuses if the remote moved since your last fetch."
    ),
    "push-protected": (
        "would push directly to a branch GitHub reports as protected, bypassing PR review "
        "entirely. Confirm with the user first, or open a PR instead."
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
    "merge": (
        "would run `gh pr merge`, completing a PR merge. Confirm with the user first — a merge "
        "needs an explicit yes regardless of whether it's risky."
    ),
    "publish": (
        "would publish (`gh release create` / `npm publish`), making it visible outside this "
        "session. Confirm with the user first — a publish needs an explicit yes regardless of "
        "whether it's risky."
    ),
}


def offending(command, cwd):
    """Return (reason, argv) for the first piece that hits one of the eight predicates, else None.

    `_merge_publish_hit()` consults no repo state, so it runs even when `cwd` is None; the other
    seven all read live git state through `cwd` and are skipped entirely when it's unresolved (the
    caller's fail-open contract, #230) rather than risk consulting the wrong repo (#154)."""
    for argv in pieces(command):
        stripped = strip_prefixes(argv)
        merge_publish = _merge_publish_hit(stripped)
        if merge_publish:
            return merge_publish, argv
        if cwd is None:
            continue
        sub = git_subcommand(stripped)
        if sub is None:
            continue
        subcommand, rest = sub
        if subcommand == "push" and _push_force_hit(rest, cwd):
            return "push", argv
        if subcommand == "push" and _push_protected_hit(rest, cwd):
            return "push-protected", argv
        if subcommand == "reset" and _reset_hard_hit(rest, cwd):
            return "reset", argv
        if subcommand == "clean" and _clean_force_hit(rest, cwd):
            return "clean", argv
        if subcommand == "branch" and _branch_delete_hit(rest, cwd):
            return "branch", argv
        if subcommand in ("checkout", "restore", "switch") and _discard_hit(subcommand, rest, cwd):
            return "discard", argv
        if subcommand == "stash" and _stash_drop_hit(rest, cwd):
            return "stash", argv
    return None


def check(command, cwd):
    """Dispatcher-facing predicate (#163): (command, cwd) -> full block message, or None.

    Seven of the eight predicates consult live repo state and fail open (are skipped, not blocked)
    when `cwd` can't be resolved, same contract as block-checkout-held-branch.py (#154) — but
    `_merge_publish_hit()` needs no repo state, so `cwd` being absent must not suppress it too;
    see `offending()`.
    """
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
        "rail: 'never force-push, merge/publish without confirmation, hard-delete, or do anything "
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
