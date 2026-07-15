# Hooks — the cardinal rails, enforced

Prose in CLAUDE.md is the weakest enforcement: the rails that matter most are the ones a model
drifts from *under pressure*. These hooks move a couple of them from aspiration to guarantee.
install.sh symlinks this dir to `~/.claude/hooks/`; settings.json wires the live ones.

## Live

- **`require-delegation-model.py`** — PreToolUse (matcher `Agent`). Enforces cardinal rule #1
  (never inherit the model): blocks an `Agent` delegation with no explicit `model=` so every fork
  picks its tier deliberately. Exempts `subagent_type=fork` (inherits by design). Wired in
  settings.json under `hooks.PreToolUse`.

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
