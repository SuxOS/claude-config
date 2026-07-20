# settings.json — what actually enforces

`settings.json` mixes *descriptive intent* with *enforced policy*, and under this repo's
default mode they are not the same list. This is the map of which is which, verified against
the Claude Code docs ([permissions], [permission-modes], [mcp]) so future wildcard-scoping and
deny-rule work is done against the real matcher, not a guessed one.

## The one rule: under `bypassPermissions`, only `deny` gates

`defaultMode` here is `bypassPermissions`. In that mode **only `permissions.deny` (plus explicit
`ask` rules, org-`ask` connector tools, and MCP tools marked `requiresUserInteraction`) is
enforced.** `permissions.allow` and every entry under `autoMode.allow` are **inert** — everything
not denied already runs unconfirmed, so the allow lists grant nothing and block nothing.

Evaluation order is **`deny` → `ask` → `allow` → mode fallback**; first match wins, specificity
does not reorder it. A broad deny beats a narrow allow (`Bash(aws *)` deny blocks even if
`Bash(aws s3 ls)` is allowed), so deny rules can't carry allowlist exceptions. Deny from any
settings scope beats allow from any scope.

Consequences for editing this file:
- The `permissions.allow` list and the hand-written Tier A/B prose in `autoMode.allow` are
  **documentation of intent, not a control.** Changing them changes nothing a default session
  does. To make an intended restriction real, it must land in `permissions.deny`, a `PreToolUse`
  hook (see `hooks/`), or by dropping `bypassPermissions`.
- Circuit breakers still fire in bypass mode: Claude Code's built-in protection is documented to
  prompt for `rm -rf /`, `rm -rf ~`, and writes to protected paths (`.git`, `.claude`, …) regardless
  of `bypassPermissions`. **That has only actually been confirmed for an interactive session with a
  human present to answer the prompt (#342) — it is UNVERIFIED for a headless/autonomous session**
  like this repo's own builder pipeline (`defaultMode: bypassPermissions`, nobody attached to
  answer). "Prompt" is meaningless with no human there; whether it silently no-ops, auto-approves,
  or genuinely blocks in that mode has not been tested live. Treat this bullet as an unverified
  assumption for autonomous sessions specifically, not a settled fact — the same class of trap as
  this file's own Cloudflare MCP mapping below (confirmed from primary source, not eyeballed live)
  — the mechanical `PreToolUse`
  rails under `hooks/` (see hooks/README.md) are this repo's actually-verified belt for anything
  that matters in that mode, independent of whether this built-in prompt also fires.

## Bash deny rules are anchored globs, not prefixes — and can't constrain arguments

A Bash rule like `Bash(tar *)` is an **anchored glob over the whole command string**. `*` matches
any run of characters *including spaces*, so `Bash(git * main)` matches both `git checkout main`
and `git log --oneline main`. The space matters: `Bash(ls *)` matches `ls -la` but not `lsof`;
`Bash(ls*)` matches both. `:*` is an equivalent trailing wildcard **only at the end of a pattern**
(`Bash(ls:*)` == `Bash(ls *)`); a `:` mid-pattern is a literal.

So a deny written to target a flag — e.g. `Bash(tar *x*)` to block extraction — is a trap: it
matches *any* `tar` command containing the character `x` anywhere (it blocks `tar -zxf`, but by
accident, and it also blocks unrelated commands), and it is trivially evaded. **Argument-
constraining Bash rules are fragile by design** (the docs say so): flag reordering, `VAR=url &&
cmd $VAR`, command substitution `$(…)`, extra spaces, and wrapper/interpreter indirection
(`env tar …`, `bash -c "…"`, `sh -c "…"`) all slip past literal-text matching. Claude Code does
split compound commands on `&& || ; | |& &` and newlines and matches each piece independently, and
it strips the wrappers `timeout/time/nice/nohup/stdbuf/xargs` before matching — but nothing else.

Practical rule for this file: **deny a dangerous tool outright** (as with `curl`/`ssh`/`scp`) rather
than trying to allow-a-safe-subset by argument pattern. A prefix/argument deny that looks scoped but
isn't is worse than a known-open wildcard, because it reads as fixed. (Note the standing gap: an
outright `curl`/`ssh` deny is still porous while `Bash(node *)`, `Bash(python3 *)`, and `Bash(npm *)`
can open sockets themselves — real egress control needs sandboxing or a hook, not Bash denies.)

## MCP deny identifiers must match the *plugin-namespaced* tool name exactly

MCP rules are `mcp__<server>__<tool>`. But tools from a **plugin-bundled** MCP server (everything
in `enabledPlugins` here) are addressed as **`mcp__plugin_<plugin>_<server>__<tool>`** — the plugin
name *and* the server key from the plugin's `.mcp.json`, not the plugin name alone. A deny that
omits the `plugin_…` prefix or uses the wrong server key **never matches, silently fails open, and
emits no startup warning** — the "unknown tool name" typo check exempts any identifier containing
`_` or `*`, which is all of them. This is the MCP analogue of the Bash-glob trap above: verify
against the live tool surface (`/mcp`, or the server's registered `tools/list`) before trusting a
deny. Deny rules may glob the server segment (`mcp__*`, `mcp__*__*_delete`); allow rules may not.

### Verified Cloudflare mapping (for any future destructive-MCP deny)

The `cloudflare` plugin's `.mcp.json` registers the delete tools under the **`cloudflare-bindings`**
server (the "Workers Bindings" remote, `bindings.mcp.cloudflare.com`), tool names confirmed from
`cloudflare/mcp-server-cloudflare` source. The correct deny identifiers are therefore:

    mcp__plugin_cloudflare_cloudflare-bindings__r2_bucket_delete
    mcp__plugin_cloudflare_cloudflare-bindings__kv_namespace_delete
    mcp__plugin_cloudflare_cloudflare-bindings__d1_database_delete
    mcp__plugin_cloudflare_cloudflare-bindings__hyperdrive_config_delete

The bare `mcp__cloudflare__r2_bucket_delete` form is **wrong** and would fail open. Because this
build environment cannot connect the MCP to run `/mcp`, the tool names and the namespacing rule are
confirmed from primary source but the exact runtime string has not been eyeballed live — confirm in
a session with the plugin connected before relying on these as the actual gate.

### A `PreToolUse` rail now covers Tier-A MCP calls generally, not just Cloudflare (#260)

The exact-name deny above only exists for the one plugin someone hand-audited; every other enabled
plugin (notably `github@claude-plugins-official`, whose server exposes `merge_pull_request`,
`push_files`, `delete_file`) had zero coverage. `home/.claude/hooks/block-destructive-mcp.py`, wired
under `hooks.PreToolUse` with matcher `mcp__.*__.*` (verified against the docs' matcher-syntax table
— `mcp__.*` alone is a no-op: without a second `.*` after the trailing `__` it still contains only
exact-match characters and matches nothing), pattern-matches Tier-A verbs (`merge`/`delete`/`push`/
`force`/`publish`/`deploy`) in a tool name's final segment and blocks unconditionally on a hit. This
needs no live-verified tool/server names — it works from the tool name's shape alone — so it covers
every plugin's destructive surface today, not just the ones someone has audited. It is narrower than
an exact-name deny in one direction (doesn't catch `create`/`update`/`edit`), so the Cloudflare
mapping above stays in place rather than being replaced by it.

[permissions]: https://code.claude.com/docs/en/permissions
[permission-modes]: https://code.claude.com/docs/en/permission-modes
[mcp]: https://code.claude.com/docs/en/mcp
