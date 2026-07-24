from __future__ import annotations

import unittest

from drain.classify import classify
from drain.record import normalize

from .helpers import NOW, load_fixture


class TestClassify(unittest.TestCase):
    def setUp(self) -> None:
        self.items = {r["native_id"]: normalize(r, NOW) for r in load_fixture("mock_tracker.json")}
        for it in self.items.values():
            it.classification = classify(it)

    def test_each_state(self) -> None:
        expected = {
            "A1": "actionable",
            "D1": "actionable",
            "B1": "blocked",
            "B2": "blocked",
            "W1": "waiting",
            "R1": "needs-review",
            "C1": "completed",
            "G1": "requires-gate",
            "U1": "unknown",
            "L1": "actionable",
        }
        for nid, want in expected.items():
            self.assertEqual(self.items[nid].classification, want, f"{nid} should be {want}")

    def test_gate_beats_duplicate(self) -> None:
        # A gated item is requires-gate even if it also looks like a duplicate.
        item = normalize(
            {"source": "mock", "native_id": "X", "title": "t", "status": "open",
             "evidence": "sup by #1",
             "signals": {"gated": True, "duplicate": True, "confidence": "high"}},
            NOW,
        )
        self.assertEqual(classify(item), "requires-gate")

    def test_completed_unverified_without_evidence_is_review(self) -> None:
        item = normalize(
            {"source": "mock", "native_id": "Y", "title": "t", "status": "open",
             "signals": {"completed_unverified": True}},
            NOW,
        )
        self.assertEqual(classify(item), "needs-review")

    def test_duplicate_without_evidence_is_review(self) -> None:
        item = normalize(
            {"source": "mock", "native_id": "Z", "title": "t", "status": "open",
             "signals": {"duplicate": True, "confidence": "high"}},
            NOW,
        )
        self.assertEqual(classify(item), "needs-review")

    def test_low_confidence_duplicate_is_review(self) -> None:
        item = normalize(
            {"source": "mock", "native_id": "Q", "title": "t", "status": "open",
             "evidence": "maybe", "signals": {"duplicate": True, "confidence": "low"}},
            NOW,
        )
        self.assertEqual(classify(item), "needs-review")


if __name__ == "__main__":
    unittest.main()
