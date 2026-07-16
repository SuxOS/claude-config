# Working with Claude on SuxOS

The development loop, in one screen. Work is organized by **where it happens**, not by any
grammar you have to memorize. Plain English is the whole surface.

## The map — three loci

```
~/Code                    ← workspace  (spans orgs; reconcile them here — rare)
├── SuxOS/                ← org        (where you live; a GitHub org, its repos)
│   ├── sux/  suxrouter/  ← repo       (focused development / surgery)
│   └── claude-config/
└── colinxs/              ← org
```

The tools detect which locus you're in from your cwd and adapt. You never say it.

## The tools — see / do / send

- **`orient`** — *see.* What's off here. At a repo: its state. At an org: the cross-repo
  radar (drift, repeated bugs, settings drift, held/stuck pipeline PRs). Read-only.
- **`work`** — *do.* Take the top doable unit end-to-end, locally, now: survey → worktree →
  code → verify → land. Self-heals a jammed git. At an org it surveys every clone and picks.
- **`dispatch`** — *send.* Steer the autonomous `.github` pipeline: file issues for it to
  build while you're away, or `hold`/toggle it for surgery and reenable.
- **`paste`** — format output for wherever it's going (email/Slack/GitHub/terminal).

That's it. No marks, no counts, no adverbs. "carefully work the flaky auth tests across all
repos" is a complete instruction. (One recognized exception: the `scope+=X`/`scope-=X`/
`scope=X` operators that modify a tool's default self-scope — see `~/.claude/CLAUDE.md`.)

## The loop

```
orient  →  work  →  land ── PR ──▶ .github pipeline (merges greens, rebases reds on its own)
   ▲         │
   └─────────┘   dispatch only when you want the pipeline to do it, or to hold/steer it
```

1. **orient** — start here; see what's off at your locus.
2. **work** — take the top unit end-to-end; push+PR is the default landing.
3. The pushed PR enters the **pipeline** automatically (green→merge, red→rebase→autofix).
4. **dispatch** — occasional: seed the pipeline with issues to build unattended, or
   stop/steer it (`hold` + cron toggle) for surgery, then reenable.

## The two things running at once

- **You**, locally, in-thread — `orient`/`work`. Watched, worktree-isolated. 90% of the time.
- **The pipeline**, in the cloud — three continuous crons in `SuxOS/.github`, building and
  merging whatever's filed, whether you or the bot filed it. Always on; `dispatch` steers it.

They're not modes to choose between. You work; the pipeline runs.

## The substrate

- **`~/.claude/fabric.json`** — the one declared truth: `workspace_root`, `orgs` (each with
  its `repos` + a `pipeline` pointer). Every tool reads it; nothing hardcodes a second copy.
  Edit it when a repo or org opts in/out — that's the only place it changes.
- **`home/.claude/hooks/`** — the cardinal rails as code. `require-delegation-model` (live)
  blocks a subagent with no explicit model. `verify-completion-claim` (built, off) blocks
  "done" with no verification — arm it when you trust it (`hooks/README.md`).
- **Security model** — one taxonomy, local and cloud: **Tier A** (irreversible/destructive,
  secret egress) blocks, human hands only; **Tier B** (everything else) ships and rolls
  back; **`hold`** is the one pipeline write-gate. Defined in
  `SuxOS/.github/docs/design/three-loop-pipeline.md`.

## Setup

```
git clone git@github.com:SuxOS/claude-config.git ~/Code/SuxOS/claude-config
~/Code/SuxOS/claude-config/install.sh    # symlinks CLAUDE.md, skills/, fabric.json into ~/.claude
```

- `gh` CLI: authenticated, works now. GitHub MCP (`mcp__github__*`): plugin enabled, needs
  `GITHUB_PERSONAL_ACCESS_TOKEN` to connect; `gh` is the working fallback until then.
- Hooks: `install.sh` symlinks the dir; merge the `hooks` block from the reference
  `settings.json` into your live `~/.claude/settings.json` and restart.
