"""Mock adapter: a deterministic in-memory tracker backed by a JSON fixture.

Stands in for any unavailable integration and drives the test suite with no network. Its
``mutations`` list records every real change so tests can assert that dry-run mutates
nothing and that execute mutates exactly once per action (idempotency).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import ActionResult, Adapter, AdapterUnavailable


class MockAdapter(Adapter):
    name = "mock"

    def __init__(
        self,
        records: Optional[List[Dict[str, Any]]] = None,
        fixture_path: Optional[str] = None,
        unavailable: bool = False,
        raise_on_discover: bool = False,
    ) -> None:
        self._records = list(records or [])
        if fixture_path:
            with open(fixture_path, encoding="utf-8") as fh:
                self._records.extend(json.load(fh))
        self._unavailable = unavailable
        self._raise_on_discover = raise_on_discover
        self.mutations: List[Dict[str, Any]] = []
        # native_id -> current state, so close/relabel actually change observable state.
        self._state: Dict[str, Dict[str, Any]] = {
            str(r.get("native_id", r.get("id"))): dict(r) for r in self._records
        }

    def available(self) -> bool:
        return not self._unavailable

    def discover(self) -> List[Dict[str, Any]]:
        if self._unavailable:
            raise AdapterUnavailable("mock source configured unavailable")
        if self._raise_on_discover:
            raise RuntimeError("mock discover failure (for circuit-breaker tests)")
        # Return the *current* state so a re-audit after execute reflects mutations.
        out = []
        for rec in self._records:
            nid = str(rec.get("native_id", rec.get("id")))
            out.append(dict(self._state.get(nid, rec)))
        return out

    def act(self, item: Dict[str, Any], action: Dict[str, Any], execute: bool) -> ActionResult:
        kind = action.get("kind", "noop")
        nid = str(item.get("native_id", item.get("id")))
        if not execute:
            return ActionResult(ok=True, detail=f"[dry-run] would {kind} {nid}", mutated=False)
        state = self._state.setdefault(nid, dict(item))
        if kind == "close_with_evidence":
            state["status"] = "closed"
            state["signals"] = {**state.get("signals", {}), "closed": True}
            self.mutations.append({"kind": kind, "native_id": nid})
            return ActionResult(
                ok=True, detail=f"closed {nid}", mutated=True, evidence=str(action.get("comment", ""))
            )
        if kind == "remove_label":
            label = action.get("label")
            labels = [x for x in state.get("labels", []) if x != label]
            state["labels"] = labels
            self.mutations.append({"kind": kind, "native_id": nid, "label": label})
            return ActionResult(ok=True, detail=f"removed {label} from {nid}", mutated=True)
        if kind in ("comment", "relabel", "link", "prepare_patch", "retry_check"):
            self.mutations.append({"kind": kind, "native_id": nid})
            return ActionResult(ok=True, detail=f"{kind} on {nid}", mutated=True)
        # inspect / noop / run_check are non-mutating even in execute mode.
        return ActionResult(ok=True, detail=f"{kind} on {nid} (no mutation)", mutated=False)
