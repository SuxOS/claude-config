#!/usr/bin/env python3
"""
Detect git-level collisions across locally-cloned repos and worktrees:
work in multiple places that can step on itself.

This is the deterministic half of the "sessions stepping on each other" check.
The agent supplies the other half — live Claude Code session metadata from the
session-mgmt MCP (which sessions are running, in which cwd, on which branch) —
and correlates it with this git-level picture. A script can't see sessions;
it can see the git state those sessions leave behind.

Usage: session_collisions.py [root_dir]   (defaults to cwd)

Detects:
- same_branch_multiple_checkouts: one branch checked out in 2+ working trees
  (duplicate clones or worktrees both on `feature/x` — pushes will race)
- worktrees: registered `git worktree` entries per repo, with their branches
- diverged_active: branches both ahead AND behind origin (local and remote each
  moved — a force-push or a second writer)
- open_pr_with_local_edits: uncommitted or unpushed work sitting on a branch that
  already has an open PR (edits stranded outside the PR another session is driving)

Outputs JSON.
"""
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def run(cmd, cwd=None):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def remote_slug(path):
    url = run(["git", "remote", "get-url", "origin"], cwd=path)
    if not url or "github.com" not in url:
        return None
    tail = url.split("github.com")[-1].lstrip(":/")
    return tail[:-4] if tail.endswith(".git") else tail


def repo_dirs(root: Path):
    if (root / ".git").exists():
        return [root]
    return [c for c in sorted(root.iterdir()) if c.is_dir() and (c / ".git").exists()]


def worktrees(path):
    out = run(["git", "worktree", "list", "--porcelain"], cwd=path)
    trees = []
    cur = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if cur:
                trees.append(cur)
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "")
        elif line == "detached":
            cur["branch"] = "(detached)"
    if cur:
        trees.append(cur)
    return trees


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()

    # (slug, branch) -> list of checkout paths
    branch_checkouts = defaultdict(list)
    all_worktrees = {}
    diverged = []
    pr_edit_conflicts = []

    for path in repo_dirs(root):
        slug = remote_slug(path) or path.name
        trees = worktrees(path)
        all_worktrees[slug] = trees
        for t in trees:
            b = t.get("branch")
            if b and b != "(detached)":
                branch_checkouts[(slug, b)].append(t["path"])

        branch = run(["git", "branch", "--show-current"], cwd=path)
        if branch:
            ab = run(["git", "rev-list", "--left-right", "--count", f"{branch}...origin/{branch}"], cwd=path)
            if ab and "\t" in ab:
                a, b = ab.split("\t")
                a, b = int(a or 0), int(b or 0)
                if a > 0 and b > 0:
                    diverged.append({"repo": slug, "branch": branch, "ahead": a, "behind": b})

                status = run(["git", "status", "--porcelain"], cwd=path)
                dirty = bool(status.strip())
                if (dirty or a > 0):
                    pr = run(["gh", "pr", "list", "--repo", slug, "--head", branch,
                              "--state", "open", "--json", "number"], cwd=path)
                    try:
                        prs = json.loads(pr) if pr else []
                    except Exception:
                        prs = []
                    if prs:
                        pr_edit_conflicts.append({
                            "repo": slug, "branch": branch,
                            "pr": prs[0]["number"],
                            "uncommitted": dirty, "unpushed_commits": a,
                        })

    same_branch = {
        f"{slug}::{branch}": paths
        for (slug, branch), paths in branch_checkouts.items()
        if len(paths) > 1
    }

    print(json.dumps({
        "same_branch_multiple_checkouts": same_branch,
        "worktrees": all_worktrees,
        "diverged_active": diverged,
        "open_pr_with_local_edits": pr_edit_conflicts,
    }, indent=2))


if __name__ == "__main__":
    main()
