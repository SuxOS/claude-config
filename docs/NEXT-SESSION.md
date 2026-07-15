# Next session — org-wide autonomous loop

What to type next session, and the plan it drives. Two phases: **get to a clean synced
state**, then **run the steady-state audit→issue→build loop**.

## The one command to start

Open a session in `~/Code` (workspace locus) and type:

```
orient the whole org, then get everything to a clean synced state: land the open
reconciliation PRs, prune anything stale/dead, and report what's left before we loop.
```

`orient` at workspace locus reads the fabric, walks every org's clones, and reports what's
off. Then `work`/`dispatch` clear it.

## Phase A — reach a clean synced state (one-time)

Started this session; finish it next:

1. **Land the reconciliation PRs** (in dependency order):
   - `SuxOS/.github#155` (draft) — smoke-test one caller via `workflow_dispatch`, then mark
     ready so it merges. **This must land first** — the caller repos pin `@main`.
   - Then the caller PRs (`sux`/`suxrouter`/`sux-fileops`, `reconcile/loci-pipeline`) and
     `claude-config#16`. Un-draft the caller PRs once #155 is on `main`.
   - Restart Claude Code after `claude-config#16` lands so the new skills load.
2. **Prune stale/dead** — the audits already removed the big items (dead callers, old
   pipeline copies, control-panel). Next: sweep each repo with `orient` for leftover stale
   labels, docs, dead code; `work` or `dispatch` (file issues) to clear.
3. **Repo-wide ops** (operator-specified — fill these in):
   - **Visibility check** — confirm every repo's intended public/private state; branch
     protection armed where `automerge` needs it.
   - **Renames** — any repo/label/branch renames to normalize.
   - **New repos** — scaffold + add to `fabric.json` `orgs.<org>.repos` + a caller-stub set
     (`scripts/scaffold-caller.sh` in `.github`).
   - **Refactor to lib** — extract the shared code into a library repo; wire consumers.
4. **Sync to main** — everything green-merged; `orient` reports zero drift; clean worktrees.

## Phase B — steady-state loop (the while-true)

Once clean, this is the ongoing org-management loop. It's just the tools + the pipeline:

```
while not interrupted:
    orient each repo (fan out — one audit lens per repo)      # see what's off / worth doing
    dispatch: file the findings as issues                     # seed the pipeline's build loop
    → the .github three loops build + merge them autonomously  # collate-build / green-merge / red-rebase
    report progress; fix org-level problems with work/dispatch
    optionally: propose feature suggestions as issues
```

In tool terms: **`orient` (audit each repo) → `dispatch` (file issues) → the three-loop
pipeline builds/merges → `orient` again (progress + new drift)**. The pipeline is the
engine; `orient`/`dispatch` are the operator's loop over it. Kick it off with:

```
run the org loop: orient every repo, file the worthwhile findings as issues for the
pipeline to build, report progress, and keep going until the backlog's dry or I stop you.
```

Keep it **bounded** (a pass count, a time cap, or manual halt — an unbounded loop is a
bug), run it in the background if it's long, and let the pipeline do the building while the
thread stays free.

## Guardrails (unchanged)

- Tier A (irreversible/destructive, secret egress) never auto-runs — human hands only.
- Everything else ships and rolls back; `hold` parks any PR.
- Nothing merges the org-wide `.github` change without a smoke test first (§6).
