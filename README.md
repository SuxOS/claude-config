# claude-config

Colin's personal Claude Code configuration — cardinal rules (`CLAUDE.md`) and the
locus-aware tools (`skills/`) — as a versioned repo instead of unversioned dotfiles
under `~/.claude`.

**Why this lives in the SuxOS org:** it's a personal, cross-project tool-config
repo, not a SuxOS product or component — it sits here for convenience/visibility
alongside the other repos it's used against (see `fabric.json`'s `orgs.SuxOS.repos`
for the current list), not because it's part of the product surface.

**New here? Read [`WORKFLOW.md`](WORKFLOW.md)** — the development loop in one screen
(orient → work → land), the three loci, and setup. Design rationale lives in
[`docs/superpowers/specs/`](docs/superpowers/specs/).

## Layout

```
home/.claude/
  CLAUDE.md       cardinal rules + the tools, loaded into every session
  fabric.json     one declared truth: workspace_root, orgs (repos + pipeline pointer), bot
  skills/         orient · work · dispatch · paste · how · retro  (+ AUTHORING.md)
  hooks/          cardinal rails as code (see hooks/README.md for the current live/disabled list)
  settings.json   reference snapshot only — NOT symlinked (see below)
  settings.README.md  what actually enforces under bypassPermissions (deny-only) + rule semantics
WORKFLOW.md       the development loop — start here
```

The tools are organized by **locus** (workspace ⊃ org ⊃ repo), not by a punctuation
grammar: `orient` (see), `work` (do), `dispatch` (send to the autonomous `.github`
pipeline), `paste` (format). `how` is a meta helper — find the right skill/MCP/agent for a
goal — not locus-scoped like the other four. `retro` is session-scoped, not locus-scoped
either — an end-of-session harvester that proposes doc edits for lessons learned. The cloud pipeline itself lives in
`SuxOS/.github` and is never duplicated here — `fabric.json`'s `pipeline` only points at it.
(One recognized exception: the `scope+=X`/`scope-=X`/`scope=X` operators — see
`~/.claude/CLAUDE.md`.)

`~/.claude/CLAUDE.md`, `~/.claude/skills`, and `~/.claude/fabric.json` are symlinks
into this repo, so edits made live (by Claude or by hand) land directly in git —
`git status`/`git diff` in this repo show what changed.

`settings.json` is copied, not symlinked: Claude Code rewrites it in place
(permissions grants, plugin state, etc.), which would fight a symlink. Treat the
copy here as a reference/backup; sync changes over manually when they're worth
keeping.

Its `permissions.deny` list runs under `bypassPermissions` and is a defense-in-depth
speed bump, **not** a real egress boundary — see
[`docs/security-model.md`](docs/security-model.md) for the threat model and why.

Everything else under `~/.claude` (sessions, cache, daemon state, telemetry,
plugin marketplaces, history) is machine/runtime state and intentionally not
tracked here.

## Setup on a new machine

```
git clone git@github.com:SuxOS/claude-config.git ~/Code/SuxOS/claude-config
~/Code/SuxOS/claude-config/install.sh
```

`install.sh` is idempotent — safe to re-run after pulling changes. If you already have a
`settings.json`, a re-run only prints any deny rules / hook commands it's missing relative
to the repo reference — pass `--apply` (or `--merge`) to patch them in directly, preserving
anything you've added yourself.

For a reproducible dev toolchain (python3 + ruff + shellcheck + shfmt, matching CI), run
`nix develop` (or let direnv pick up `.envrc` automatically).
