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
`collate-build`, `green-merge`, `red-rebase` — **conceptual names, not workflow
filenames**: each maps to real `.yml` files in the table below, so never
`gh workflow disable collate-build.yml`). The authoritative design is
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

The loop *names* (`collate-build`/`green-merge`/`red-rebase`) are conceptual — the real,
disable-able cron/trigger workflows live **in the repo you're doing surgery on**
(`<org>/<r>`), not in `<org>/.github`. `.github` only hosts the reusable `workflow_call`
*library* definitions (plain `issue-build.yml`/`automerge.yml`/`fixer.yml` there have no
schedule of their own) plus its own self-contained pipeline for `.github`'s own repo
(`self-issue-build.yml`/`self-automerge.yml`/`self-fixer.yml`). Map loop → real file(s):

| Loop | File(s) in `<org>/<r>` | If `<r>` is `.github` itself |
|---|---|---|
| collate-build | `issue-build.yml` (+ all `fixer*.yml` cadences to stop new proposals too — check `gh workflow list`) | `self-issue-build.yml` (+ `self-fixer.yml`) |
| green-merge | `automerge.yml` (+ `pr-drain.yml` reconcile backstop) | `self-automerge.yml` |
| red-rebase | `pr-auto-update.yml` (+ `pr-unstick.yml`, `claude-autofix.yml`) | n/a — `.github` has no red-rebase loop of its own |

Not every repo has every file (e.g. `claude-config` currently has no `pr-auto-update`/
`pr-unstick` — a red/behind PR here has nothing to auto-rebase or unstick it, so it needs
a manual `git pull --rebase` or `hold`/close; it DOES have `pr-drain.yml`, the green-merge
reconcile backstop noted in the row above) — confirm with
`gh workflow list --repo <org>/<r>` before disabling. Wiring it is a repo-side thin wrapper
around the `SuxOS/.github` reusable `pr-auto-update.yml`/`pr-unstick.yml` (mirroring
`issue-build.yml`'s/`automerge.yml`'s pattern in this repo's `.github/workflows/`), but
requires reading those reusable workflows' actual `workflow_call` inputs first — this
bot's token can't reach `SuxOS/.github` (see the token-scope note in `CLAUDE.md`), so that
step needs a human or a differently-scoped session.

The exact sequence for "stop the remote workflows, do local surgery, then reenable":

1. **Stop** — `hold` the PRs that must not move + disable the relevant loop file(s) in the
   repo you're operating on:
   ```
   gh pr edit <n> --repo <org>/<r> --add-label hold
   gh workflow disable issue-build.yml --repo <org>/<r>
   ```
2. **Surgery** — do the local work (`work`), land it.
3. **Reenable** — remove the holds + re-enable the same file(s):
   ```
   gh pr edit <n> --repo <org>/<r> --remove-label hold
   gh workflow enable issue-build.yml --repo <org>/<r>
   ```

Other controls: **requeue** a `needs-human` PR (remove the label so `pr-unstick` retries,
where that workflow is wired — see the table above for which repos have it), **park**
anything by hand with `hold`, **cancel** by closing the PR/issue.

## Output

`[SEEDED: <n issues>|HELD: <prs>|DISABLED: <loops>|REENABLED: <loops>|REQUEUED: <pr>] <desc>`
When you disable a loop, say so plainly and don't forget the reenable — a disabled cron is
silent.

## Rails

`hold` and label edits are reversible — fine to apply boldly. **Disabling a pipeline cron
is a standing change**: confirm before leaving one disabled, and always name what you
turned off so it gets turned back on. Merging/force-pushing/anything Tier A still needs an
explicit yes.
