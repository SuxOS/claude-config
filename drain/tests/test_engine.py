from __future__ import annotations

import os
import tempfile
import unittest

from drain.adapters.mock import MockAdapter
from drain.audit_log import AuditLog
from drain.engine import Engine

from .helpers import load_fixture, now


def _log():
    d = tempfile.mkdtemp()
    return AuditLog(os.path.join(d, "audit.jsonl"), now=now)


def _engine(adapter, mode, log=None, **kw):
    return Engine(
        adapters=[adapter],
        audit_log=log or _log(),
        mode=mode,
        now=now,
        sleep=lambda _: None,
        **kw,
    )


class TestAuditMode(unittest.TestCase):
    def test_read_only_no_mutations(self) -> None:
        adapter = MockAdapter(records=load_fixture("mock_tracker.json"))
        result = _engine(adapter, "audit").run()
        self.assertEqual(adapter.mutations, [])
        self.assertEqual(result.actions, [])
        self.assertEqual(result.discovered, 10)
        self.assertEqual(result.by_state.get("requires-gate"), 1)
        self.assertEqual(result.by_state.get("completed"), 1)


class TestPlanMode(unittest.TestCase):
    def test_dry_run_records_plans_without_mutation(self) -> None:
        adapter = MockAdapter(records=load_fixture("mock_tracker.json"))
        result = _engine(adapter, "plan").run()
        self.assertEqual(adapter.mutations, [])  # dry-run mutates nothing
        self.assertTrue(len(result.actions) > 0)
        self.assertFalse(result.drained)


class TestRunMode(unittest.TestCase):
    def test_executes_and_gates_and_completes(self) -> None:
        adapter = MockAdapter(records=load_fixture("mock_tracker.json"))
        result = _engine(adapter, "run").run()
        # Real mutations happened (D1 close, L1 remove_label, A1 prepare_patch, ...).
        kinds = {m["kind"] for m in adapter.mutations}
        self.assertIn("close_with_evidence", kinds)
        self.assertIn("remove_label", kinds)
        # Gated item emitted, never executed.
        self.assertEqual(len(result.gates), 1)
        self.assertTrue(result.gates[0]["gate"].startswith("[GATE:"))
        self.assertNotIn("force_push", {m["kind"] for m in adapter.mutations})
        # Completed item surfaced; drain reached completion.
        self.assertTrue(any(c["title"] == "already closed" for c in result.completed))
        self.assertTrue(result.drained)

    def test_idempotent_across_runs(self) -> None:
        log = _log()
        records = load_fixture("mock_tracker.json")
        first = MockAdapter(records=records)
        _engine(first, "run", log=log).run()
        n_first = len(first.mutations)
        self.assertGreater(n_first, 0)
        # Second run, same log, fresh adapter -> everything already applied -> no mutation.
        second = MockAdapter(records=records)
        _engine(second, "run", log=log).run()
        self.assertEqual(second.mutations, [])

    def test_completion_requires_evidence(self) -> None:
        # Duplicate/high-confidence but NO evidence text -> close is skipped, flagged review.
        rec = {"source": "mock", "native_id": "NOEV", "title": "dup no evidence",
               "status": "open", "signals": {"duplicate": True, "confidence": "high", "has_evidence": True}}
        adapter = MockAdapter(records=[rec])
        result = _engine(adapter, "run").run()
        self.assertEqual(adapter.mutations, [])  # nothing closed without evidence
        self.assertTrue(any(a.get("action") == "needs-review" for a in result.actions))


class TestFailSafe(unittest.TestCase):
    def test_unavailable_adapter_is_skipped_not_fatal(self) -> None:
        adapter = MockAdapter(records=[], unavailable=True)
        result = _engine(adapter, "run").run()
        self.assertEqual(result.discovered, 0)
        self.assertTrue(any(s["source"] == "mock" for s in result.skipped_sources))

    def test_discover_error_trips_breaker_and_skips(self) -> None:
        adapter = MockAdapter(records=[{"source": "mock", "native_id": "x"}], raise_on_discover=True)
        result = _engine(adapter, "run", retries=1, breaker_threshold=1).run()
        self.assertTrue(any(s["source"] == "mock" for s in result.skipped_sources))
        self.assertEqual(result.discovered, 0)  # no crash, just empty


if __name__ == "__main__":
    unittest.main()
