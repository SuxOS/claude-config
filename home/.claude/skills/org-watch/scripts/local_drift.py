#!/usr/bin/env python3
"""
Scan immediate subdirectories of cwd for git-repo drift and thrashing,
and bidirectionally diff local clones against an org's repo list.

Usage: local_drift.py <org>

Outputs JSON:
{
  "repos": [
    {
      "name": "acme-corp/widgets",
      "path": "widgets",
      "branch": "main",
      "uncommitted_changes": 3,
      "untracked_files": 1,
      "ahead": 2,
      "behind": 0,
      "stale_branches": ["feature/old-thing"],   # local branches >30d untouched, unmerged
      "recent_force_pushes_or_resets": 4,         # reflog entries suggesting thrashing, last 7d
      "last_commit_days_ago": 0
    },
    ...
  ],
  "missing_local_clone": ["acme-corp/other-repo", ...],   # in org, no local dir
  "stray_local_clones": ["some-dir"]                       # local git dir not in org's repo list
}
"""
import json
import subprocess
import sys
import time
from pathlib import Path


def run(cmd, cwd=None):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def git_remote_owner_repo(path):
    url = run(["git", "remote", "get-url", "origin"], cwd=path)
    if not url or "github.com" not in url:
        return None
    tail = url.split("github.com")[-1].lstrip(":/")
    tail = tail[:-4] if tail.endswith(".git") else tail
    parts = tail.split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return None


def analyze_repo(path: Path):
    branch = run(["git", "branch", "--show-current"], cwd=path) or "HEAD"
    status = run(["git", "status", "--porcelain"], cwd=path)
    uncommitted = len([l for l in status.splitlines() if l and not l.startswith("??")])
    untracked = len([l for l in status.splitlines() if l.startswith("??")])

    ahead_behind = run(["git", "rev-list", "--left-right", "--count", f"{branch}...origin/{branch}"], cwd=path)
    ahead, behind = 0, 0
    if ahead_behind and "\t" in ahead_behind:
        a, b = ahead_behind.split("\t")
        ahead, behind = int(a or 0), int(b or 0)

    last_commit_ts = run(["git", "log", "-1", "--format=%ct"], cwd=path)
    last_commit_days_ago = None
    if last_commit_ts.isdigit():
        last_commit_days_ago = int((time.time() - int(last_commit_ts)) / 86400)

    branches = run(["git", "for-each-ref", "--format=%(refname:short) %(committerdate:unix)", "refs/heads/"], cwd=path)
    stale_branches = []
    now = time.time()
    for line in branches.splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        bname, ts = parts[0], int(parts[1])
        if bname == branch:
            continue
        age_days = (now - ts) / 86400
        merged = run(["git", "branch", "--merged", branch], cwd=path)
        if age_days > 30 and bname not in merged:
            stale_branches.append(bname)

    reflog = run(["git", "reflog", "--date=unix", "-50"], cwd=path)
    cutoff = now - 7 * 86400
    thrash_count = 0
    for line in reflog.splitlines():
        if "reset:" in line or "forced-update" in line or "rebase" in line:
            thrash_count += 1

    return {
        "branch": branch,
        "uncommitted_changes": uncommitted,
        "untracked_files": untracked,
        "ahead": ahead,
        "behind": behind,
        "stale_branches": stale_branches,
        "recent_force_pushes_or_resets": thrash_count,
        "last_commit_days_ago": last_commit_days_ago,
    }


def org_repo_list(org):
    out = run(["gh", "repo", "list", org, "--limit", "1000", "--json", "name"])
    if not out:
        return []
    try:
        return [f"{org}/{r['name']}" for r in json.loads(out)]
    except Exception:
        return []


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: local_drift.py <org>"}))
        sys.exit(1)
    org = sys.argv[1]
    cwd = Path.cwd()

    local_repos = {}
    for child in sorted(cwd.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        remote_name = git_remote_owner_repo(child) or child.name
        local_repos[remote_name] = child

    results = []
    for name, path in local_repos.items():
        info = analyze_repo(path)
        info["name"] = name
        info["path"] = str(path.relative_to(cwd))
        results.append(info)

    org_repos = set(org_repo_list(org))
    local_names = set(local_repos.keys())

    missing = sorted(org_repos - local_names) if org_repos else []
    stray = sorted(n for n in local_names if org_repos and n not in org_repos)

    print(json.dumps({
        "repos": results,
        "missing_local_clone": missing,
        "stray_local_clones": stray,
    }, indent=2))


if __name__ == "__main__":
    main()
