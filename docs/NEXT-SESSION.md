# Next session — zero-question org autonomy

Everything from the loci redesign + three-loop reconciliation is **merged to `main`
org-wide** (`.github`, `claude-config`, `sux`, `sux-fileops`, `suxrouter`). The pipeline is
**live** (`CLAUDE_CODE_OAUTH_TOKEN` + bot App secrets set) and **scheduled** — it runs and
makes progress on its own crons, credit-bounded. This doc is how to drive it hands-off.

## The one command — paste this, expect zero questions

Open a session in `~/Code` and paste:

```
Full autonomy, zero questions — decide and log, don't ask. Reconcile everything org- and
local-dir-wide, fully sync local with cloud (pull every repo's main, prune anything stale
or dead you find), then run the exhaustive loop: orient every repo, file the worthwhile
findings as issues for the pipeline to build, and keep the pipeline healthy. Make real,
meaningful progress — do not blow the budget on busywork. Bound it: stop if the throttle
goes red or you hit 2 empty passes. Monitor spend the whole time and pull the kill switch
(below) if credits run away. Report progress as you go; I'm signing off.
```

This is deliberately self-contained: it grants autonomy (no gate), scopes the work
(reconcile → sync → loop), sets the quality bar (real progress, not busywork), bounds it
(red throttle / 2 empty passes), and names the kill switch. The tools won't stop to ask.

## What "the exhaustive loop" actually is

It's already the architecture — you don't babysit it:

```
fixer-bugs / fixer-30m / fixer (3-tier, 15m/30m/hourly)  ─proposes issues→  issue-build (hourly)  ─builds PRs→  automerge (on green)
```

The three `fixer*.yml` cadences and `issue-build.yml`'s schedule live in
`.github/workflows/` (see each file's `on.schedule` cron) — check there instead of this doc
for exact timing, since it drifts as cadences get retuned. Not every repo runs the
`pr-watch`/`pr-auto-update`/`pr-unstick` self-heal loop shown in earlier revisions of this
doc — `claude-config` currently doesn't (see `.github/workflows/` for what's actually wired
here).

`orient` + `dispatch` from your session are the *operator's overlay* on this: `orient`
finds cross-repo work the scheduled `fixer` misses; `dispatch` files it as issues (seeds
the same build loop) or holds/steers the pipeline. To seed a burst now instead of waiting
for the cron: `gh workflow run fixer.yml --repo SuxOS/<repo>`.

## Monitoring & the kill switch (credit safety — already built)

`budget-governor.yml` (runs every 6h) rolls up trailing-7-day runner minutes as a spend
**proxy** and writes a green/yellow/red **throttle** into an "Autonomy throttle" issue per
repo. `check-throttle` makes expensive Claude workloads **skip at red** — so spend stops
before a blowout without disabling anything. Fail-open (a governor outage never stalls
merges).

- **See spend:** the org-wide "Autonomy throttle" report issue in `SuxOS/.github`, and
  per-repo throttle issues. Calibrate the proxy against claude.ai's usage page
  (`SuxOS/.github/docs/design/budget-and-cadence.md`).
- **Hard stop (manual kill switch):** set a repo's "Autonomy throttle" issue body to
  `level: red` and add the `throttle-manual` label — the governor won't override it, and
  every scheduled Claude workload defers. To fully halt a loop:
  `gh workflow disable <fixer|issue-build|pr-unstick>.yml --repo SuxOS/<repo>` (re-enable
  with `enable`).
- **Tunable knobs** (in `SuxOS/.github`, for stability/efficiency):
  - `budget-governor.yml` env: `OPUS_BUDGET_MIN` (900), `TOTAL_BUDGET_MIN` (6000),
    `YELLOW_FRACTION` (0.75), governor cadence (`13 */6 * * *` — tighten for faster
    reaction overnight).
  - caller cadences: `fixer` (daily), `issue-build` (`7 2,8,14,20`), `pr-unstick` (daily).
  - `issue-build` `MAX_CLUSTERS` (throughput cap); `claude-autofix` `max-attempts` (6).
  Tune from observed spend: red too often → widen budgets or slow cadence; idle with
  backlog → tighten cadence or raise `MAX_CLUSTERS`.

## Guardrails (unchanged, hold under full autonomy)

- Tier A (irreversible/destructive, secret egress) never auto-runs — human hands only.
- Everything else ships and rolls back; `hold` parks any PR; a red throttle stops spend.
- The org-wide `.github` pipeline change already landed behind its consumer smoke checks.

## Local housekeeping when you start

- `git -C <each repo> checkout main && git pull` (the reconcile/redesign branches are
  merged + deleted remotely). Restart Claude Code once so the new `orient`/`work`/`dispatch`
  skills load from the merged `claude-config`.
