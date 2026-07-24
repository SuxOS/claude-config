"""Local-git adapter: discover in-flight work in local clones.

Surfaces uncommitted working trees, local branches ahead of their upstream with no merged
PR (unmerged local work), and orphaned worktrees. Read-only by design — its ``act`` never
rewrites git history; auto actions record intent / prepare artifacts, and anything
destructive is gated upstream by policy.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional

from .base import ActionResult, Adapter, AdapterUnavailable


def _git(repo: str, *args: str, timeout: int = 20) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


class LocalGitAdapter(Adapter):
    name = "local"

    def __init__(self, repos: Optional[List[str]] = None, workspace_root: Optional[str] = None) -> None:
        self._repos = list(repos or [])
        self._root = os.path.expanduser(workspace_root) if workspace_root else None

    def _repo_paths(self) -> List[str]:
        if self._repos:
            return [os.path.expanduser(r) for r in self._repos]
        if self._root and os.path.isdir(self._root):
            out = []
            for name in sorted(os.listdir(self._root)):
                path = os.path.join(self._root, name)
                if os.path.isdir(os.path.join(path, ".git")):
                    out.append(path)
            return out
        return []

    def available(self) -> bool:
        try:
            subprocess.run(["git", "--version"], capture_output=True, timeout=5, check=True)
            return True
        except Exception:
            return False

    def discover(self) -> List[Dict[str, Any]]:
        if not self.available():
            raise AdapterUnavailable("git not available on PATH")
        out: List[Dict[str, Any]] = []
        for repo in self._repo_paths():
            name = os.path.basename(repo.rstrip("/"))
            try:
                out.extend(self._discover_repo(repo, name))
            except Exception as exc:  # one bad repo must not sink the source
                out.append(
                    {
                        "source": f"local:{name}",
                        "native_id": f"{name}:error",
                        "title": f"repo scan failed: {exc}",
                        "kind": "unknown",
                        "status": "unknown",
                        "signals": {"needs_review": True},
                    }
                )
        return out

    def _discover_repo(self, repo: str, name: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        # Uncommitted changes -> needs-review.
        dirty = _git(repo, "status", "--porcelain").strip()
        if dirty:
            items.append(
                {
                    "source": f"local:{name}",
                    "native_id": f"{name}:uncommitted",
                    "title": f"{name}: uncommitted changes ({len(dirty.splitlines())} files)",
                    "kind": "worktree",
                    "status": "dirty",
                    "signals": {"needs_review": True},
                    "evidence": dirty[:400],
                    "next_action": "review and commit or discard local changes",
                }
            )
        # Local branches ahead of upstream with no obvious merge.
        try:
            branches = _git(
                repo, "for-each-ref", "--format=%(refname:short) %(upstream:track)", "refs/heads/"
            ).splitlines()
        except Exception:
            branches = []
        for line in branches:
            parts = line.split(None, 1)
            branch = parts[0] if parts else ""
            track = parts[1] if len(parts) > 1 else ""
            if branch in ("main", "master") or not branch:
                continue
            if "ahead" in track:
                items.append(
                    {
                        "source": f"local:{name}",
                        "native_id": f"{name}:branch:{branch}",
                        "title": f"{name}: local branch '{branch}' has unpushed commits",
                        "kind": "branch",
                        "status": "ahead",
                        "signals": {"needs_review": True},
                        "next_action": "open a PR or land the branch",
                    }
                )
        # Orphaned worktrees (present on disk, not the main checkout).
        try:
            wt = _git(repo, "worktree", "list", "--porcelain")
        except Exception:
            wt = ""
        for block in wt.split("\n\n"):
            path = ""
            for l in block.splitlines():
                if l.startswith("worktree "):
                    path = l.split(" ", 1)[1]
            if path and os.path.realpath(path) != os.path.realpath(repo):
                items.append(
                    {
                        "source": f"local:{name}",
                        "native_id": f"{name}:worktree:{os.path.basename(path)}",
                        "title": f"{name}: extra worktree at {path}",
                        "kind": "worktree",
                        "status": "orphaned",
                        "signals": {"needs_review": True},
                        "next_action": "verify then remove the worktree if abandoned",
                    }
                )
        return items

    def act(self, item: Dict[str, Any], action: Dict[str, Any], execute: bool) -> ActionResult:
        # Local actions are non-destructive: record intent, never rewrite history here.
        kind = action.get("kind", "noop")
        nid = str(item.get("native_id", ""))
        return ActionResult(
            ok=True,
            detail=f"local {kind} on {nid} (intent recorded; no git mutation)",
            mutated=False,
        )
