"""Append-only JSONL audit trail with secret redaction.

Every decision and action appends one line. The log is the idempotency source of truth
(``seen_keys``) and the evidence backing the final report. Nothing is ever rewritten or
deleted — re-runs append. All payloads pass through ``redact`` so a token that leaks into
an error string never lands in the log.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

# Known secret-ish token shapes. op:// reference paths are NOT secrets and are left intact.
_SECRET_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),  # GitHub PAT / app / oauth tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),  # OpenAI-style keys
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack tokens
    re.compile(r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
]
_REDACTED = "«redacted»"


def redact(value: Any) -> Any:
    """Recursively redact secret-shaped substrings from strings/dicts/lists."""
    if isinstance(value, str):
        out = value
        for pat in _SECRET_PATTERNS:
            out = pat.sub(_REDACTED, out)
        return out
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class AuditLog:
    """Append-only JSONL log. ``now`` is injectable for deterministic tests."""

    def __init__(self, path: str, now: Optional[Any] = None) -> None:
        self.path = path
        self._now = now or (lambda: datetime.now(timezone.utc))
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(entry)
        record.setdefault("ts", self._now().isoformat())
        record = redact(record)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def entries(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        out: List[Dict[str, Any]] = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def seen_keys(self, actions: Optional[Iterable[str]] = None) -> set:
        """Keys already acted upon (optionally filtered to specific action kinds).

        This is the idempotency ledger: before executing an action the engine checks
        whether ``(key, action)`` already succeeded here, and skips if so.
        """
        want = set(actions) if actions is not None else None
        seen = set()
        for e in self.entries():
            if e.get("event") != "action" or e.get("result") != "ok":
                continue
            if want is not None and e.get("action") not in want:
                continue
            k = e.get("key")
            if k:
                seen.add((k, e.get("action")))
        return seen
