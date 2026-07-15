# Loci Redesign — workspace / org / repo

**Date:** 2026-07-15
**Status:** approved design, pre-implementation
**Branch:** `add-org-watch-and-control-panel`

## Problem

The current `claude-config` encodes intent as a typographic DSL: a `.`/`?`/`!` mood
system, `!`-count intensity dials, and `name=value` adverbs, spread across ~18 verb
skills (`go`, `wtf`, `fix`, `bug`, `develop`, `drain`, `org-watch`, …). Two failures:

1. **The punctuation is cognitive tax with no payoff.** `/go` over plain "go" buys
   nothing the bare word plus the cardinal rules don't already give. The marks encode
   intensity, but plain English already carries intensity ("carefully, in parallel").
2. **The verbs are one operation seen through intensity lenses.** `go`/`develop`/
   `drain`/`fix`/`bug` are all "do the highest-value doable thing." Once punctuation
   stops encoding intensity, the only real axis of difference left is **locus** — where
   the work is happening.

Meanwhile the actual work has a clear shape the config doesn't model: a three-tier
**locus** hierarchy, workspace ⊃ org ⊃ repo, with 5–10 concurrent sessions each mapped
to a subset of repos.

## Themes (from the user)

- Keep the spirit of the cardinal rules (deterministic-over-LLM, one-source-of-truth,
  bias-to-reversible-action, one-workstream-per-context).
- **Drop all punctuation** — `.`/`?`/`!`, counts, adverbs. Gone.
- A skill must earn its keep: encode a playbook or tool-routing the bare word wouldn't
  give. Ceremony verbs die.
- Radical cut: a **few loci-aware skills**, not a verb zoo.
- Rewrite `WORKFLOW.md` full scope.

## Grounding sentence (shared with the cloud pipeline)

The `.github` three-loop-pipeline design states the frame this redesign also inherits
verbatim:

> a **self-hosted autonomy pipeline for one operator (Colin), on private repos, with the
> operator nearby to fix things, and high trust in the agent.**

Everything falls out of that sentence: high trust + operator-nearby justifies the radical
cut and the no-ceremony surface; private + reversible justifies **ship-and-roll-back** as
the default (cardinal rule #4); the one real residual risk is **prompt injection via
content the agent reads**, defended by *scoping what a tool can do after reading untrusted
text*, never by author-trust theater.

## Reconciliation with the cloud three-loop pipeline

`SuxOS/.github/docs/design/three-loop-pipeline.md` is the **authoritative** model of the
cloud fabric; this spec adapts to it (not the reverse). Consequences woven through the
sections below:

- The cloud pipeline is **not** `fixer`/`triage`/`issue-build`. `triage.yml` is deleted;
  the real shape is **three continuous cron loops** + nightly safety nets:
  1. **collate & build** — `fixer` proposes → `issue-build` verifies (binary
     buildable/needs-human) + clusters (file/concept/time) + always builds ≥1.
  2. **green → merge** — GitHub native auto-merge; eligibility is `not-draft AND
     not-hold`; branch-protection required checks are the real gate.
  3. **red/behind → rebase → autofix → needs-human → unstick** — `pr-auto-update`
     (cheap, uncapped) → `claude-autofix` (capped) → `needs-human` → `pr-unstick` (daily,
     cooldown+cycle-capped free retries).
  Safety nets: `deep-audit` (nightly), `org-consistency` (weekly), `security-review`
  (per-PR, advisory), `budget-governor` (spend control).
- **One security model across local and cloud** — see Substrate → Rails.
- **The parked local-vs-cloud fork is dissolved** — see Substrate → local ↔ cloud.

## The locus model (the spine)

```
~/Code                    ← workspace  (spans orgs; sync colinxs ↔ suxos)
├── SuxOS/                ← org        (where you live; maps to a GitHub org)
│   ├── sux/  suxrouter/  ← repo       (focused dev / surgery)
│   └── claude-config/
└── colinxs/              ← org        (renamed from Life; matches GitHub org)
```

| Locus | Path shape | What you do | Session character |
|---|---|---|---|
| **workspace** | `~/Code` | sync orgs, reconcile clones, keep fabric true | rare, brief |
| **org** | `~/Code/<Org>` | orient across repos, coordinate sessions, dispatch (local/cloud), watch health | home base, long-lived |
| **repo** | `~/Code/<Org>/<repo>` | focused development / surgery | short, deep |

Skills do not each reimplement scope. A single **deterministic locus detector**
(cwd + fabric → `{locus, org, repos-in-scope}`) is the one shared primitive every
skill calls. Centralizing it is what keeps five small skills from each re-growing their
own "am I at org or repo?" branching.

## Organizing metaphor: skills are CLI tools for Claude

The design spine is Unix. A skill is a tool on Claude's PATH; the cardinal rules are the
shell. This is what makes the radical cut principled instead of arbitrary, and it sorts
every skill — present and future — into one of two families:

- **Locus tools** — cwd-sensitive, act on the workspace/org/repo tree (like `git`,
  `make`, `find`, `ls`): `orient`, `work`, `dispatch`, `sync`, `verify`.
- **Filters** — orthogonal, transform an output/stream regardless of locus (like
  `paste`, `sort`, `grep`, `jq`): `paste`, and room for more.

Unix principles *are* the spec, and each resolves a design question:

| Unix | Here |
|---|---|
| do one thing well | the radical cut — one skill = one tool |
| composable | chain in a session: `orient` → `work` → `verify` |
| job control (`nohup`/`bg`/`jobs`/`kill`/`fg`) | `dispatch` — launch **and** stop/resume/cancel remote+background work |
| `--help` / `man` / `which` | discovery is self-describing (skill descriptions = man pages); no ceremony verb |
| `paste`, `sort` are coreutils | filters are a real class, not an exception |
| exit codes / `$?` | `verify` — did it *actually* succeed |
| PATH + man pages | skill descriptions for triggering; WORKFLOW.md as the intro(1) |

## The skills (radical cut, zero punctuation)

Intensity and scope come from plain English + the detected locus — never from marks.

1. **`orient`** — "where am I, what's off, where did I leave off." Read-only.
   - repo → this repo's state; org → cross-repo health radar; workspace → cross-org drift.
   - Absorbs: `wtf`, `org-watch`, `explain`, `man`.
2. **`work`** — pick the highest-value doable unit, take it end-to-end
   (branch → code → verify → land). Self-heals when git is jammed.
   - repo → focused; org → survey all repos, worktree, land.
   - Absorbs: `develop`, `drain`, `go`, `fix`, `bug`, `fml`.
3. **`dispatch`** — **job control** over the cloud three-loop pipeline and background
   work, both directions (`nohup`+`jobs`+`kill`+`fg` of the fabric):
   - **launch** — file issues (seed Loop 1), open PRs (enter Loops 2–3), spawn a
     background session, schedule a cron, queue-for-later.
   - **stop / pause** — apply `hold` (the one cloud write-gate) + disable loop crons.
   - **resume** — remove `hold` + re-enable crons.
   - **list / cancel** — show in-flight loop state; close a PR/issue.
   - Absorbs: `fork`, `cron`, `queue`. "Stop remote workflows, do surgery, reenable"
     is literally `dispatch(hold+disable) → work → dispatch(unhold+enable)`.
4. **`verify`** — prove it actually works by exercising it end-to-end (the `$?` check).
   - Absorbs: `bet`. Aligns with the existing built-in `verify` skill.
5. **`sync`** — workspace-only: reconcile `colinxs ↔ SuxOS`, pull/push clones, keep
   `fabric.json` true.

**Filter (orthogonal, not a locus tool):**

6. **`paste`** — format output for its destination (email/Slack/GitHub/terminal),
   selecting register per target. Locus-agnostic; a coreutil, kept.

**Deleted:** every other verb skill and all `.`/`?`/`!` marks, counts, adverbs.

Locus → primary tools: workspace → `sync` (+ `orient`); org → `orient` + `dispatch`;
repo → `work` + `verify`. `orient`/`work`/`dispatch`/`verify` run at every locus, scoped
by the detector; `sync` is workspace-specific; `paste` runs anywhere.

**Discovery** ("how would I do X with these skills") needs no verb — the skill
descriptions are the man pages and WORKFLOW.md is the intro. Ask in plain English.

## Substrate

**Fabric** (`fabric.json`) — lifts from single-org to workspace-with-orgs:

```json
{
  "workspace_root": "~/Code",
  "orgs": {
    "SuxOS":   { "github": "SuxOS",   "repos": ["sux", "sux-fileops", "suxrouter", "claude-config", ".github"],
                 "pipeline": { "repo": ".github", "loops": ["collate-build", "green-merge", "red-rebase"] } },
    "colinxs": { "github": "colinxs", "repos": [] }
  },
  "accounts": {
    "human": { "email": "m@colinxs.com" },
    "bot":   { "email": "claude@colinxs.com", "config_dir": "~/.claude-bot" }
  },
  "surfaces": {
    "desktop":         { "account": "human" },
    "cli":             { "account": "bot" },
    "cloud-workflows": { "account": "bot" }
  }
}
```

**Identity is per-surface** — the fact that Desktop runs as the human (`m@colinxs.com`)
while CLI and cloud-workflows run as the bot (`claude@colinxs.com`) is declared truth,
not something a skill sniffs at runtime. This replaces the old flat `bot` block (whose
`bot@colinxs.com` / `claude@colinxs.com` values were stale). In CLI-tool terms it's
`/etc/passwd` + "which user the daemon runs as": any tool that acts as or attributes to
an identity (`dispatch` to cloud, `work`'s commit/land, `sync`) reads it here.

One truth, read by the locus detector, all five skills, and the control-panel. No
second copy anywhere. The `pipeline` block **points at** the loops (hosted in `.github`);
it does not enumerate workflow files — that list lives in `SuxOS/.github` and is not
duplicated here (which is why the old `cloud_workflows: [fixer, triage, issue-build]` was
both a duplication and stale once `triage.yml` was deleted). `loops` names the three loops
so `dispatch` has routing targets without re-encoding `.github`'s file set.

**Locus detector** — a tiny deterministic helper (stdlib only, no LLM). Input: cwd +
fabric. Output: `{locus: workspace|org|repo, org: <name|null>, repos: [...in scope],
surface: desktop|cli|cloud-workflows, account: human|bot}`. Shared by every skill.

**Rails** (`hooks/`) — the **local expression of the one security model shared with the
cloud pipeline**. That model (from `three-loop-pipeline.md` §2) is two tiers + one label,
and it governs local `work` and the cloud loops identically:

- **Tier A — hard block, no LLM, human hands only.** Irreversible/destructive writes
  (force-push to `main`, branch/tag/repo deletion, history rewrite, dropping prod data),
  persistent secret exposure (secret that *survives* in git history / a comment / committed
  logs), PHI/PII egress. Enforced by *mechanism* — branch protection + restricted tokens +
  Safe Outputs in cloud; the hard rails locally. This is cardinal rule #4's "irreversible
  needs an explicit yes," stated as an enforced boundary.
- **Tier B — advisory, ship-and-roll-back (the default for everything else).** Red CI,
  missing verdict, high-blast diff, unverified issue, stale branch, a secret briefly
  visible in an *ephemeral* log. None block; they ship, get watched, and roll back if
  wrong. This is cardinal rule #4's "bias to reversible action."
- **`hold`** — the single manual+automatic cloud write-gate ("no automation touches this
  PR"), applied only by a CONFIRMED critical/high security finding or by the operator.
  `dispatch` is how the operator applies/removes it.

The existing hooks are the local Tier-B rails: `require-delegation-model` (live),
`verify-completion-claim` (built, off). Nothing new to add — YAGNI — but they are now
*documented as* the local half of a model whose cloud half is enforced in `.github`.

**local ↔ cloud — the parked fork, dissolved.**
`.github/docs/design/local-vs-cloud-autonomy-model.md` parks an open question: should
`develop` default local-first, cloud-first, or two-co-equal-modes? The loci model
*dissolves* it rather than picking a side. There is no global default mode because there
are two independent things running at once:

- **The operator works locally, in-thread** — locus = wherever cwd is. `work`/`verify` at
  repo or org locus. This is hands-on, watched, worktree-isolated.
- **The three loops run continuously in the cloud** — crons, bot account, always churning
  whatever has been filed, whether the operator or the bot filed it.

They are not competing modes; they are the *operator* and the *substrate*. `dispatch`
seeds the loops (file issues / open PRs) and controls them (`hold`, cron toggle);
`orient @org` monitors what they did. Both always run, sharing the one security model. So
"default locus" is a non-question: your locus is your cwd; the pipeline just runs. (This
resolves the parked doc — worth updating it to point here.)

**Control-panel** (`tools/control-panel/`) — reframed as the **org-locus cockpit**: the
visual face of `orient` (three-loop + local health) + `dispatch` (seed/hold/toggle the
loops). Made multi-org aware via the new fabric. Kept, not rebuilt.

**WORKFLOW.md** — fully rewritten: the three loci (the map) → the five skills (what you
drive) → the per-locus loop → fabric/rails as substrate → setup state. No punctuation
grammar anywhere.

**CLAUDE.md** — the "verb grammar" section (the entire `.`/`?`/`!` mood/count/adverb
DSL and the per-verb family notes) is **removed and replaced**. It currently *mandates*
the punctuation the skills are dropping, so leaving it makes the cardinal-rules file
contradict the skills. Replacement: keep the 10 cardinal rules and the dev-speed
tactics; swap the grammar section for a short "loci + five skills" section pointing at
WORKFLOW.md. This is required scope, not optional.

## Non-goals

- No new hooks (YAGNI — the two existing rails suffice).
- **No rebuild of the cloud pipeline.** The three-loop pipeline in `SuxOS/.github` is
  authoritative and stays as-is; this redesign only *consumes* it (dispatch seeds/controls
  it, orient monitors it, fabric points at it). `claude-config` never re-encodes the loop
  logic or the workflow file list.
- No session-state persistence in fabric — sessions are runtime, not declared truth.

## Open questions

- `colinxs` org dir exists (renamed from `Life`) but has no clones yet; repo list starts
  empty and gets seeded as repos land there.
- The three-loop pipeline's Phases 1–3 are shipped-but-not-exercised-live (per its §6).
  `claude-config`'s `dispatch`/`orient` should be built against its *documented* contract
  (`hold`, `needs-human`, native auto-merge, the loop crons), and smoke-tested once a real
  PR exercises the pipeline — not blocked on it.
- Worth a one-line update to `.github/docs/design/local-vs-cloud-autonomy-model.md`
  pointing at this spec's "local ↔ cloud dissolved" resolution (separate repo, separate
  commit).
