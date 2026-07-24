"""Adapter contract shared by every source."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class AdapterUnavailable(Exception):
    """Raised by discover()/act() when the underlying integration is unreachable.

    The engine catches this and degrades the source to 'skipped' with a reason — it never
    aborts the whole run (spec: "fail safely when an integration is unavailable").
    """


@dataclass
class ActionResult:
    ok: bool
    detail: str = ""
    evidence: Optional[str] = None
    mutated: bool = False  # True only if the source was actually changed
    extra: Dict[str, Any] = field(default_factory=dict)


class Adapter:
    """Base adapter. Subclasses override ``name``, ``discover``, and ``act``."""

    name = "base"

    def available(self) -> bool:
        """Cheap check whether the integration is reachable. Default: assume yes."""
        return True

    def discover(self) -> List[Dict[str, Any]]:
        """Return raw source records (dicts in the record.normalize input shape)."""
        raise NotImplementedError

    def act(self, item: Dict[str, Any], action: Dict[str, Any], execute: bool) -> ActionResult:
        """Perform ``action`` on ``item``.

        ``execute=False`` (dry-run) MUST NOT mutate the source — return a plan-only
        ActionResult with ``mutated=False``. ``execute=True`` may perform the action if
        it is an auto action (the engine never passes gated actions here).
        """
        raise NotImplementedError
