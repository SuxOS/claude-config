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
3. **`dispatch`** — **job control** for dispatched/remote/background work, both
   directions: launch (background session, cloud pipeline fixer/triage/issue-build,
   schedule, queue) *and* list / stop / pause / resume / cancel. The `nohup`+`jobs`+
   `kill`+`fg` of the fabric.
   - Absorbs: `fork`, `cron`, `queue`.
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
    "SuxOS":   { "github": "SuxOS",   "repos": ["sux", "sux-fileops", "suxrouter", "claude-config"], "cloud_workflows": ["fixer.yml", "triage.yml", "issue-build.yml"] },
    "colinxs": { "github": "colinxs", "repos": [] }
  },
  "bot": { "account": "bot@colinxs.com", "config_dir": "~/.claude-bot" }
}
```

One truth, read by the locus detector, all five skills, and the control-panel. No
second copy anywhere.

**Locus detector** — a tiny deterministic helper (stdlib only, no LLM). Input: cwd +
fabric. Output: `{locus: workspace|org|repo, org: <name|null>, repos: [...in scope]}`.
Shared by every skill.

**Rails** (`hooks/`) — unchanged. `require-delegation-model` (live),
`verify-completion-claim` (built, off by default). Cardinal rules as code.

**Control-panel** (`tools/control-panel/`) — reframed as the **org-locus cockpit**: the
visual face of `orient` (health across repos) + `dispatch` (fire local/cloud jobs).
Made multi-org aware via the new fabric. Kept, not rebuilt.

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
- No rebuild of the cloud pipeline (`fixer`/`triage`/`issue-build` commands stay;
  `dispatch` routes to them).
- No session-state persistence in fabric — sessions are runtime, not declared truth.

## Open questions

- `colinxs` org dir exists (renamed from `Life`) but has no clones yet; repo list starts
  empty and gets seeded as repos land there.
- (none outstanding)
