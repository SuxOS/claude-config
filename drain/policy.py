"""Action policy: the safety spine.

Given a classified WorkItem, derive the single next action and decide whether it is
**auto** (safe + reversible + idempotent — executed in ``run`` mode) or **gated**
(destructive / privileged / irreversible / externally-consequential — NEVER executed,
emitted as a ``[GATE: ...]``). The gate set is closed and conservative: anything not
provably safe is gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .record import WorkItem

# Safe, reversible, idempotent action kinds — allowed in execute mode.
AUTO_ACTIONS = frozenset(
    {
        "inspect",  # read code/logs, no mutation
        "run_check",  # run a read-only validation
        "retry_check",  # re-trigger an idempotent check
        "prepare_patch",  # write a patch to a file (not pushed)
        "comment",  # add/refresh an idempotent issue comment (records a decision)
        "relabel",  # add a label
        "remove_label",  # remove a label (e.g. clear needs-human so the pipeline selects it)
        "link",  # link related items / add evidence reference
        "close_with_evidence",  # close an issue WITH evidence (reversible: reopen)
        "noop",  # nothing to do (waiting/monitor)
    }
)

# Destructive / privileged / irreversible / consequential — always gated.
GATED_ACTIONS = frozenset(
    {
        "delete",  # delete data / branch / file
        "force_push",  # history rewrite
        "merge",  # merge a PR (irreversible-ish, and hook-blocked here anyway)
        "rotate_secret",
        "deploy",  # production change
        "pay",  # financial
        "sign",  # legal signature
        "grant_permission",  # permission/security change
    }
)


@dataclass
class Action:
    kind: str
    params: Dict[str, object]
    gated: bool
    gate_reason: Optional[str] = None

    def gate_line(self) -> Optional[str]:
        """The exact ``[GATE: ...]`` marker for a gated action, per the mandate format."""
        if not self.gated:
            return None
        what = self.gate_reason or self.kind
        return f"[GATE: {what} — assumed safest placeholder prepared, revisit]"


def _gate(kind: str, reason: str, **params: object) -> Action:
    return Action(kind=kind, params=params, gated=True, gate_reason=reason)


def _auto(kind: str, **params: object) -> Action:
    assert kind in AUTO_ACTIONS, f"{kind} is not an auto action"
    return Action(kind=kind, params=params, gated=False)


def plan_action(item: WorkItem) -> Action:
    """Derive the next action for a classified item. Deterministic and total."""
    signals = item.signals
    cls = item.classification

    # A gated classification, or any explicit gated signal, produces a gated action.
    if cls == "requires-gate" or signals.get("gated"):
        reason = str(signals.get("gate_reason") or "privileged/irreversible action required")
        requested = str(signals.get("gate_action", "gated_action"))
        return _gate(requested if requested in GATED_ACTIONS else "gated_action", reason)

    if cls == "completed":
        return _auto("noop", note="already terminal")

    if cls == "actionable":
        # Duplicate / stale with evidence -> close it (reversible).
        if signals.get("duplicate") or signals.get("stale"):
            return _auto(
                "close_with_evidence",
                superseded_by=signals.get("superseded_by", ""),
                comment=item.evidence or "",
            )
        # Clear a needs-human-style gate label so the build pipeline can select it.
        gate_label = signals.get("clear_label")
        if gate_label:
            return _auto("remove_label", label=str(gate_label))
        # Otherwise the concrete next_action string drives an inspect/patch cycle.
        return _auto("prepare_patch", next_action=item.next_action or "")

    if cls == "blocked":
        # A failed idempotent check is worth one retry; otherwise document the blocker.
        if signals.get("failed_check") and signals.get("idempotent_check"):
            return _auto("retry_check", check=str(signals.get("check", "")))
        return _auto("comment", note="blocked: " + _blocker_text(item))

    if cls == "needs-review":
        # No human in the loop -> record the decision/flag as a comment (auto, reversible).
        return _auto("comment", note="needs-review: " + (item.next_action or "flagged"))

    if cls == "waiting":
        return _auto("noop", note="waiting on external signal")

    # unknown
    return _auto("inspect", note="unclassified — inspect for a next action")


def _blocker_text(item: WorkItem) -> str:
    if item.dependencies:
        return "depends on " + ", ".join(item.dependencies)
    if item.signals.get("failed_check"):
        return "failing check: " + str(item.signals.get("check", "unknown"))
    return "unresolved dependency"
