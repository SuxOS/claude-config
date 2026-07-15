# Dimension: local drift & coverage gap

Run `scripts/local_drift.py <org>` from the scope directory. Mechanical git work (status/log/reflog across subdirs) — a script, never a model call.

Reports, per locally-cloned repo:
- **Drift** — uncommitted changes, untracked files, ahead/behind vs. `origin/<branch>`. Local and remote have diverged.
- **Thrashing** — recent resets/force-pushes/rebases in the reflog (last 7 days) and stale unmerged branches (>30 days untouched). Signals churn or work that stalled mid-flight.
- **Bidirectional coverage gap** — `missing_local_clone` (org repos with no local clone here) and `stray_local_clones` (local git dirs not mapping to any repo in the target org). Both mean your local view and the org's real state have diverged, which is worth a line each.

Filter to signal: a clean repo (nothing uncommitted, in sync, no thrashing) gets no line. The report names what's *off*, not a roster of every clone.
