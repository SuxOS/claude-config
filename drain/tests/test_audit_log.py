from __future__ import annotations

import os
import tempfile
import unittest

from drain.audit_log import AuditLog, redact

from .helpers import now


class TestAuditLog(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "audit.jsonl")
        self.log = AuditLog(self.path, now=now)

    def test_append_and_read(self) -> None:
        self.log.append({"event": "action", "key": "k1", "action": "comment", "result": "ok"})
        self.log.append({"event": "gate", "key": "k2", "gate": "[GATE: x]"})
        entries = self.log.entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["ts"], now().isoformat())

    def test_redaction(self) -> None:
        token = "ghp_" + "A" * 36
        out = redact({"msg": f"leaked {token} here", "op": "op://Secrets/x/credential"})
        self.assertNotIn(token, out["msg"])
        self.assertIn("«redacted»", out["msg"])
        # op:// reference paths are not secrets and must survive.
        self.assertIn("op://Secrets/x/credential", out["op"])

    def test_seen_keys_only_ok_actions(self) -> None:
        self.log.append({"event": "action", "key": "k1", "action": "comment", "result": "ok"})
        self.log.append({"event": "action", "key": "k2", "action": "comment", "result": "error"})
        self.log.append({"event": "plan", "key": "k3", "action": "comment"})
        seen = self.log.seen_keys()
        self.assertIn(("k1", "comment"), seen)
        self.assertNotIn(("k2", "comment"), seen)
        self.assertNotIn(("k3", "comment"), seen)

    def test_seen_keys_filter_by_action(self) -> None:
        self.log.append({"event": "action", "key": "k1", "action": "comment", "result": "ok"})
        self.log.append({"event": "action", "key": "k1", "action": "close_with_evidence", "result": "ok"})
        self.assertEqual(self.log.seen_keys(actions=["close_with_evidence"]), {("k1", "close_with_evidence")})


if __name__ == "__main__":
    unittest.main()
