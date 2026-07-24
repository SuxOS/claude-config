"""The orchestrator loop: discover -> normalize -> classify -> prioritize -> act -> verify
-> re-audit, with the spec's non-functionals baked in.

Three modes:
  * ``audit``  (read-only): discover + classify + report. Never plans or mutates.
  * ``plan``   (dry-run):   also prioritizes and asks each adapter what it *would* do,
                            with ``execute=False`` so nothing mutates.
  * ``run``    (execute):   performs auto actions (retry+backoff, per-source circuit
                            breaker, idempotent via the audit log + adapter sentinels),
                            emits gated actions as ``[GATE: ...]``, verifies claimed
                            completions carry evidence, and re-audits until drained.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from . import classify as _classify
from . import policy as _policy
from . import prioritize as _prioritize
from . import record as _record
from .adapters.base import Adapter, AdapterUnavailable
from .audit_log import AuditLog
from .runtime import CircuitBreaker, RetryError, run_with_retry

MODES = ("audit", "plan", "run")


@dataclass
class DrainResult:
    mode: str
    rounds: int = 0
    discovered: int = 0
    by_state: Dict[str, int] = field(default_factory=dict)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    gates: List[Dict[str, Any]] = field(default_factory=list)
    skipped_sources: List[Dict[str, str]] = field(default_factory=list)
    completed: List[Dict[str, Any]] = field(default_factory=list)
    remaining: List[Dict[str, Any]] = field(default_factory=list)
    drained: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "rounds": self.rounds,
            "discovered": self.discovered,
            "by_state": self.by_state,
            "actions": self.actions,
            "gates": self.gates,
            "skipped_sources": self.skipped_sources,
            "completed": self.completed,
            "remaining": self.remaining,
            "drained": self.drained,
        }


class Engine:
    def __init__(
        self,
        adapters: List[Adapter],
        audit_log: AuditLog,
        mode: str = "audit",
        max_rounds: int = 3,
        limit: Optional[int] = None,
        retries: int = 2,
        backoff_base: float = 0.2,
        breaker_threshold: int = 3,
        concurrency: int = 4,
        now: Optional[Callable[[], datetime]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        assert mode in MODES, f"mode must be one of {MODES}"
        self.adapters = adapters
        self.log = audit_log
        self.mode = mode
        self.max_rounds = max_rounds
        self.limit = limit
        self.retries = retries
        self.backoff_base = backoff_base
        self.breaker = CircuitBreaker(breaker_threshold)
        self.concurrency = max(1, concurrency)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep  # None -> real time.sleep inside run_with_retry

    # ---- discovery (fail-safe, concurrent, breaker-guarded) -------------------------

    def _discover_one(self, adapter: Adapter) -> Dict[str, Any]:
        source = adapter.name
        if self.breaker.is_open(source):
            return {"source": source, "raw": [], "skipped": "circuit breaker open"}
        try:
            if not adapter.available():
                self.breaker.record_fail(source)
                return {"source": source, "raw": [], "skipped": "adapter unavailable"}
            raw = run_with_retry(
                adapter.discover,
                retries=self.retries,
                backoff_base=self.backoff_base,
                sleep=self._sleep,
            )
            self.breaker.record_ok(source)
            return {"source": source, "raw": raw, "skipped": None}
        except (AdapterUnavailable, RetryError) as exc:
            self.breaker.record_fail(source)
            return {"source": source, "raw": [], "skipped": str(exc)}
        except Exception as exc:  # never let one source abort the run
            self.breaker.record_fail(source)
            return {"source": source, "raw": [], "skipped": f"error: {exc}"}

    def _discover_all(self, result: DrainResult) -> List[_record.WorkItem]:
        raw_records: List[Dict[str, Any]] = []
        seen_skips = {s["source"] for s in result.skipped_sources}
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            for out in pool.map(self._discover_one, self.adapters):
                if out["skipped"]:
                    if out["source"] not in seen_skips:
                        result.skipped_sources.append(
                            {"source": out["source"], "reason": out["skipped"]}
                        )
                        seen_skips.add(out["source"])
                    continue
                raw_records.extend(out["raw"])
        # Normalize + dedup by content key (first occurrence wins).
        now = self._now()
        items: Dict[str, _record.WorkItem] = {}
        for raw in raw_records:
            item = _record.normalize(raw, now)
            items.setdefault(item.key, item)
        return list(items.values())

    def _adapter_for(self, item: _record.WorkItem) -> Optional[Adapter]:
        src = item.source.split(":", 1)[0]
        for a in self.adapters:
            if a.name == src or a.name == item.source:
                return a
        return self.adapters[0] if self.adapters else None

    # ---- the loop -------------------------------------------------------------------

    def run(self) -> DrainResult:
        result = DrainResult(mode=self.mode)
        acted: set = set(self.log.seen_keys())  # (key, action) already applied historically
        rounds = self.max_rounds if self.mode == "run" else 1

        last_items: List[_record.WorkItem] = []
        for round_no in range(1, rounds + 1):
            result.rounds = round_no
            items = _classify.classify_all(self._discover_all(result))
            items = _prioritize.prioritize(items)
            last_items = items
            if self.limit is not None:
                items = items[: self.limit]

            progressed = False
            for item in items:
                action = _policy.plan_action(item)
                action.params["_key"] = item.key

                if item.classification == "completed":
                    if item.key not in {c["key"] for c in result.completed}:
                        result.completed.append(
                            {"key": item.key, "title": item.title, "source": item.source}
                        )
                    continue

                if self.mode == "audit":
                    continue  # classification only

                if action.gated:
                    self._emit_gate(result, item, action)
                    continue

                if self.mode == "plan":
                    self._record_plan(result, item, action)
                    continue

                # execute mode
                if (item.key, action.kind) in acted:
                    continue  # idempotent: already applied
                if self._execute(result, item, action):
                    acted.add((item.key, action.kind))
                    progressed = True

            # completion: no un-acted actionable items remain
            remaining_actionable = [
                i for i in last_items
                if i.classification == "actionable"
                and (i.key, _policy.plan_action(i).kind) not in acted
            ]
            if self.mode != "run" or not remaining_actionable:
                result.drained = self.mode == "run" and not remaining_actionable
                break
            if not progressed:
                break

        self._finalize(result, last_items, acted)
        return result

    # ---- per-item handlers ----------------------------------------------------------

    def _emit_gate(self, result: DrainResult, item: _record.WorkItem, action: _policy.Action) -> None:
        gate = {
            "key": item.key,
            "title": item.title,
            "source": item.source,
            "gate": action.gate_line(),
            "reason": action.gate_reason,
        }
        if item.key not in {g["key"] for g in result.gates}:
            result.gates.append(gate)
        self.log.append(
            {"event": "gate", "key": item.key, "source": item.source, "gate": action.gate_line()}
        )

    def _record_plan(self, result: DrainResult, item: _record.WorkItem, action: _policy.Action) -> None:
        adapter = self._adapter_for(item)
        detail = ""
        if adapter is not None:
            res = adapter.act(item.raw, {"kind": action.kind, **action.params}, execute=False)
            detail = res.detail
            assert not res.mutated, "dry-run must not mutate"
        entry = {
            "event": "plan",
            "key": item.key,
            "source": item.source,
            "action": action.kind,
            "classification": item.classification,
            "detail": detail,
        }
        result.actions.append(entry)
        self.log.append(entry)

    def _execute(self, result: DrainResult, item: _record.WorkItem, action: _policy.Action) -> bool:
        adapter = self._adapter_for(item)
        if adapter is None:
            return False

        # Verification gate: a completion action must carry evidence.
        if action.kind == "close_with_evidence" and not (action.params.get("comment") or item.evidence):
            self.log.append(
                {"event": "action", "key": item.key, "action": action.kind,
                 "result": "skipped", "reason": "no evidence for claimed completion"}
            )
            result.actions.append(
                {"key": item.key, "action": "needs-review", "source": item.source,
                 "detail": "completion claimed without evidence — not closed"}
            )
            return False

        source = item.source.split(":", 1)[0]
        if self.breaker.is_open(source):
            return False
        try:
            res = run_with_retry(
                lambda: adapter.act(item.raw, {"kind": action.kind, **action.params}, execute=True),
                retries=self.retries,
                backoff_base=self.backoff_base,
                sleep=self._sleep,
            )
        except RetryError as exc:
            self.breaker.record_fail(source)
            self.log.append(
                {"event": "action", "key": item.key, "action": action.kind,
                 "result": "error", "detail": str(exc)}
            )
            return False

        self.breaker.record_ok(source) if res.ok else self.breaker.record_fail(source)
        entry = {
            "event": "action",
            "key": item.key,
            "source": item.source,
            "action": action.kind,
            "result": "ok" if res.ok else "error",
            "mutated": res.mutated,
            "detail": res.detail,
            "evidence": res.evidence,
        }
        result.actions.append(entry)
        self.log.append(entry)
        return res.ok

    def _finalize(self, result: DrainResult, items: List[_record.WorkItem], acted: set) -> None:
        by_state: Dict[str, int] = {}
        for item in items:
            by_state[item.classification] = by_state.get(item.classification, 0) + 1
        result.by_state = by_state
        result.discovered = len(items)
        # Remaining = anything not terminally resolved, with its precise blocker.
        for item in items:
            if item.classification == "completed":
                continue
            if item.classification == "actionable" and (item.key, _policy.plan_action(item).kind) in acted:
                continue
            result.remaining.append(
                {
                    "key": item.key,
                    "title": item.title,
                    "source": item.source,
                    "state": item.classification,
                    "blocker": self._blocker(item),
                }
            )

    @staticmethod
    def _blocker(item: _record.WorkItem) -> str:
        if item.classification == "requires-gate":
            return str(item.signals.get("gate_reason", "gated action"))
        if item.classification == "blocked":
            if item.dependencies:
                return "depends on " + ", ".join(item.dependencies)
            return "failing check: " + str(item.signals.get("check", "unknown"))
        if item.classification == "waiting":
            return "waiting on external signal"
        if item.classification == "needs-review":
            return "needs review / decision"
        return item.classification
