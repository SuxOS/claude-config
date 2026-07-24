from __future__ import annotations

import unittest

from drain.classify import classify
from drain.policy import AUTO_ACTIONS, GATED_ACTIONS, plan_action
from drain.record import normalize

from .helpers import NOW, load_fixture


def _classified(raw):
    item = normalize(raw, NOW)
    item.classification = classify(item)
    return item


class TestPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.items = {r["native_id"]: _classified(r) for r in load_fixture("mock_tracker.json")}

    def test_duplicate_closes_with_evidence(self) -> None:
        action = plan_action(self.items["D1"])
        self.assertEqual(action.kind, "close_with_evidence")
        self.assertFalse(action.gated)
        self.assertIn(action.kind, AUTO_ACTIONS)

    def test_clear_label_removes_label(self) -> None:
        action = plan_action(self.items["L1"])
        self.assertEqual(action.kind, "remove_label")
        self.assertEqual(action.params.get("label"), "needs-human")

    def test_gated_item_is_gated(self) -> None:
        action = plan_action(self.items["G1"])
        self.assertTrue(action.gated)
        self.assertIn(action.kind, GATED_ACTIONS)
        line = action.gate_line()
        self.assertTrue(line.startswith("[GATE:"))
        self.assertIn("force-push", line)

    def test_failed_idempotent_check_retries(self) -> None:
        self.assertEqual(plan_action(self.items["B2"]).kind, "retry_check")

    def test_blocked_dependency_comments(self) -> None:
        self.assertEqual(plan_action(self.items["B1"]).kind, "comment")

    def test_needs_review_comments(self) -> None:
        self.assertEqual(plan_action(self.items["R1"]).kind, "comment")

    def test_waiting_noop(self) -> None:
        self.assertEqual(plan_action(self.items["W1"]).kind, "noop")

    def test_no_gated_action_in_auto_set(self) -> None:
        self.assertEqual(AUTO_ACTIONS & GATED_ACTIONS, frozenset())


if __name__ == "__main__":
    unittest.main()
