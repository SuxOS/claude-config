# Two-account model: human (m@) + bot (claude@)

Run the interactive identity (**m@colinxs.com**) out of `~/.claude`, and a separate autonomous
**bot** identity (**claude@colinxs.com**) out of `~/.claude-bot`. Never log both into one config
dir again — that dual-account clobber is what wiped the live safety layer (see
`suxos-claude-code-config-reorg-2026-07-21`).

## Verified mechanics (Claude Code docs, 2026-07-21)

- **`CLAUDE_CONFIG_DIR` is the isolation lever.** It relocates the *entire* `~/.claude` tree —
  settings, hooks, memory, plugins, skills, sessions, `~/.claude.json` state — for a CLI run. It
  only moves the **user-scope** settings layer; managed/CLI-flag/project/local settings are
  untouched. (docs: claude-directory, agent-view, settings.)
- **The bot is CLI-only.** The desktop app does **not** honor `CLAUDE_CONFIG_DIR` (the only way to
  give it a second identity is the unsupported Electron `--user-data-dir` hack — don't). Run the
  bot as `CLAUDE_CONFIG_DIR=$HOME/.claude-bot claude` in its own terminal, logged in as claude@.
- **macOS Keychain isolation is UNVERIFIED.** Credentials live in the Keychain, not a file, on Mac.
  Community reverse-engineering says the Keychain service name is derived from a sha256 of the
  config-dir path (so each `CLAUDE_CONFIG_DIR` gets its own credential entry), but Anthropic's docs
  don't confirm it. **Verify at bot-login:** after logging in claude@ under `~/.claude-bot`, run
  `security find-generic-password -s "Claude Code-credentials"` and its hashed-suffix siblings and
  confirm two distinct entries (m@ + claude@). If they collide, the two identities can't coexist on
  this Mac and the bot must run on a separate machine / CI.
- **Cloud routines always run as their creating account — no cross-account visibility.** A routine
  created by m@ runs as m@; one created by claude@ runs as claude@. Neither account can natively
  see the other's routines. Cross-identity status must flow through a **shared external channel**
  (GitHub) — same shape as the existing `suxbot[bot]` pipeline signal.

## Config: two variants, same guards

`install.sh` ships both identities from one source tree:

- `home/.claude/settings.json` — **human** (m@): full interactive plugin set, notifications, theme.
- `home/.claude/settings.bot.json` — **bot** (claude@): **an empty `permissions.deny` and the same
  PreToolUse/PostToolUse hook rails** as the human config ("guards-in-both" — the rails protect the
  autonomous agent under `bypassPermissions` regardless of identity, and since the 2026-07-22 owner
  decision emptied `deny` in both identities they are now the only automated gate; see
  [`docs/security-model.md`](../../docs/security-model.md)). The old "identical `permissions.deny`
  (62 rules)" exact-parity claim no longer holds — parity is now "both empty". `permissions.allow`
  is unchanged and stays inert under `bypassPermissions`. Otherwise a lean headless plugin
  set (sux, superpowers, security-guidance, semgrep, commit-commands, claude-md-management,
  code-review, typescript-lsp, cloudflare, grafana), connectors off, and no notification/theme
  keys (nobody watches a bot's screen). Both reference the shared `$HOME/.claude/hooks` copies.

Install per identity:

```bash
./install.sh                                    # human → ~/.claude
CLAUDE_CONFIG_DIR="$HOME/.claude-bot" ./install.sh --bot   # bot → ~/.claude-bot
```

`--bot` (or any `CLAUDE_CONFIG_DIR` whose dir name ends in `-bot`) copies `settings.bot.json` to
`$DEST/settings.json` and symlinks the shared hooks/skills/CLAUDE.md/fabric into the bot dir.

## Trust posture (owner directive 2026-07-21)

The bot is trusted like the interactive session — *"I trust the bot as much as I trust you in this
session where you're running largely unsupervised."* So it keeps the SAME **painless** guards as
the human (identical empty `permissions.deny` + the hook rails, now the sole automated gate —
these protect the agent regardless of identity) but is deliberately NOT extra-locked-down: marketplaces `autoUpdate:true` (trusted
vendors), allow-dangerous (`skipDangerousModePermissionPrompt`), and **no config-tamper guard**.
Friction hardening that would make the owner babysit the bot was explicitly declined — see
`suxos-security-friction-principle`. (Residual risk accepted knowingly: an unattended bot with
`Write`/`Edit` over symlink-shared hooks *could* be induced to edit a rail; the owner trusts it not
to, the same way this interactive session is trusted.)

## Bootstrap (one-time, human step)

1. `CLAUDE_CONFIG_DIR="$HOME/.claude-bot" ./install.sh --bot`
2. `CLAUDE_CONFIG_DIR="$HOME/.claude-bot" claude` → log in as **claude@colinxs.com**.
3. Verify Keychain isolation (above). Verify the bot's `gh` auth is claude@'s (or the suxbot token)
   and NOT m@'s.
4. Sanity-check the bot session loads `settings.bot.json` (lean plugins, deny+hooks present).

## Routine migration (observer pattern)

Current local scheduled tasks (in `~/.claude/scheduled-tasks/`) split by visibility:

| Routine | Cadence | Visibility | New home |
|---|---|---|---|
| `suxos-dev-brief` | daily 07:07 | **visible** (Colin reads it) | m@ **cloud** routine |
| `suxos-life-brief` | daily 06:47 | **visible** | m@ **cloud** routine |
| `suxos-graduate-ready` | manual | **visible** (dispatches ready items) | m@ (manual, unchanged) |
| `life-weekly-consolidate` | weekly Sun 04:32 | **invisible drudge**, vault-touching | **bot** (claude@) — stays local under `~/.claude-bot` |
| `bot-monitor` (**new**) | daily | **visible** | m@ **cloud** routine — surfaces bot status |

**Observer pattern (because m@ can't see claude@'s routines):** the bot's `life-weekly-consolidate`
run ends by writing a heartbeat/status to a **shared GitHub channel** — append a comment (last-run
timestamp, GREEN/AMBER, one-line summary, any needs-human) to a fixed tracking issue in the vault
or `SuxOS/.github` (e.g. a `bot: claude@ status` issue). The new m@ `bot-monitor` cloud routine
reads that issue via `gh` each morning and folds "bot ran / bot needs you" into the dev-brief. No
cross-account API is needed — GitHub is the bridge, exactly as `suxbot[bot]` PRs already bridge the
pipeline.

**Migration steps (after bootstrap):**
1. Recreate `suxos-dev-brief` and `suxos-life-brief` as **cloud** routines under m@ (the `schedule`
   skill), same prompts/cadence as the local `SKILL.md`s, then delete the local scheduled tasks so
   they don't double-run.
2. Move `life-weekly-consolidate` to the bot: in the `CLAUDE_CONFIG_DIR=~/.claude-bot` session,
   create it there (local scheduled task under the bot), and delete it from `~/.claude`. Add the
   "write status to the tracking issue" step to its prompt.
3. Create the m@ `bot-monitor` cloud routine that reads the tracking issue and surfaces bot status.
4. Leave `suxos-graduate-ready` as-is (manual, m@).

> ⚠️ Do the local↔cloud cutover carefully to avoid double-runs of the daily briefs (create cloud,
> confirm it fires once, then delete the local task). This is why the migration is a deliberate
> human step, not an autonomous one.
