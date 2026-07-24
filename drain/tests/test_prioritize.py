from __future__ import annotations

import unittest

from drain.classify import classify_all
from drain.prioritize import prioritize, score
from drain.record import normalize

from .helpers import NOW


def _item(nid, **kw):
    raw = {"source": "mock", "native_id": nid, "title": nid, "status": "open"}
    raw.update(kw)
    return normalize(raw, NOW)


class TestPrioritize(unittest.TestCase):
    def test_completed_sinks(self) -> None:
        items = classify_all([
            _item("done", status="closed"),
            _item("todo", next_action="x"),
        ])
        order = [i.native_id for i in prioritize(items)]
        self.assertEqual(order[-1], "done")

    def test_priority_label_beats_stale(self) -> None:
        p0 = _item("p0", next_action="x", priority_label="P0", created_at="2026-07-23T00:00:00Z")
        p4 = _item("p4", next_action="x", priority_label="P4-LATER", created_at="2024-01-01T00:00:00Z")
        classify_all([p0, p4])
        order = [i.native_id for i in prioritize([p4, p0])]
        self.assertEqual(order[0], "p0")

    def test_deterministic_and_tie_break_by_key(self) -> None:
        a = _item("aaa", next_action="x")
        b = _item("bbb", next_action="x")
        classify_all([a, b])
        first = [i.key for i in prioritize([a, b])]
        second = [i.key for i in prioritize([b, a])]
        self.assertEqual(first, second)  # order independent of input order

    def test_failed_check_raises_score_within_state(self) -> None:
        # Both are 'blocked' (a dependency blocks them); the failing one ranks higher
        # among blocked work. The bonus orders within a state, never across states —
        # a failed check moves an item to 'blocked', it doesn't promote it above actionable.
        plain = _item("plain", dependencies=["#1"])
        failing = _item("fail", dependencies=["#1"], signals={"failed_check": True})
        classify_all([plain, failing])
        self.assertEqual(plain.classification, "blocked")
        self.assertEqual(failing.classification, "blocked")
        self.assertGreater(score(failing), score(plain))


if __name__ == "__main__":
    unittest.main()
