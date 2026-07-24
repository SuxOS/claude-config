"""Deterministic classification of a WorkItem into one of the seven states.

This is the heart of the "deterministic beats LLM" principle (Cardinal #2): classification
is a fixed, ordered set of predicates over normalized fields — no model call, fully
reproducible, cheap, and unit-testable. An optional LLM enricher may pre-populate
``signals`` upstream, but it is off by default and never used in the test path.

Rule order matters — the FIRST matching predicate wins, and the order is
conservative-by-construction: a gate beats everything (never auto-act on a gated item),
an unverified-completion beats a raw closed status (force human/evidence review before
trusting "done"), and only concrete next-actionable items fall through to ``actionable``.
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from .record import WorkItem

_CLOSED_STATUSES = {"closed", "merged", "done", "resolved", "completed"}
_ACTIONABLE_CONFIDENCE = {"high", "medium"}


def _has_evidence(item: WorkItem) -> bool:
    return bool(item.evidence) or bool(item.signals.get("has_evidence"))


# Each rule is (name, predicate) -> returns the state if it fires, else None is implied
# by the predicate returning False. Ordered; first True wins.
def _rules() -> List[Tuple[str, Callable[[WorkItem], bool]]]:
    return [
        ("requires-gate", lambda i: bool(i.signals.get("gated"))),
        (
            "needs-review",
            lambda i: bool(i.signals.get("completed_unverified")) and not _has_evidence(i),
        ),
        (
            "completed",
            lambda i: bool(i.signals.get("merged"))
            or bool(i.signals.get("closed"))
            or i.status.lower() in _CLOSED_STATUSES,
        ),
        ("needs-review", lambda i: bool(i.signals.get("contradictory"))),
        (
            "blocked",
            lambda i: bool(i.signals.get("failed_check"))
            or bool(i.signals.get("dependencies_open"))
            or bool(i.dependencies),
        ),
        ("waiting", lambda i: bool(i.signals.get("waiting_external"))),
        (
            "needs-review",
            lambda i: bool(i.signals.get("needs_review"))
            or bool(i.signals.get("unreviewed_pr")),
        ),
        # duplicate/stale with solid evidence is a concrete close action; without
        # evidence (or low confidence) it needs a human/second look first.
        (
            "actionable",
            lambda i: (bool(i.signals.get("duplicate")) or bool(i.signals.get("stale")))
            and _has_evidence(i)
            and i.signals.get("confidence", "high") in _ACTIONABLE_CONFIDENCE,
        ),
        (
            "needs-review",
            lambda i: bool(i.signals.get("duplicate")) or bool(i.signals.get("stale")),
        ),
        ("actionable", lambda i: bool(i.next_action)),
    ]


def classify(item: WorkItem) -> str:
    """Return the item's state. Pure function of the item's normalized fields."""
    for state, predicate in _rules():
        try:
            if predicate(item):
                return state
        except Exception:
            # A predicate must never crash the run; an unreasoned item is 'unknown'.
            continue
    return "unknown"


def classify_all(items: List[WorkItem]) -> List[WorkItem]:
    """Classify in place and return the same list (convenience for the engine)."""
    for item in items:
        item.classification = classify(item)
    return items
