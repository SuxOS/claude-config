"""The normalized WorkItem record and the raw -> normalized transform.

Every adapter emits *raw* dicts in a documented shape; ``normalize`` turns one into a
``WorkItem`` with a content-stable dedup ``key``, a computed ``age_days``, and an empty
classification (filled later by classify.py). Nothing here reaches the network or the
clock except through the injected ``now`` — so normalization is pure and testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# The canonical classification states (spec §Functional / state machine).
STATES = (
    "actionable",
    "blocked",
    "waiting",
    "needs-review",
    "completed",
    "requires-gate",
    "unknown",
)


@dataclass
class WorkItem:
    """One normalized unit of in-flight work, source-agnostic."""

    source: str  # e.g. "github:SuxOS/sux", "local:sux", "mock"
    native_id: str  # id within the source (issue number, branch name, ...)
    title: str
    kind: str  # issue | pr | branch | worktree | todo | check
    status: str  # raw source status token (open/closed/merged/dirty/failing/...)
    key: str  # content-stable dedup key: sha1(source:native_id)
    owner: Optional[str] = None
    priority_label: Optional[str] = None
    created_at: Optional[str] = None  # ISO-8601
    updated_at: Optional[str] = None  # ISO-8601
    age_days: Optional[float] = None
    labels: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    evidence: Optional[str] = None
    signals: Dict[str, Any] = field(default_factory=dict)
    next_action: Optional[str] = None
    classification: str = "unknown"
    last_audit: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "native_id": self.native_id,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "key": self.key,
            "owner": self.owner,
            "priority_label": self.priority_label,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "age_days": self.age_days,
            "labels": list(self.labels),
            "dependencies": list(self.dependencies),
            "evidence": self.evidence,
            "signals": dict(self.signals),
            "next_action": self.next_action,
            "classification": self.classification,
            "last_audit": self.last_audit,
        }


def make_key(source: str, native_id: str) -> str:
    """Stable dedup key from identity only — never from mutable fields or time."""
    return hashlib.sha1(f"{source}:{native_id}".encode("utf-8")).hexdigest()[:16]


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_days(created_at: Optional[str], now: datetime) -> Optional[float]:
    created = _parse_iso(created_at)
    if created is None:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - created
    return round(delta.total_seconds() / 86400.0, 3)


def normalize(raw: Dict[str, Any], now: datetime) -> WorkItem:
    """Convert one adapter raw record into a WorkItem.

    Missing fields degrade to conservative defaults; a malformed record never raises —
    at worst it becomes an ``unknown``-kind item the classifier can reason about.
    """
    source = str(raw.get("source", "unknown"))
    native_id = str(raw.get("native_id", raw.get("id", "")))
    signals = dict(raw.get("signals", {}))
    evidence = raw.get("evidence")
    # A non-empty evidence field is itself a signal the classifier consults.
    if evidence:
        signals.setdefault("has_evidence", True)
    return WorkItem(
        source=source,
        native_id=native_id,
        title=str(raw.get("title", "")),
        kind=str(raw.get("kind", "unknown")),
        status=str(raw.get("status", "unknown")),
        key=make_key(source, native_id),
        owner=raw.get("owner"),
        priority_label=raw.get("priority_label"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        age_days=_age_days(raw.get("created_at"), now),
        labels=list(raw.get("labels", [])),
        dependencies=list(raw.get("dependencies", [])),
        evidence=evidence,
        signals=signals,
        next_action=raw.get("next_action"),
        last_audit=now.isoformat(),
        raw=dict(raw),
    )
