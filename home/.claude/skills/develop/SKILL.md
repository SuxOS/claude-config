---
name: develop
description: The autonomous developer verb — find the highest-value doable work and take it end-to-end (branch → code → verify → PR), as **one burst**, then return. Act family; **dispatch by default, drop local to unjam**. Bare/no-args self-scopes ("just figure it out"); a hint scopes what, the `!` count + adverbs scope how hard and how wide (develop! one unit here → develop!!!!! a full org-sweep pass). Its looping sibling `/developer` runs bursts until dry. Use for "/develop", "figure out what to work on", "ship one thing", "the pipeline's jammed", "work on X and ship it".
---

**`develop` means: find the work worth doing and ship it end-to-end** — no ceremony. Bare, it *self-scopes*: reads the repo and picks what's worth doing. It is **mostly a dispatcher** — healthy work goes to the cloud fabric and you get your thread back — but it keeps local hands for the one job the cloud can't do to itself: **unjamming**. It runs **one burst** — a unit, a cluster, or a single org-sweep pass — then hands your thread back. To keep draining until the backlog's dry, that's the looping sibling `/developer` (this verb in a `while (not dry)`). No separate "foreman" verb — org scale is just `develop repos=all`.

## The locus router (what runs where)

Every run **preflights the fabric, then routes**. Iron rule: **never dispatch onto a jam** — piling cloud work on a stuck queue deepens it.

- **Healthy → dispatch (cloud, the default).** Compile the modifier → `gh workflow run` the propose/build/drain stages across the target repos; return a manifest. The label state-machine + event chain drain it unattended. This is "shift max work to the cloud, return fast."
- **Jammed → recover (local, worktree-safe).** A wedged merge queue, exhausted subscription pool, orphaned `building` issue, GH007 push reject, stale-worktree no-op — the cloud can't fix these by running *more* cloud. Drop in-thread, run the `fml!` recovery method locally across the affected repos, then re-fire.
- **Local build (single session).** A not-opted-in repo, `--local`, or "do it here now": run the whole propose→build→verify arc yourself, in this context, through isolated worktrees.

## `!` count + hint = scope and locus

No mark **gates** (proposes what it'll do first); any `!` **produces**. The count scales scope *and* pushes locus from local-atom toward cloud-org:

- **`/develop`** (bare, no args) — self-scope: scan the current repo (git status, failing tests, TODOs, open issues, recent churn), pick the top doable-in-one-session unit, **propose it, then build on your ok**.
- **`develop!`** — pick and build one unit, here, now. Skip the gate.
- **`develop!!!`** — clear this repo's ready queue: a related cluster, fork sub-agents for independent pieces, verify each.
- **`develop!!!!!`** — one org-sweep pass: broadcast propose→build→drain across every opted-in repo in the cloud, then return. (Repeat-until-dry is `/developer`.)

**Hint = the noun** (scopes *what*, skips the guessing): `develop! the flaky auth tests` · `develop! #42` · `develop! src/router`. **Adverbs tune the rest** — `repos=` (default current; `all` = org), `risk=` (bold vs everything-staged-for-review), `verify=` (smoke → adversarial `bet?`), `parallel=`, `model=`, `tokens=`. `--local`/`--cloud` force the locus · `--dry` shows the plan, writes nothing · `--suggest` proposes + recommends · `--force` skips the soft gate (hard rails hold).

## How to run it

1. **Preflight** — cheap local read of fabric health (`gh pr list`, `gh run list`, merge-queue + label counts, `git worktree list`). No LLM. If jammed, route to recovery *before* dispatching.
2. **Scope** — take the hint, or self-scope the top unit(s) through the fixer lens. Size to what one session can finish; overflow hands to the cloud/`fork!`, never churns a rotting context (rule #10).
3. **Route** — dispatch (healthy) / recover (jammed) / local-build (explicit). Compile the modifier into the stage set, model, caps, fan-out.
4. **Execute** — cloud: fire the callers, return the manifest. Local: worktree-isolated branch → code → verify. Chase root causes; exhaustive where cheap, scoped by *difficulty* not size.
5. **Verify + hand back** — cloud: confirm the runs launched. Local: exercise the change (`/verify`), open the PR. After a recovery, confirm the jam actually cleared (`bet?`) — don't assume.

## Unjam playbook (local, the `fml!` method scoped to the fabric)

| Jam | Signal | Local fix |
|---|---|---|
| Merge queue stuck | PRs queued, not landing | diagnose failing required check; rebase/auto-update; re-enqueue |
| Pool exhausted → `security-review` can't gate | required check never starts | verify `security-review.yml` uses `CLAUDE_CODE_OAUTH_TOKEN` (never `ANTHROPIC_API_KEY` — dead in SuxOS CI, $0 instant-error); if the pool itself is exhausted, escalate for more OAuth capacity — **config change, ask first** |
| Orphaned `building` | issue `building` >2h, no PR | re-queue (`building`→`queued-for-build`); manual escalation of the reaper |
| GH007 committer-email | push rejected on drain | fix committer identity, re-push |
| Stale-worktree no-op | `git checkout` silently fails | prune the stale worktree, operate detached |
| `needs-review` pileup | count climbing | surface for you; optionally re-triage borderline items |

## Worktrees (local-mutation discipline — non-negotiable)

Any parallel or cross-repo local git work goes through isolated worktrees, per the org's hygiene:

- **One detached scratch worktree per mutator** — `git worktree add --detach <scratch>/<repo>-<unit> <base-sha>`. Never a named-branch checkout.
- **Never `git checkout` a branch a worktree may hold** — silent no-op, not an error. Operate detached; push by explicit refspec (`git push origin HEAD:refs/heads/<branch>`).
- **Verify committer identity before every push** — pre-empt the GH007 reject.
- **Never touch the primary checkout's current branch.** GC orphaned scratch worktrees at start and end; cap concurrent worktrees at `min(cores−2)`.
- **Reap `[gone]` branches worktree-first.** A branch marked `[gone]` (upstream deleted after merge) may still be held by a worktree. Find it (`git worktree list`), `git worktree remove --force` it, *then* `git branch -D` — deleting the branch first orphans the worktree, the silent-no-op failure mode this section already guards against. Fold into the start/end GC pass.

## Output

One line per unit — outcome, not narration:

`[DISPATCHED: <n runs>|SHIPPED|BUILT|VERIFIED|UNJAMMED: <what cleared>|STAGED: <needs review>|BLOCKED: <reason>|HANDED-OFF: <to cloud/fork>] <short desc>`

At higher count, follow with an **Assumptions** list (self-scoped picks are assumptions you can veto) and a one-line **locus/spend** note.

## Hand off — don't reach past the boundary

- A whole distinct workstream that shouldn't share this context → `fork!`.
- Just diagnosing a break, not fixing → `wtf?`; it's on fire / deep recovery → `fml!` (develop calls this method for jams).
- Prove a shipped change is real → `bet?`. Run the org sweep on a cadence → `cron!` (`develop!!!!! @nightly`).

## Rails that don't bend

Never force-push, auto-merge past CI + security-review, hard-delete, or do anything irreversible without an explicit yes — a high count buys boldness on **reversible** moves only (branches, worktrees, PRs, reverts). Reverting the metered-key escape hatch for `security-review.yml` is a config change → ask first. A dispatched or forked run carries no standing authority; irreversible actions still gate wherever they run.
