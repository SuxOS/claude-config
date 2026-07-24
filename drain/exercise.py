"""SuxOS glue: map the 69-issue Opus eval verdicts into drain records.

Kept out of the generic core — this is the one place that knows the eval's verdict
vocabulary. Each verdict becomes a raw record whose signals drive the deterministic
classifier to the right action:

  ALREADY_DONE / STALE_SUPERSEDED -> actionable close_with_evidence (reversible)
  DEFER                            -> actionable close_with_evidence (documented rationale)
  DECIDE_AND_BUILD                 -> actionable remove_label (clear needs-human -> pipeline)
  HARD_BLOCKED                     -> requires-gate ([GATE: <human action>])
"""

from __future__ import annotations

from typing import Any, Dict, List

from .adapters.github import GitHubAdapter

_CLOSE_VERDICTS = {"ALREADY_DONE", "STALE_SUPERSEDED", "DEFER"}


def verdict_to_record(v: Dict[str, Any]) -> Dict[str, Any]:
    repo = v["repo"]
    slug = repo if "/" in repo else f"SuxOS/{repo}"
    number = str(v["number"])
    verdict = v["verdict"]
    evidence = v.get("evidence") or v.get("rationale") or ""
    base = {
        "source": f"github:{slug}",
        "native_id": number,
        "title": v.get("title", ""),
        "kind": "issue",
        "status": "open",
        "labels": ["needs-human"],
        "evidence": evidence,
        "signals": {"confidence": v.get("confidence", "high")},
    }
    sig = base["signals"]
    if verdict in _CLOSE_VERDICTS:
        sig["stale"] = True
        sig["has_evidence"] = bool(evidence)
        sig["superseded_by"] = v.get("superseded_by", "")
        base["next_action"] = "close with evidence"
        # Evidence comment posted on close.
        base["_comment"] = f"Resolved by drain ({verdict}): {evidence}"[:1000]
    elif verdict == "DECIDE_AND_BUILD":
        sig["clear_label"] = "needs-human"
        base["next_action"] = v.get("decision", "decision recorded — cleared for build")
    elif verdict == "HARD_BLOCKED":
        sig["gated"] = True
        sig["gate_reason"] = v.get("hard_block_action", "human action required")
        sig["gate_action"] = "grant_permission"
        base["next_action"] = v.get("local_continuation", "")
    else:
        base["signals"]["needs_review"] = True
    return base


def verdicts_to_records(verdicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [verdict_to_record(v) for v in verdicts]


class VerdictAdapter(GitHubAdapter):
    """A GitHub adapter seeded from eval verdicts.

    Discovery returns the verdict-derived records (no ``gh`` query needed); actions run
    through the real ``gh`` path inherited from GitHubAdapter, so ``plan`` mode previews
    and ``run`` mode applies the same closes/relabels/gates.
    """

    name = "github"

    def __init__(self, verdicts: List[Dict[str, Any]], **kwargs) -> None:
        super().__init__(**kwargs)
        self._records = verdicts_to_records(verdicts)

    def discover(self) -> List[Dict[str, Any]]:
        return list(self._records)
