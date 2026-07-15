# Dimension: local drift & coverage gap

Script-free: plain `git` across the in-scope clones under `workspace_root` (from the
fabric). Mechanical, deterministic — run the commands, read the output, filter to signal.
No model judgment in the gathering.

## Gather (inline)

`WS` = `workspace_root`; iterate the resolved locus's repos (`<org>/<repo>` dirs). Per
clone — dirty/diverged in one pass:
```
for d in <org>/<repos>; do
  echo "== $d =="
  git -C "$WS/$d" status --short --branch          # uncommitted, untracked, ahead/behind
done
```
Deeper signal, only where a clone looked busy above:
```
git -C "$WS/$d" log -1 --format='%cr'                        # last-commit age
git -C "$WS/$d" for-each-ref --sort=-committerdate refs/heads/ --format='%(refname:short) %(committerdate:relative)'
git -C "$WS/$d" reflog --date=relative -20                   # resets/rebases = thrashing
```
Coverage gap — local vs org (per in-scope org):
```
gh repo list <org> --limit 1000 --json name -q '.[].name'    # compare to the local clone dirs
```

## Filter to signal — what earns a line

- **Drift** — uncommitted/untracked changes, or ahead/behind vs `origin/<branch>`.
- **Thrashing** — recent resets/force-pushes/rebases (reflog, last ~7d), or stale unmerged
  branches (>30d untouched). Work that stalled mid-flight.
- **Coverage gap** — an org repo with no local clone (`missing`), or a local git dir not in
  the fabric's `repos` (`stray`). One line each.

A clean clone — nothing uncommitted, in sync, no thrashing — gets **no line**. The report
names what's *off*. When a dirty clone also has an open PR (GitHub dimension) or a held
pipeline PR (pipeline dimension), surface the join — it outranks the raw drift.
