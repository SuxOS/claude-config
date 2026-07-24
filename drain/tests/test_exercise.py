from __future__ import annotations

import unittest
from collections import Counter

from drain.classify import classify
from drain.exercise import verdict_to_record, verdicts_to_records
from drain.policy import plan_action
from drain.record import normalize

from .helpers import NOW, load_fixture


def _classified(raw):
    item = normalize(raw, NOW)
    item.classification = classify(item)
    return item


class TestExerciseMapping(unittest.TestCase):
    def test_verdict_kinds_map_to_actions(self) -> None:
        cases = {
            "ALREADY_DONE": ("actionable", "close_with_evidence"),
            "STALE_SUPERSEDED": ("actionable", "close_with_evidence"),
            "DEFER": ("actionable", "close_with_evidence"),
            "DECIDE_AND_BUILD": ("actionable", "remove_label"),
            "HARD_BLOCKED": ("requires-gate", None),
        }
        for verdict, (state, action_kind) in cases.items():
            raw = verdict_to_record(
                {"repo": "sux", "number": 1, "title": "t", "verdict": verdict,
                 "confidence": "high", "evidence": "e", "superseded_by": "#2",
                 "decision": "d", "hard_block_action": "mint a secret"}
            )
            item = _classified(raw)
            self.assertEqual(item.classification, state, verdict)
            action = plan_action(item)
            if action_kind:
                self.assertEqual(action.kind, action_kind, verdict)
            else:
                self.assertTrue(action.gated, verdict)

    def test_golden_69_distribution(self) -> None:
        verdicts = load_fixture("eval-verdicts-69.json")
        records = verdicts_to_records(verdicts)
        self.assertEqual(len(records), 69)
        counts = Counter()
        for raw in records:
            item = _classified(raw)
            action = plan_action(item)
            key = action.kind if not action.gated else "GATED"
            counts[key] += 1
        # 4 ALREADY_DONE + 4 STALE + 5 DEFER = 13 evidence-closes
        self.assertEqual(counts["close_with_evidence"], 13)
        # 53 DECIDE_AND_BUILD -> clear needs-human
        self.assertEqual(counts["remove_label"], 53)
        # 3 HARD_BLOCKED -> gated
        self.assertEqual(counts["GATED"], 3)

    def test_hard_blocked_carries_gate_line(self) -> None:
        raw = verdict_to_record(
            {"repo": "sux", "number": 1356, "title": "t", "verdict": "HARD_BLOCKED",
             "hard_block_action": "Colin exports from portal"}
        )
        item = _classified(raw)
        line = plan_action(item).gate_line()
        self.assertTrue(line.startswith("[GATE:"))
        self.assertIn("portal", line)


if __name__ == "__main__":
    unittest.main()
