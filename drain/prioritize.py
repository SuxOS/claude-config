"""Deterministic priority scoring and stable ordering of the drain plan.

Score is a plain weighted sum over normalized signals — higher drains first. Ties break
on the content-stable ``key`` so the ordering is fully reproducible across runs (no
timestamps, no dict-iteration surprises).
"""

from __future__ import annotations

from typing import List

from .record import WorkItem

# Priority-label weights (case-insensitive substring match, first hit wins).
_LABEL_WEIGHTS = (
    ("p0", 100),
    ("p1", 80),
    ("critical", 80),
    ("security", 70),
    ("bug", 40),
    ("p2", 30),
    ("enhancement", 20),
    ("p3", 10),
    ("p4", -20),
    ("later", -30),
)

# State weights — actionable work outranks review/blocked/waiting; terminal states sink.
_STATE_WEIGHTS = {
    "actionable": 50,
    "needs-review": 20,
    "requires-gate": 10,
    "blocked": 5,
    "waiting": 0,
    "unknown": -5,
    "completed": -100,
}


def _label_weight(item: WorkItem) -> int:
    hay = " ".join([item.priority_label or ""] + item.labels).lower()
    for needle, weight in _LABEL_WEIGHTS:
        if needle in hay:
            return weight
    return 0


def score(item: WorkItem) -> float:
    """Higher = drain sooner. Deterministic; depends only on normalized fields."""
    value = float(_STATE_WEIGHTS.get(item.classification, 0))
    value += float(_label_weight(item))
    # Blocker fan-in: an item other items depend on is worth clearing early.
    value += 5.0 * float(item.signals.get("blocks_count", 0))
    # A failing check on otherwise-actionable work is urgent.
    if item.signals.get("failed_check"):
        value += 15.0
    # Duplicates are cheap wins — nudge them up so the queue shrinks fast.
    if item.signals.get("duplicate"):
        value += 8.0
    # Age: mild pressure, capped so a stale P4 never outranks a fresh P0.
    if item.age_days:
        value += min(float(item.age_days) / 30.0, 10.0)
    return round(value, 3)


def prioritize(items: List[WorkItem]) -> List[WorkItem]:
    """Return a new list ordered by descending score, ties broken by key (stable)."""
    return sorted(items, key=lambda i: (-score(i), i.key))
