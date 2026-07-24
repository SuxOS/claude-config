"""GitHub adapter: discover issues/PRs/CI via the ``gh`` CLI and apply safe actions.

Discovery is read-only. Actions (comment / remove-label / close-with-evidence) run only in
execute mode and only for auto actions — gated actions never reach here. Idempotency is
enforced by a sentinel HTML comment embedded in every drain-authored comment: before
commenting or closing, the adapter checks whether the sentinel already exists.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .base import ActionResult, Adapter, AdapterUnavailable

SENTINEL = "<!-- drain:{key} -->"


def _gh(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)


class GitHubAdapter(Adapter):
    name = "github"

    def __init__(self, repos: Optional[List[str]] = None, limit: int = 200) -> None:
        # repos as "SuxOS/sux" slugs.
        self._repos = list(repos or [])
        self._limit = limit

    def available(self) -> bool:
        try:
            proc = _gh("auth", "status", timeout=10)
            return proc.returncode == 0
        except Exception:
            return False

    def discover(self) -> List[Dict[str, Any]]:
        if not self.available():
            raise AdapterUnavailable("gh not authenticated / not on PATH")
        out: List[Dict[str, Any]] = []
        for slug in self._repos:
            out.extend(self._discover_repo(slug))
        return out

    def _discover_repo(self, slug: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        proc = _gh(
            "issue", "list", "--repo", slug, "--state", "open", "--limit", str(self._limit),
            "--json", "number,title,labels,createdAt,updatedAt",
        )
        if proc.returncode != 0:
            raise AdapterUnavailable(f"gh issue list {slug}: {proc.stderr.strip()}")
        for row in json.loads(proc.stdout or "[]"):
            labels = [l["name"] for l in row.get("labels", [])]
            signals: Dict[str, Any] = {}
            if "needs-human" in labels:
                signals["needs_review"] = True
            items.append(
                {
                    "source": f"github:{slug}",
                    "native_id": str(row["number"]),
                    "title": row.get("title", ""),
                    "kind": "issue",
                    "status": "open",
                    "labels": labels,
                    "created_at": row.get("createdAt"),
                    "updated_at": row.get("updatedAt"),
                    "signals": signals,
                    "next_action": "triage",
                }
            )
        return items

    def _slug_and_number(self, item: Dict[str, Any]) -> Tuple[str, str]:
        slug = item.get("source", "github:").split(":", 1)[1]
        number = str(item.get("native_id"))
        return slug, number

    def _comment_has_sentinel(self, slug: str, number: str, key: str) -> bool:
        proc = _gh("issue", "view", number, "--repo", slug, "--json", "comments")
        if proc.returncode != 0:
            return False
        try:
            comments = json.loads(proc.stdout).get("comments", [])
        except Exception:
            return False
        needle = SENTINEL.format(key=key)
        return any(needle in (c.get("body", "")) for c in comments)

    def act(self, item: Dict[str, Any], action: Dict[str, Any], execute: bool) -> ActionResult:
        kind = action.get("kind", "noop")
        key = action.get("_key", "")
        slug, number = self._slug_and_number(item)
        if not execute:
            return ActionResult(ok=True, detail=f"[dry-run] would {kind} {slug}#{number}", mutated=False)

        sentinel = SENTINEL.format(key=key)

        if kind in ("comment", "close_with_evidence"):
            # Idempotency: skip if our sentinel is already on the issue.
            if key and self._comment_has_sentinel(slug, number, key):
                return ActionResult(ok=True, detail=f"{slug}#{number}: already applied", mutated=False)
            body = str(action.get("note") or action.get("comment") or "drain action") + "\n\n" + sentinel
            if kind == "close_with_evidence":
                proc = _gh("issue", "close", number, "--repo", slug, "--comment", body, "--reason", "not planned")
            else:
                proc = _gh("issue", "comment", number, "--repo", slug, "--body", body)
            ok = proc.returncode == 0
            return ActionResult(
                ok=ok,
                detail=(proc.stderr.strip() if not ok else f"{kind} {slug}#{number}"),
                mutated=ok,
                evidence=str(action.get("comment", "")),
            )

        if kind == "remove_label":
            label = str(action.get("label", ""))
            proc = _gh("issue", "edit", number, "--repo", slug, "--remove-label", label)
            ok = proc.returncode == 0
            return ActionResult(ok=ok, detail=f"remove {label} {slug}#{number}", mutated=ok)

        return ActionResult(ok=True, detail=f"{kind} {slug}#{number} (no mutation)", mutated=False)
