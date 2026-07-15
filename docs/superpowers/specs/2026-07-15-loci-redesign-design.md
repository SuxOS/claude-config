# Loci Redesign — workspace / org / repo

**Date:** 2026-07-15
**Status:** approved — implementing
**Branch:** `add-org-watch-and-control-panel`

## What this is

A ground-up redesign of `claude-config`: replace the ~18-verb `.`/`?`/`!` punctuation DSL
with a tiny set of **locus-aware tools** organized around where the work happens
(workspace ⊃ org ⊃ repo). Skills become CLI tools for Claude — porcelain over the
plumbing of a fabric + `gh`/`git`.

Guiding cut: **less is more.** A tool exists only if it encodes a bespoke playbook the
bare word + cardinal rules + an existing built-in wouldn't already give.

## Grounding sentence (shared with the cloud pipeline)

From `SuxOS/.github/docs/design/three-loop-pipeline.md`, inherited verbatim:

> a self-hosted autonomy pipeline for one operator (Colin), on private repos, with the
> operator nearby to fix things, and high trust in the agent.

Consequences: high trust + operator-nearby → radical cut, no ceremony. Private +
reversible → **ship-and-roll-back** is the default (cardinal rule #4). The one real risk
is **prompt injection via content the agent reads**, defended by scoping what a tool may
*do* after reading untrusted text — never by author-trust theater.

## The locus model (the spine)

```
~/Code                    ← workspace  (spans orgs)
├── SuxOS/                ← org        (where you live; maps to a GitHub org)
│   ├── sux/  suxrouter/  ← repo       (focused dev / surgery)
│   └── claude-config/
└── colinxs/              ← org        (renamed from Life; no clones yet)
```

| Locus | Path | What you do |
|---|---|---|
| **workspace** | `~/Code` | reconcile orgs, keep fabric true (rare) |
| **org** | `~/Code/<Org>` | orient across repos, control the pipeline (home base) |
| **repo** | `~/Code/<Org>/<repo>` | focused development / surgery |

Tools detect locus deterministically (a few lines: `git rev-parse --show-toplevel` for
repo; path-vs-`workspace_root` for org/workspace) and adapt. Not each reimplemented — one
shared convention documented in `AUTHORING.md`.

## The tools — see / do / send + format

Three loci verbs, each a distinct locus of action, plus one orthogonal filter. Zero
punctuation; intensity/scope come from plain English + detected locus.

1. **`orient`** — *see.* Read the locus, report only what's off. repo → this repo's state;
   org → cross-repo health radar; workspace → cross-org drift. Read-only.
   Absorbs `wtf`, `org-watch`, `explain`, `man`.
2. **`work`** — *do.* Pick the highest-value doable unit and take it end-to-end
   (worktree → code → verify → land). Self-heals local git jams. repo → focused; org →
   survey all repos, sweep. Absorbs `develop`, `drain`, `go`, `fix`, `bug`, `fml`, `time`.
3. **`dispatch`** — *send.* The console for the autonomous `.github` three-loop pipeline:
   seed it (file issues → Loop 1; open PRs → Loops 2–3), and control it (`hold` a PR,
   toggle the loop crons — the "stop remote / do surgery / reenable" flow). Generic async
   (background agent, `schedule` cron) is the built-ins used directly, not re-wrapped.
   Absorbs `fork`, `cron`, `queue`.
4. **`paste`** *(filter, kept as-is)* — format output for its destination
   (email/Slack/GitHub/terminal). Orthogonal to locus; a coreutil.

### Pruned (final review)

- **`verify` → cut.** A wrapper over the built-in `verify` skill is pure indirection;
  `work` calls the built-in directly. `bet`'s adversarial mode folds into `work`'s verify
  step.
- **`sync` → deferred.** Workspace-sync's only job is `colinxs ↔ SuxOS`, and `colinxs` has
  no clones. Build it test-first when a second org is actually populated — not before.
- **All other verbs → deleted** (`go`/`wtf`/`fix`/`bug`/`time`/`fml`/`man`/`explain`/
  `audit`/`bet`/`cron`/`queue`/`fork`/`drain`/`develop`/`org-watch`) and every `.`/`?`/`!`
  mark, count, and adverb.

### Don't reimplement — delegation map

Each tool's own code is locus-aware routing; the heavy lift is borrowed.

| Tool | Its job | Delegates to |
|---|---|---|
| `orient` | survey locus, report drift | domain-skill dimensions (`gh`/`git`, script-free); built-in `code-review`/`security-review` for a deep pass |
| `work` | one unit end-to-end | superpowers `brainstorming`→`writing-plans`→`test-driven-development`/`systematic-debugging`; `using-git-worktrees`; built-in `verify` |
| `dispatch` | control the pipeline | `.github` loops via `gh` (`hold`, cron toggle, file issues/PRs); built-in `schedule`; `Agent` for background |
| `paste` | format for destination | self-contained |

## Cloud pipeline — authoritative, consumed not rebuilt

`SuxOS/.github/docs/design/three-loop-pipeline.md` is the source of truth. Its shape (for
`orient`/`dispatch` to read against):

1. **collate & build** — `fixer` proposes → `issue-build` verifies (binary
   buildable/needs-human) + clusters + always builds ≥1. *(`triage.yml` deleted; the
   confidence-tier taxonomy is gone.)*
2. **green → merge** — native auto-merge; eligibility is `not-draft AND not-hold`.
3. **red/behind → rebase → autofix → needs-human → unstick** — `pr-auto-update` →
   `claude-autofix` (capped) → `pr-unstick` (daily, cooldown+cycle-capped).

Safety nets: `deep-audit` (nightly), `org-consistency` (weekly), `security-review`,
`budget-governor`. `claude-config` never re-encodes any of this.

**local ↔ cloud is not a mode choice.** The operator works locally in-thread (locus =
cwd); the three loops run continuously in the cloud regardless. `dispatch` seeds/controls
them; `orient @org` monitors them. Both always run — the parked
`local-vs-cloud-autonomy-model.md` question is dissolved, not answered.

## Security model — one taxonomy, local + cloud

From the pipeline's §2, governing local `work` and the cloud loops identically:

- **Tier A — hard block, human hands only.** Irreversible/destructive writes (force-push
  to `main`, branch/tag/repo deletion, history rewrite, dropping prod data), persistent
  secret exposure, PHI/PII egress. Enforced by *mechanism* — branch protection + restricted
  tokens + Safe Outputs in cloud; the hard rails locally. = cardinal rule #4's
  irreversible-needs-a-yes.
- **Tier B — advisory, ship-and-roll-back (default for everything else).** Red CI, missing
  verdict, high-blast diff, unverified issue. None block; ship, watch, revert if wrong.
  = cardinal rule #4's bias-to-reversible-action.
- **`hold`** — the single cloud write-gate. `dispatch` applies/removes it.

The two hooks are the local Tier-B rails: `require-delegation-model` (live),
`verify-completion-claim` (built, off). Nothing new — YAGNI.

## Fabric — one declared truth (`~/.claude/fabric.json`, global)

```json
{
  "workspace_root": "~/Code",
  "orgs": {
    "SuxOS":   { "github": "SuxOS",   "repos": ["sux", "sux-fileops", "suxrouter", "claude-config", ".github"],
                 "pipeline": { "repo": ".github", "loops": ["collate-build", "green-merge", "red-rebase"] } },
    "colinxs": { "github": "colinxs", "repos": [] }
  },
  "bot": { "email": "claude@colinxs.com", "config_dir": "~/.claude-bot" }
}
```

- **Global location** (not a walk-up manifest): always findable from any cwd, dead simple,
  one workspace. The detector still walks up from cwd for repo/org locus.
- **`pipeline` points at** the loops (hosted in `.github`); it never enumerates workflow
  files — that list lives in `.github` (one source of truth; the old
  `cloud_workflows:[fixer,triage,issue-build]` was both a duplication and stale).
- **Identity is a documented fact, not a lookup.** Human = `m@colinxs.com` (desktop, runs
  as `~/.claude`); bot = `claude@colinxs.com` (cli + cloud, runs as `~/.claude-bot`). It's
  *ambient* — you inherit it from how the session launched — so the detector returns
  `{locus, org, repos}` only; `bot.config_dir` stays because a background/bot session
  needs the path.

## Prior art — the design instantiates proven patterns

Verified, not asserted. We instantiate established patterns rather than invent:

| Our piece | Pattern | Prior art |
|---|---|---|
| workspace ⊃ org ⊃ repo | clone tri-level under a root | **ghq** (`<root>/<host>/<org>/<repo>`; we drop host — single host today) |
| fabric + fan-out across repos | manifest declares repo set | **mani**, **gita**, **myrepos** |
| cwd → locus | nearest-config-wins, walk up | **git** (`rev-parse --show-toplevel`), **direnv** |
| thin tools ← detector + `gh`/`git` | high-level over composable primitives | **git porcelain vs plumbing** |
| small verb set × locus | fixed verbs on typed scope | **kubectl** (`get`/`apply`/`delete <resource>`) |

## Migration inventory

| Artifact | Fate | Note |
|---|---|---|
| `skills/{go,wtf,fix,bug,time,fml,man,explain,audit,bet,cron,queue,fork,drain,develop,org-watch}` | **delete** | folds into `orient`/`work`/`dispatch` |
| `skills/orient` | **born** | domain-skill pattern; reuses `org-watch`'s spine + `references/{github,local}.md` |
| `skills/work` | **born** | `develop`'s body minus the grammar; survey → scope → execute → verify → land; worktree + unjam discipline |
| `skills/dispatch` | **born** | pipeline console (`gh` `hold`/toggle/seed) + pointers to built-in `schedule`/`Agent` |
| `skills/verify` | **not created** | built-in covers it |
| `skills/sync` | **deferred** | until `colinxs` has clones |
| `skills/paste` | **keep** | orthogonal filter, unchanged |
| `skills/AUTHORING.md` | **rewrite** | keep test-first + domain-skill pattern; drop verb-family/mark scaffolding; add the locus-detection convention |
| `commands/{fixer,triage,issue-build}.md` | **delete** | stale copies of the pre-three-loop pipeline |
| `hooks/*` | **keep** | local Tier-B rails |
| `CLAUDE.md` | **trim** | keep 10 rules + 6 tactics; delete ~150-line grammar; add short "loci + tools" pointer. 193 → ~55 lines |
| `fabric.json` | **rewrite** | single-org → workspace-with-orgs + `pipeline` pointer; drop `cloud_workflows` |
| `tools/control-panel/` | **delete** | `orient` + `dispatch` cover it in-thread; a second surface not worth maintaining |
| `WORKFLOW.md` | **rewrite** | one operational screen: loci map → 3 verbs → the loop → setup. No essays |

## The development workflow (end-to-end)

The whole thing, no ceremony:

1. **Session opens** anywhere under `~/Code`. Tools detect locus from cwd.
2. **`orient`** — what's off here (repo state, or cross-repo radar at org).
3. **`work`** — take the top unit end-to-end: worktree → code (TDD where it fits) →
   built-in `verify` → **land** (push+PR is the default exit; merge/keep/discard on ask).
   Pushed PRs enter the `.github` loops automatically (green→merge, red→rebase/autofix).
4. **`dispatch`** *(occasional)* — seed the loops with issues to build while away, or
   `hold`/toggle the pipeline for surgery, then reenable.
5. **`paste`** — whenever output goes somewhere else.

Four things to know — **orient, work, dispatch, paste** — and the pipeline runs itself.

## Non-goals

- No new hooks; no rebuild of the cloud pipeline; no session-state in fabric (runtime, not
  declared truth); no `verify`/`sync`/control-panel (pruned/deferred/cut).

## Follow-up (separate `.github` commit, not this repo)

- One-line pointer in `local-vs-cloud-autonomy-model.md` noting the fork is dissolved here.
