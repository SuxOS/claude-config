---
name: work
description: Do the work — take the highest-value doable unit end-to-end, locally, now (survey → scope → worktree → code → verify → land). Locus-aware: at a repo it works that repo; at an org it surveys all the org's clones and picks. Self-heals when local git is jammed. Use for "work", "develop", "ship it", "build X", "fix this", "implement Y", "figure out what to work on", "work across all my repos", "take it end to end", "do the highest-value thing", "keep shipping until done". Acts locally in-thread; to hand work to the autonomous pipeline instead, that's dispatch.
---

# work

**work means: find the unit worth doing at this locus and take it end-to-end** — no
ceremony. Read the fabric, survey the clones in scope, pick, then branch → code → verify →
land. One burst, then hand the thread back. `orient` finds what's off; `work` does it.

Local and in-thread by design — you're watching it happen, worktree-isolated. To hand work
to the autonomous `.github` pipeline instead (build-while-away), use `dispatch`.

## Scope — from the locus, or from what you're told

- A **hint** scopes what: `work the flaky auth tests` · `work #42` · `work suxrouter`.
- **Bare**, self-scope from the locus: at a **repo**, the top doable-in-one-session unit
  here; at an **org**, survey every clone and pick the top unit (or sweep, if asked). Size
  to what one session finishes — overflow hands to a fresh session (rule #10), never churns
  a rotting context.
- **Keep going until dry** (a whole backlog, "keep shipping"): run bursts back-to-back,
  **bounded** — declare the stop up front (2 empty passes, a time cap, or manual halt). An
  unbounded loop is a bug. Self-heal between passes; a jam drops to recovery, then resumes.
- **Scope operators** (`scope+=X` / `scope-=X` / `scope=X`, see root `CLAUDE.md`) act on the
  bare self-scope above: `+=` unions X in, `-=` excludes X from the survey/pick, `=`
  replaces self-scope entirely with X. `work org scope-=automation` = the org's normal
  survey-every-clone-pick-top-unit, with automation/pipeline work excluded from candidates.

## How to run it

1. **Read the fabric + survey (deterministic, no LLM — rule #2).** From `workspace_root`,
   one pass over the in-scope repos:
   ```
   for d in <org>/<repos>; do git -C "$WS/$d" status --short --branch; done
   gh pr list --repo <org>/<r> --state open
   gh run list --repo <org>/<r> --limit 5      # repeated failures
   ```
   This is the same survey `orient` runs — there filtered to report, here a work queue. If
   local git looks stuck (a jam), route to the unjam playbook before starting new work.
2. **Scope + plan.** Take the hint or self-scope. For anything beyond a small unit, gate
   first: surface intent, and for a build with real design choices, propose 2–3 approaches
   with a recommendation (superpowers `brainstorming`) → a file-level plan (`writing-plans`)
   before code. Small units skip the ceremony — scope by difficulty, not size.
3. **Execute — worktree-isolated.** Branch in a detached scratch worktree → code. Where a
   test can pin the behavior, drive it test-first (`test-driven-development`); a gnarly break
   goes through `systematic-debugging`, not guesses. Chase root causes; exhaustive where
   cheap, scoped by difficulty.
4. **Verify.** Exercise the change with the built-in `verify` skill — never claim shipped
   without watching the checks pass (this is self-enforced discipline, not a hook — no Stop
   hook is wired, see `hooks/README.md`; regression tests earn the name only red-green
   verified). For a high-stakes change, `verify` adversarially.
5. **Land.** With checks green, offer the exits — don't pick silently:
   **push + open PR** (the default; the PR then enters the `.github` loops:
   green→merge, red→rebase/autofix) · **merge locally** · **keep the branch** · **discard**.
   Discarding needs an explicit go-ahead.

## Output

One line per unit — outcome, not narration:
`[SHIPPED|BUILT|VERIFIED|UNJAMMED: <what cleared>|STAGED: <needs review>|BLOCKED: <reason>] <desc>`
For a drain, a summary: `[DRAINED: <n over p passes>|DRY|CAPPED: <bound>|HALTED|BLOCKED: <jam>]`.

## Worktrees — local-mutation discipline (non-negotiable)

Any parallel or cross-repo local git work goes through isolated worktrees:

- **One detached scratch worktree per mutator** — `git worktree add --detach <scratch>/<repo>-<unit> <base-sha>`. Never a named-branch checkout.
- **Never `git checkout` a branch a worktree may hold** — silent no-op, not an error.
  Operate detached; push by explicit refspec (`git push origin HEAD:refs/heads/<branch>`).
- **Verify committer identity before every push** — pre-empt the GH007 reject.
- **Never touch the primary checkout's current branch.** GC orphaned scratch worktrees at
  start and end; cap concurrent at `cores−2`.
- **Reap `[gone]` branches worktree-first** — `git worktree remove --force` before
  `git branch -D` (delete-first orphans the worktree).

## Unjam playbook (local git stuck — self-heal before new work)

| Jam | Signal | Fix |
|---|---|---|
| GH007 committer-email | push rejected | fix committer identity, re-push |
| Stale-worktree no-op | `git checkout` silently fails | prune the stale worktree, operate detached |
| Required check stuck | your PR red/behind, not landing | diagnose the failing check; rebase/auto-update; let the pipeline's ladder take it, or `dispatch` requeue |

## Rails that don't bend

Never force-push, merge/publish without confirmation, hard-delete, or do anything
irreversible/destructive (Tier A) without an explicit yes — boldness is spent on
**reversible** moves only (branches, worktrees, PRs, reverts). That's the same
ship-and-roll-back model the `.github` pipeline runs on.
