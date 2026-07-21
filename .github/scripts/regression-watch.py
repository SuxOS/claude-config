#!/usr/bin/env python3
"""Advisory step for a filed bug issue against a rail file (#316): cross-references recent git
history for that file and annotates the issue with `possible-regression-of: #<PR>` candidates.

This is the minimal "watch" half of claude-config's Tier-B ship-and-roll-back policy
(docs/superpowers/specs/2026-07-15-loci-redesign-design.md:117-120 — "ship, watch, revert if
wrong"): today a merge that silently weakens a rail's real-world behavior is only caught when a
human or fixer pass stumbles onto the resulting bug later, with zero automated attribution back
to the merge that likely caused it. This only flags a lead for a human/fixer to check next — it
never reverts anything or asserts the merge actually caused the bug.

Run from `.github/workflows/regression-watch.yml` on a `bug`-labeled issue. Reads the issue's
title/body from ISSUE_TITLE/ISSUE_BODY, posts via `gh issue comment` using GH_TOKEN/ISSUE_NUMBER.
"""
import os
import re
import subprocess
import sys

RAIL_GLOB = "home/.claude/hooks/*.py"
WINDOW_GIT = "14 days ago"  # git --since value
WINDOW_LABEL = "14 days"  # human-readable prose form of the same window
MAX_LINES = 15
PR_NUM_RE = re.compile(r"\(#(\d+)\)")


def rail_files():
    out = subprocess.run(
        ["git", "ls-files", RAIL_GLOB], capture_output=True, text=True, check=True
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def mentioned_rail_files(text, files):
    return [f for f in files if re.search(re.escape(os.path.basename(f)), text)]


def recent_prs_for_file(path):
    """(pr_number, subject) for each commit in the window touching path, PR = last (#N) in the
    subject — GitHub's default squash-merge commit message appends " (#<PR>)"."""
    out = subprocess.run(
        ["git", "log", f"--since={WINDOW_GIT}", "--pretty=format:%s", "--", path],
        capture_output=True, text=True, check=True,
    ).stdout
    hits = []
    for subject in out.splitlines():
        matches = PR_NUM_RE.findall(subject)
        if matches:
            hits.append((matches[-1], subject))
    return hits


def main():
    title = os.environ.get("ISSUE_TITLE") or ""
    body = os.environ.get("ISSUE_BODY") or ""
    issue_number = os.environ.get("ISSUE_NUMBER") or ""
    text = f"{title}\n{body}"

    hits = mentioned_rail_files(text, rail_files())
    if not hits:
        print("no rail file mentioned in this issue; nothing to cross-reference")
        return 0

    lines = []
    seen = set()
    for path in hits:
        for pr_number, subject in recent_prs_for_file(path):
            key = (path, pr_number)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"possible-regression-of: #{pr_number} — touched `{path}`: {subject}")

    if not lines:
        print(f"rail file(s) mentioned ({', '.join(hits)}) but no merges in the last {WINDOW_LABEL}")
        return 0

    truncated = lines[:MAX_LINES]
    comment = "\n".join(
        [
            "This issue names a rail file that was touched by a recent merge — not a confirmed "
            f"cause, just a lead worth checking first (merges in the last {WINDOW_LABEL}):",
            "",
            *truncated,
        ]
    )
    if len(lines) > MAX_LINES:
        comment += f"\n\n... and {len(lines) - MAX_LINES} more merge(s) in the window."

    subprocess.run(["gh", "issue", "comment", issue_number, "--body", comment], check=True)
    print(comment)
    return 0


if __name__ == "__main__":
    sys.exit(main())
