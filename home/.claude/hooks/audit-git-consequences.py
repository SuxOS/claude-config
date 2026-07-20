#!/usr/bin/env python3
"""PostToolUse hook (matcher: Bash) — flags a destructive git CONSEQUENCE the PreToolUse argv
rails in this directory (block-destructive-git.py and friends) missed, by diffing live git ref
state instead of trying to recognize a destructive COMMAND before it runs (#236).

Every PreToolUse(Bash) rail here is a text/argv heuristic — "a speed bump, not a seal"
(docs/security-model.md, hooks/README.md) — and a new tokenization/bundling/wrapper shape keeps
slipping past them (#105/#115/#119/#120/#121/#126/#129/#136/#144/#162/#193/#198/#200/#212/#214/
#217/#227). This hook is a different, complementary mechanism: it snapshots each git-repo cwd's
branch/remote-tracking ref tips (plus the HEAD pseudo-ref, for detached-HEAD work) at the END of
every Bash call — via the same git_out()/git_returncode() helpers every other rail uses — and
compares that snapshot to the one recorded after the PREVIOUS Bash call seen for the same repo
root. If a ref that pointed at a commit a moment ago now points somewhere that commit isn't
reachable from ANY current ref — or the ref is gone entirely — that commit was just discarded (a
force-push, a hard reset, an amend, a branch delete of unmerged work, ...) no matter how the
command that did it was spelled. Immune by construction to every bundling/wrapper/substitution
bypass class the argv rails keep individually patching — but NOT a block: PostToolUse fires after
the tool call already ran, so a hit here can only print a loud stderr warning (exit 2 feeds
stderr back to the model, same PostToolUse contract Claude Code uses elsewhere) — a last-resort
net behind the PreToolUse rails, not a replacement for them.

Fail-open on everything: an unreadable snapshot, a git subprocess quirk, a non-repo cwd, a state
file that can't be written — all degrade to "say nothing" (repo convention, same as every other
hook here), never to a crash or a false alarm. State lives outside this repo/the installed config
tree (tempfile.gettempdir()), keyed by a hash of the repo's real toplevel path so parallel
worktrees of the same repo — each with a distinct toplevel — never share a baseline.
"""
import hashlib
import json
import os
import sys
import tempfile

from _hookutil import git_out, git_returncode, load_hook_input

STATE_DIR = os.path.join(tempfile.gettempdir(), "claude-git-consequence-audit")


def _repo_root(cwd):
    if not cwd:
        return None
    root = git_out(["rev-parse", "--show-toplevel"], cwd)
    return root.strip() if root else None  # git_out is None (or empty) outside a work tree


def _snapshot(cwd):
    """Map every branch/remote-tracking ref, plus the HEAD pseudo-ref, to its current commit
    sha. None on any git failure — never a partial/misleading snapshot."""
    head = git_out(["rev-parse", "HEAD"], cwd)
    if head is None:
        return None
    snap = {"HEAD": head.strip()}
    out = git_out(
        ["for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads", "refs/remotes"],
        cwd,
    )
    if out is None:
        return None
    for line in out.splitlines():
        name, _, sha = line.partition(" ")
        if name and sha:
            snap[name] = sha
    return snap


def _state_path(root):
    digest = hashlib.sha256(root.encode()).hexdigest()
    return os.path.join(STATE_DIR, f"{digest}.json")


def _load_state(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _save_state(path, snapshot):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = f"{path}.tmp{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(snapshot, f)
        os.replace(tmp, path)
    except Exception:
        pass  # best-effort — a failed write only costs the NEXT call's baseline, never this one


def _reachable(sha, cwd):
    """True if `sha` is still an ancestor of some current branch/remote-tracking ref — i.e. still
    kept alive by a live ref, not just sitting unreferenced until git gc reaps it. None (not
    False) when the git subprocess itself failed — "couldn't tell" must never read as "discarded"
    (#343)."""
    out = git_out(["branch", "-a", "--contains", sha], cwd)
    if out is None:
        return None
    return bool(out.strip())


def _consequences(prev, current, cwd):
    messages = []
    for ref, old_sha in prev.items():
        new_sha = current.get(ref)
        if new_sha == old_sha:
            continue
        if new_sha is None:
            if _reachable(old_sha, cwd) is False:
                messages.append(
                    f"'{ref}' was removed and its tip commit {old_sha[:12]} is no longer "
                    "reachable from any branch — those commits look discarded"
                )
            continue
        # 0 = fast-forward (nothing lost). 1 = definitively not an ancestor. Anything else
        # (None from a failed subprocess, or a non-0/1 git exit like a pruned/missing object)
        # means "couldn't tell" and must not fall through to the alarm below (#339).
        if git_returncode(["merge-base", "--is-ancestor", old_sha, new_sha], cwd) != 1:
            continue
        if _reachable(old_sha, cwd) is False:
            messages.append(
                f"'{ref}' moved from {old_sha[:12]} to {new_sha[:12]} in a way that is not a "
                f"fast-forward, and {old_sha[:12]} is no longer reachable from any branch — "
                "those commits look discarded"
            )
    return messages


def main():
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)

    root = _repo_root(data.get("cwd") or None)
    if root is None:
        sys.exit(0)

    current = _snapshot(root)
    if current is None:
        sys.exit(0)

    path = _state_path(root)
    prev = _load_state(path)
    _save_state(path, current)
    if prev is None:
        sys.exit(0)  # first call seen for this repo — nothing to compare against yet

    messages = _consequences(prev, current, root)
    if not messages:
        sys.exit(0)

    print("audit-git-consequences: possible destructive git consequence detected:", file=sys.stderr)
    for m in messages:
        print(f"  - {m}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)  # fail open — a bug in this audit must never wedge the session
