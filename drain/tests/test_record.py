from __future__ import annotations

import unittest

from drain.record import make_key, normalize

from .helpers import NOW


class TestRecord(unittest.TestCase):
    def test_key_is_deterministic_and_identity_based(self) -> None:
        self.assertEqual(make_key("github:sux", "1"), make_key("github:sux", "1"))
        self.assertNotEqual(make_key("github:sux", "1"), make_key("github:sux", "2"))

    def test_age_days(self) -> None:
        item = normalize(
            {"source": "mock", "native_id": "a", "created_at": "2026-07-14T00:00:00Z"}, NOW
        )
        self.assertEqual(item.age_days, 10.0)

    def test_missing_created_at_gives_none_age(self) -> None:
        self.assertIsNone(normalize({"source": "m", "native_id": "a"}, NOW).age_days)

    def test_evidence_sets_signal(self) -> None:
        item = normalize({"source": "m", "native_id": "a", "evidence": "x"}, NOW)
        self.assertTrue(item.signals.get("has_evidence"))

    def test_malformed_record_does_not_raise(self) -> None:
        item = normalize({}, NOW)
        self.assertEqual(item.kind, "unknown")
        self.assertTrue(item.key)

    def test_to_dict_roundtrips_fields(self) -> None:
        item = normalize({"source": "m", "native_id": "a", "title": "t"}, NOW)
        d = item.to_dict()
        self.assertEqual(d["title"], "t")
        self.assertEqual(d["key"], item.key)


if __name__ == "__main__":
    unittest.main()
