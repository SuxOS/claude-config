---
name: dispatch
description: Send work to the autonomous side — the console for the SuxOS/.github three-loop pipeline. Seed it (file issues → build loop; open PRs → merge/rebase loops) and control it (hold/unhold a PR, disable/re-enable the loop crons — the "stop the remote workflows, do surgery, then reenable" flow). Use for "dispatch", "stop the remote workflows", "pause the pipeline", "put a hold on", "reenable", "file issues for the bot to build", "build this while I'm away", "let the pipeline handle it", "requeue that PR". For generic background/scheduled work (not the pipeline) it points you at the built-in Agent/schedule — it doesn't re-wrap them.
---

# dispatch

**dispatch means: hand work to the autonomous side and control it.** The bespoke thing it
owns is the `SuxOS/.github` **three-loop pipeline** — the crons that build filed issues,
merge green PRs, and rebase/autofix red ones while you're away. `work` does it yourself,
locally; `dispatch` lets the pipeline do it, or steers the pipeline.

Generic async is *not* this skill's job — a one-off background agent is the `Agent` tool;
a recurring job is the built-in `schedule` skill. Use those directly. dispatch is only for
the pipeline.

## The pipeline (what you're steering)

Read it from the fabric's `orgs.<org>.pipeline` (repo = `.github`, loops =
`collate-build`, `green-merge`, `red-rebase`). The authoritative design is
`SuxOS/.github/docs/design/three-loop-pipeline.md` — don't re-encode it; drive it via `gh`.

| Loop | Fires on | You steer it by |
|---|---|---|
| collate & build | filed issues | filing issues (seed) |
| green → merge | `not-draft AND not-hold` PR | `hold`/unhold |
| red/behind → rebase → autofix | a red or behind PR | requeue / toggle the cron |

## Seed — give the loops work

- **File issues** for the bot to build unattended: `gh issue create --repo <org>/<r> ...`.
  A well-scoped issue (clear title + acceptance) is what the build loop clusters and takes.
- **Open a PR** and it enters the merge/rebase loops automatically — that's just `work`'s
  land step; nothing extra to do here.

## Control — the stop / surgery / reenable flow

The exact sequence for "stop the remote workflows, do local surgery, then reenable":

1. **Stop** — `hold` the PRs that must not move + disable the loop crons:
   ```
   gh pr edit <n> --repo <org>/<r> --add-label hold
   gh workflow disable <loop>.yml --repo <org>/.github
   ```
2. **Surgery** — do the local work (`work`), land it.
3. **Reenable** — remove the holds + re-enable the crons:
   ```
   gh pr edit <n> --repo <org>/<r> --remove-label hold
   gh workflow enable <loop>.yml --repo <org>/.github
   ```

Other controls: **requeue** a `needs-human` PR (remove the label so `pr-unstick` retries),
**park** anything by hand with `hold`, **cancel** by closing the PR/issue.

## Output

`[SEEDED: <n issues>|HELD: <prs>|DISABLED: <loops>|REENABLED: <loops>|REQUEUED: <pr>] <desc>`
When you disable a loop, say so plainly and don't forget the reenable — a disabled cron is
silent.

## Rails

`hold` and label edits are reversible — fine to apply boldly. **Disabling a pipeline cron
is a standing change**: confirm before leaving one disabled, and always name what you
turned off so it gets turned back on. Merging/force-pushing/anything Tier A still needs an
explicit yes.
