"""Render a DrainResult into a deterministic markdown (and dict) report.

The report distinguishes observed facts (discovered/by-state), actions taken, gates &
assumptions, and remaining items with their precise blockers — the spec's final-report
contract.
"""

from __future__ import annotations

from typing import Any, Dict

from .engine import DrainResult


def to_markdown(result: DrainResult) -> str:
    r = result
    lines = []
    lines.append(f"# drain report — mode: {r.mode}")
    lines.append("")
    lines.append(f"- rounds: {r.rounds}")
    lines.append(f"- discovered: {r.discovered}")
    lines.append(f"- drained: {'yes' if r.drained else 'no'}")
    lines.append("")
    lines.append("## By state")
    if r.by_state:
        for state in sorted(r.by_state, key=lambda s: -r.by_state[s]):
            lines.append(f"- {state}: {r.by_state[state]}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append(f"## Actions ({len(r.actions)})")
    if r.actions:
        for a in r.actions[:100]:
            res = a.get("result", a.get("action"))
            lines.append(f"- [{a.get('action')}] {a.get('source','')} {a.get('key','')} — {a.get('detail','')} ({res})")
    else:
        lines.append("- none")
    lines.append("")
    lines.append(f"## Completed ({len(r.completed)})")
    for c in r.completed[:100]:
        lines.append(f"- {c['source']} — {c['title']}")
    if not r.completed:
        lines.append("- none")
    lines.append("")
    lines.append(f"## Remaining, with blockers ({len(r.remaining)})")
    for item in r.remaining[:200]:
        lines.append(f"- [{item['state']}] {item['source']} — {item['title']} → {item['blocker']}")
    if not r.remaining:
        lines.append("- none")
    lines.append("")
    lines.append(f"## Gates & assumptions ({len(r.gates)})")
    for g in r.gates:
        lines.append(f"- {g['gate']} ({g['source']} — {g['title']})")
    if not r.gates:
        lines.append("- none")
    lines.append("")
    lines.append(f"## Unavailable / skipped sources ({len(r.skipped_sources)})")
    for s in r.skipped_sources:
        lines.append(f"- {s['source']}: {s['reason']}")
    if not r.skipped_sources:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def to_dict(result: DrainResult) -> Dict[str, Any]:
    return result.to_dict()
