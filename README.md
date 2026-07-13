# claude-config

Colin's personal Claude Code configuration — cardinal rules (`CLAUDE.md`) and the
custom skill/command verb grammar (`skills/`, `commands/`) — as a versioned repo
instead of unversioned dotfiles under `~/.claude`.

## Layout

```
home/.claude/
  CLAUDE.md       cardinal rules, loaded into every session
  skills/         the go/wtf/fix/bug/... verb family
  commands/       fixer/triage/issue-build
  settings.json   reference snapshot only — NOT symlinked (see below)
```

`~/.claude/CLAUDE.md`, `~/.claude/skills`, and `~/.claude/commands` are symlinks
into this repo, so edits made live (by Claude or by hand) land directly in git —
`git status`/`git diff` in this repo show what changed.

`settings.json` is copied, not symlinked: Claude Code rewrites it in place
(permissions grants, plugin state, etc.), which would fight a symlink. Treat the
copy here as a reference/backup; sync changes over manually when they're worth
keeping.

Everything else under `~/.claude` (sessions, cache, daemon state, telemetry,
plugin marketplaces, history) is machine/runtime state and intentionally not
tracked here.

## Setup on a new machine

```
git clone git@github.com:SuxOS/claude-config.git ~/Code/claude-config
~/Code/claude-config/install.sh
```

`install.sh` is idempotent — safe to re-run after pulling changes.
