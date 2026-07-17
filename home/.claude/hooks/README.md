# Hooks — the cardinal rails, enforced

Prose in CLAUDE.md is the weakest enforcement: the rails that matter most are the ones a model
drifts from *under pressure*. These hooks move a couple of them from aspiration to guarantee.
install.sh symlinks this dir to `~/.claude/hooks/`; settings.json wires the live ones.

## Live

- **`require-delegation-model.py`** — PreToolUse (matcher `Agent`). Enforces cardinal rule #1
  (never inherit the model): blocks an `Agent` delegation with no explicit `model=` when
  `subagent_type` is absent, `general-purpose`, or `claude` — the generic cases that silently
  inherit the orchestrator's session model. Exempts `subagent_type=fork` (inherits by design) and
  any other NAMED subagent_type (e.g. `Explore`, `Plan`, `code-reviewer`), since those resolve
  their model from their own agent definition and omitting `model=` there is the recommended,
  rule-compliant usage. Wired in settings.json under `hooks.PreToolUse`.
- **`block-egress.py`** — PreToolUse (matcher `Bash`). The egress speed bump the security stream
  keeps pointing at (#77, docs/security-model.md): parses the command's argv and blocks the two
  obvious egress forms no `permissions.deny` rule can catch — interpreter/shell inline-code
  one-liners that open a socket (`python3 -c 'import urllib…'`, `node -e 'fetch(…)'`, `bash -c
  '…curl…'`) and `gh api` **writes** in any argv position (`gh api /repos/O/R -X DELETE`, which
  slips the prefix deny). **Honest about being a speed bump, not a seal** — base64/obfuscated
  payloads and file-fed code still pass; a real boundary needs OS-level network sandboxing. Wired
  in settings.json under `hooks.PreToolUse`; fails open on any error.

## Available but DISABLED by default

- **`verify-completion-claim.py`** — Stop hook. The "no completion claim without fresh evidence"
  rail: blocks stopping when the final message claims done/fixed/passing over edited product code
  and no verification command ran this turn. **Not wired** — a blocking Stop hook is disruptive on
  a false positive, so arm it only after watching it. To enable, add to settings.json `hooks`:

      "Stop": [
        { "hooks": [ { "type": "command", "command": "$HOME/.claude/hooks/verify-completion-claim.py" } ] }
      ]

  Then restart Claude Code. It fails open on any parse error and self-limits via `stop_hook_active`.

## Testing a hook before you trust it

Pipe synthetic hook-input JSON to the script and check the exit code (2 = block, 0 = allow):

    echo '{"tool_name":"Agent","tool_input":{"subagent_type":"claude","prompt":"x"}}' \
      | ~/.claude/hooks/require-delegation-model.py; echo "exit=$?"

This recipe is now automated: `tests/test_hooks.sh` (run in CI inside the required `shellcheck` job) byte-compiles
every hook and asserts each one's exit-code contract — block, fork/model exemptions, malformed-JSON
fail-open. Add a case there when you add or change a hook so the contract stays enforced, not just prose.
