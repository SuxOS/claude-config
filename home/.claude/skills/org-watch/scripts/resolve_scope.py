#!/usr/bin/env python3
"""
Resolve an org-watch scope argument into a concrete org + repo list.

Scope syntax (space-separated, any mix, order-free):
  (none)          -> infer org from cwd (see below), scan all its repos
  org:<name>       -> explicit org, scan all its repos (ignores cwd)
  repo:<name>      -> single repo, org inferred from cwd
  repo:<owner>/<name> -> single repo, explicit owner
  Multiple tokens combine (union of repos).

Org inference from cwd (in priority order):
  1. If cwd itself is a git repo, use its remote's owner as the org
     and scope to just that one repo (a "repo" invocation, not "org").
  2. Else, scan immediate subdirectories that are git repos, read each
     remote's owner, and take the most common owner as the org.
  3. Else, fall back to the cwd directory's basename as the org name.

Outputs JSON: {"org": str|null, "repos": [str,...]|null, "mode": "org"|"repo"|"mixed", "inferred": bool}
"repos": null means "all repos in org" (caller should gh repo list).
"""
import json
import subprocess
import sys
from pathlib import Path
from collections import Counter


def git_remote_owner(path):
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        url = out.stdout.strip()
        # git@github.com:owner/repo.git  or  https://github.com/owner/repo.git
        if "github.com" not in url:
            return None
        tail = url.split("github.com")[-1].lstrip(":/")
        tail = tail[:-4] if tail.endswith(".git") else tail
        parts = tail.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    except Exception:
        return None
    return None


def is_git_repo(path):
    return (path / ".git").exists()


def infer_scope(cwd: Path):
    if is_git_repo(cwd):
        owner_repo = git_remote_owner(cwd)
        if owner_repo:
            owner, repo = owner_repo
            return {"org": owner, "repos": [f"{owner}/{repo}"], "mode": "repo", "inferred": True}
        return {"org": cwd.name, "repos": [cwd.name], "mode": "repo", "inferred": True}

    owners = []
    for child in sorted(cwd.iterdir()):
        if child.is_dir() and is_git_repo(child):
            owner_repo = git_remote_owner(child)
            if owner_repo:
                owners.append(owner_repo[0])
    if owners:
        org = Counter(owners).most_common(1)[0][0]
        return {"org": org, "repos": None, "mode": "org", "inferred": True}

    return {"org": cwd.name, "repos": None, "mode": "org", "inferred": True}


def main():
    tokens = sys.argv[1:]
    cwd = Path.cwd()

    if not tokens:
        print(json.dumps(infer_scope(cwd)))
        return

    org = None
    repos = []
    for tok in tokens:
        if tok.startswith("org:"):
            org = tok[len("org:"):]
        elif tok.startswith("repo:"):
            val = tok[len("repo:"):]
            if "/" in val:
                repos.append(val)
            else:
                base = infer_scope(cwd)
                inferred_org = org or base["org"]
                repos.append(f"{inferred_org}/{val}")

    if repos and not org:
        # derive org from the repos if all share one owner, else leave org unset (mixed)
        owners = {r.split("/")[0] for r in repos}
        org = owners.pop() if len(owners) == 1 else None

    mode = "repo" if repos and not (org and not repos) else ("org" if org and not repos else "mixed")
    print(json.dumps({"org": org, "repos": repos or None, "mode": mode, "inferred": False}))


if __name__ == "__main__":
    main()
