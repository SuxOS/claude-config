---
name: orient
description: See what's going on at the current locus — the read-only radar over workspace/org/repo. Detects where you are from cwd (repo → this repo's state; org → the cross-repo health radar; workspace → cross-org drift), surveys local clones + GitHub (issues/PRs/Actions/settings) + the .github pipeline, and reports only what's OFF. Use for "orient", "what's going on", "where did I leave off", "catch me up", "status", "monitor the org", "what's drifting across repos", "check Actions across all repos", "what's uncommitted", "is anything broken". Read-only — it surveys and routes; work/dispatch act.
---

# orient

**orient means: read the current locus and report only what's *off*.** It's the read-only
radar. A per-repo scan is raw input; the deliverable is what emerges when you compare
clones, PRs, and pipeline state against each other. `work` acts on what orient finds;
orient never repairs.

## The spine — resolve locus → run dimensions → synthesize → report

Fixed and tiny. All domain knowledge lives in the dimensions (one file each); the spine
just collects and joins.

## Step 0 — resolve the locus from the fabric + cwd

Read `~/.claude/fabric.json` (`workspace_root`, `orgs`). Detect locus deterministically —
no LLM, no inference:

- **repo** — cwd is inside a git repo (`git rev-parse --show-toplevel` succeeds and sits
  under an org dir) → scope = that one repo.
- **org** — cwd is an org dir directly under `workspace_root` (or `git` finds no repo but
  the path matches an org) → scope = that org's `repos`.
- **workspace** — cwd is `workspace_root` → scope = all orgs.

That resolution *is* the scope — say it in the header. Fall back to cwd-inference only when
the fabric is absent; say so when you're guessing.

## Step 1 — run the dimensions (fan out; each self-filters to signal)

The dimensions are independent — run them concurrently. Each reference file owns its own
"what to gather + how to filter." **The filter is the discipline: a healthy repo and a
clean clone emit zero lines.** Read a dimension's file only when running it.

| Dimension | When | File |
|---|---|---|
| **GitHub survey** | org/workspace; cross-repo issues/PRs/Actions/settings | `references/github.md` |
| **Local drift** | any locus with clones; uncommitted / diverged / thrashing | `references/local.md` |
| **Pipeline** | org has a `pipeline`; held PRs, `needs-human`, stuck loops | `references/pipeline.md` |

At **repo** locus, this collapses to the current repo's slice of each — its own git state,
its own open PRs/Actions, its own pipeline PRs. At **org/workspace**, the cross-repo
synthesis is the point.

## Step 2 — synthesize + report

The highest-value findings are **cross-dimension**: a diverged local branch that also has
an open PR against a repo with a failing required check; a held PR blocking a `needs-human`
pileup. Join where the evidence lines up — that correlation is the payoff of running the
dimensions together.

```markdown
# Orient: <locus> <name>
_Scope: <mode>, N repos · dimensions: <list>_

## What's off        ← cross-repo bugs · drift · settings drift · held/stuck pipeline · blocked-by
## Local             ← uncommitted/diverged · thrashing · coverage gap
## Snapshot          ← one line per repo, reference only
```

Any checked section with nothing to report says "none" in one line — don't omit it, don't
pad it. Lead with whatever's most urgent.

## Hand off — orient reports; the tools act

Each finding names its exit:

- **Local drift** (uncommitted/diverged clone) → `work` on that repo.
- **A jam** (wedged local git, orphaned worktree) → `work` (self-heals before new work).
- **Held / stuck / `needs-human` pipeline PR** → `dispatch` (unhold, toggle, or requeue).
- **Repeated cross-repo bug / settings drift** → `dispatch` files an issue per repo, or
  `work` fixes the class if it's one root cause.
- **Recurring digest** → the built-in `schedule` skill owns *when*; orient just surveys.

Don't reach past the boundary: orient surveys and routes, it does not repair.

## Extending — a dimension is a file, not a rewrite

Drop `references/<dim>.md` (what to gather + how to filter), add a script to `scripts/`
**only if the logic is genuinely non-trivial** (prefer inline `gh`/`git`), add a table row
and a report section. A new dimension earns its file only from an observed miss
(test-first — see `../AUTHORING.md`).
