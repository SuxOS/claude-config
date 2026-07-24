"""drain — continuous audit-and-drain orchestrator for in-flight work.

Discovers work from configured adapters (local git, GitHub, mock fixtures), normalizes
it into one record shape, classifies each item deterministically, prioritizes a drain
plan, performs safe reversible idempotent actions, gates everything destructive, verifies
claimed completions, and re-audits until drained or every item carries a precise blocker.

Local-first, stdlib-only (Python 3.9+), three run modes: audit (read-only), plan
(dry-run), run (execute). See docs/design/2026-07-24-drain-orchestrator-design.md.
"""

from __future__ import annotations

__version__ = "0.1.0"
