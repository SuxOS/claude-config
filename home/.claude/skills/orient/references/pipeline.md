# Dimension: cloud pipeline state

Read-only survey of the autonomous three-loop pipeline (`SuxOS/.github`,
`three-loop-pipeline.md`). Runs when the in-scope org has a `pipeline` in the fabric. All
`gh`, no model judgment. Reports only what needs a human — a healthy pipeline emits zero
lines.

## What the loops mean (so you know what "off" looks like)

1. **collate & build** — `fixer` files issues → `issue-build` clusters + builds ≥1.
2. **green → merge** — native auto-merge; eligibility = `not-draft AND not-hold`.
3. **red/behind → rebase → autofix → needs-human → unstick**.

## Gather (per org, across its `repos`)

```
# Held — parked, nothing automated touches these (operator or a CONFIRMED security finding)
gh pr list --repo <org>/<r> --state open --label hold --json number,title,updatedAt

# needs-human — autofix exhausted its cap; awaiting pr-unstick or a human
gh pr list --repo <org>/<r> --state open --label needs-human --json number,title,updatedAt

# Stuck in a loop — red or behind for a while, not moving
gh pr list --repo <org>/<r> --state open --json number,title,mergeable,isDraft,updatedAt,labels

# Pipeline workflows failing (the loops themselves broken, not a PR)
gh run list --repo <org>/.github --workflow issue-build.yml --limit 5 --json status,conclusion,createdAt
```

## Filter to signal — what earns a line

- **Held PRs** — list them; a `hold` you forgot to clear silently blocks a PR forever.
- **`needs-human` pileup** — PRs autofix gave up on. Count + oldest; a growing pile means
  the operator is the bottleneck.
- **Stuck** — a PR open + red/behind for >~24h with no bot commit progressing it (the
  ladder isn't clearing it).
- **Broken loop** — a pipeline workflow (`issue-build`/`automerge`/`pr-unstick`) itself
  failing on its cron. This is a jam, not a PR problem.

A pipeline that's merging greens and clearing reds on its own gets **no line**. Route: held
/ stuck / broken → `dispatch` (unhold, toggle, requeue); a `needs-human` PR whose fix is
real work → `work`.
