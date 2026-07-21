# Hooks — the cardinal rails, enforced

Prose in CLAUDE.md is the weakest enforcement: the rails that matter most are the ones a model
drifts from *under pressure*. These hooks move a couple of them from aspiration to guarantee.
install.sh symlinks this dir to `~/.claude/hooks/`; settings.json wires the live ones.

## Live

- **`require-delegation-model.py`** — PreToolUse (matcher `Agent|Task`). Enforces cardinal rule #1
  (never inherit the model): blocks an `Agent` delegation with no explicit `model=` when
  `subagent_type` is absent, `general-purpose`, or `claude` — the generic cases that silently
  inherit the orchestrator's session model. Exempts `subagent_type=fork` (inherits by design) and
  any other NAMED subagent_type (e.g. `Explore`, `Plan`, `code-reviewer`), since those resolve
  their model from their own agent definition and omitting `model=` there is the recommended,
  rule-compliant usage. Wired in settings.json under `hooks.PreToolUse`.
- **`pretooluse-bash.py`** — PreToolUse (matcher `Bash`). The single envelope dispatcher for every
  Bash-command rail (#163): reads `json.load(sys.stdin)` ONCE, guards `tool_name != "Bash"` and a
  non-string `tool_input.command` ONCE, then runs a registered list of pure `check(command, cwd) ->
  message | None` predicates — one per rail, defined in and testable from the rail's own module —
  and prints+exits 2 on the first hit. This is the only entry wired in settings.json under
  `hooks.PreToolUse` for the `Bash` matcher; the five rails below are loaded by it (via
  `importlib`, since their filenames are hyphenated) rather than run as separate hook processes.
  Each stays directly runnable via stdin for the manual-test recipe below and its own entry in
  `tests/test_hooks.sh`. Add a new rail by giving its module a `check(command, cwd)` function and
  registering its module name in `pretooluse-bash.py`'s `_RAIL_MODULES` tuple — `_load_checks()`
  loads each module independently and drops one that fails to even import, so a broken rail
  degrades to "not enforced" rather than crashing the dispatcher for every Bash call (#180).
- **`block-egress.py`** — the egress speed bump the security stream keeps pointing at (#77,
  docs/security-model.md): parses the command's argv and blocks the two obvious egress forms no
  `permissions.deny` rule can catch — interpreter/shell inline-code one-liners that open a socket
  (`python3 -c 'import urllib…'`, `node -e 'fetch(…)'`, `bash -c '…curl…'`) and `gh api` **writes**
  in any argv position (`gh api /repos/O/R -X DELETE`, which slips the prefix deny). **Honest about
  being a speed bump, not a seal** — base64/obfuscated payloads and file-fed code still pass; a real
  boundary needs OS-level network sandboxing. Registered with `pretooluse-bash.py` via its
  `check(command, cwd)`; fails open on any error.
- **`block-checkout-held-branch.py`** — enforces the git-checkout-vs-worktree cardinal rail
  (CLAUDE.md dev-speed tactics, #123): `git checkout <branch>` / `git switch <branch>` raises a
  **loud `fatal: ... already used by worktree` error, exit 128** — not a silent no-op — when that
  branch is already checked out in another worktree, wasting a turn re-diagnosing it (#210). Parses
  the command for a
  real single-branch switch (not creation `-b`/`-c`, not `--detach`, not a `--` path restore),
  consults `git worktree list` for the invoking cwd, and blocks with guidance (work in that worktree,
  or add a detached scratch worktree) when the target is held elsewhere. Registered with
  `pretooluse-bash.py` via its `check(command, cwd)`; fails open on any error.
- **`block-sleep-loop.py`** — flags a `sleep`-based polling loop (CLAUDE.md dev-speed tactics:
  "never poll in a loop — block on one `--watch`/`wait` call instead", #181). Fires only when the
  command has BOTH a loop-opening piece (`while`/`until`/`for`) and a `sleep` piece — a bare
  `sleep N` with no loop is a common, legitimate delay and is left alone. Registered with
  `pretooluse-bash.py` via its `check(command, cwd)`; fails open on any error.
- **`block-suppressed-stderr.py`** — flags a command that redirects stderr to `/dev/null`
  (`2>/dev/null`/`&>/dev/null`, and their `>>`-appending variants, plus the order-sensitive
  `>/dev/null 2>&1` idiom, #201; CLAUDE.md dev-speed tactics: "don't suppress a command's stderr if
  you might need it to diagnose", #181). Matches on the raw command text (not tokenized argv) so it
  can require the fd digit be glued to the `>` with no space — the same adjacency rule the shell
  itself uses to tell a real `2>` fd-redirect from an ordinary word `2` followed by an unrelated `>`
  (e.g. `ffmpeg -loglevel 2 > /dev/null`).
  Registered with `pretooluse-bash.py` via its `check(command, cwd)`; fails open on any error.
- **`block-destructive-git.py`** — enforces the work skill's Tier-A rail in prose (home/.claude/
  skills/work/SKILL.md: "never force-push, merge/publish without confirmation, hard-delete, or do
  anything irreversible/destructive without an explicit yes", #230, #242). Eight narrowly-scoped
  predicates, each checked against every relevant `git` piece of the command, seven of them
  conservative the same way block-checkout-held-branch.py is (a missed detection is a harmless
  allow; nothing they can't confidently resolve is ever blocked): `git push -f`/`--force` that is provably NOT a
  fast-forward of the remote-tracking ref known locally (a force-push to a brand-new branch, or
  one that's still an ancestor relationship, is left alone — `--force-with-lease` is also always
  allowed, it's git's own safe form); `git reset --hard` over a working tree with uncommitted
  TRACKED changes (a clean tree has nothing to lose); `git clean` with a force flag where a `-n`
  dry run with the same flags shows it would actually remove something; `git branch -D`/`--delete
  --force` on a branch NOT fully merged into HEAD (one that `-d` would already have deleted safely
  is left alone); `git checkout -- .`/`git restore .` discarding the WHOLE tree (not a single-file
  discard) while it has uncommitted tracked changes; and `git stash drop`/`git stash clear` when
  `git stash list` isn't already empty (#239). The seventh, `gh pr merge`/`gh release create`
  (unless `--draft`)/`npm publish` (unless `--dry-run`), has no repo state to consult and so fires
  unconditionally on a match instead (#242). The eighth, a bare `git push` straight to a branch
  GitHub reports as protected, asks `gh api repos/<owner>/<repo>/branches/<branch>/protection`
  rather than guessing from the branch name — `<owner>`/`<repo>` are resolved from the SPECIFIC
  remote the push argv targets (`git remote get-url <remote>`), not `gh`'s own ambient default-repo
  context, which can diverge in a fork workflow (#264) — this hook installs into every repo the
  user works in and plenty push straight to `main` with no PR workflow at all, so a blanket name
  match would be false-positive-prone (#242) — and fails open (not protected) on an unresolved
  destination, missing `gh`/auth, an unparsable/non-GitHub remote URL, or any API error (#252).
  Registered with `pretooluse-bash.py` via its `check(command, cwd)`; fails open on any error.

- **`block-destructive-mcp.py`** — PreToolUse (matcher `mcp__.*__.*`). Extends the Tier-A cardinal
  rail to MCP tool calls (#260): every other destructive-action guard here only inspects Bash argv
  text, so an MCP tool call (e.g. the GitHub plugin's `merge_pull_request`/`push_files`/
  `delete_file`) had zero enforcement under `bypassPermissions`. Splits `tool_name` on the last `__`
  to isolate the real tool name from its server/plugin namespace, then blocks if any `_`/`-`
  separated token in it exactly matches a Tier-A verb (`merge`, `delete`, `push`, `force`,
  `publish`, `deploy`) — the same pattern-match-the-name approach as the Bash rails, generalized so
  it covers every current and future MCP plugin instead of a hand-maintained per-plugin
  enumeration. Also scans `tool_input["method"]`/`["action"]` for the same verb set (#358), so a
  consolidated tool that bundles several actions behind one generic name (e.g. GitHub's
  `label_write`, `method: "delete"`) is still caught even when `tool_name` itself carries no
  destructive token. No repo state can prove such a call safe and there's no human to confirm in an
  autonomous session, so a match blocks unconditionally (mirrors `block-destructive-git.py`'s
  merge/publish predicate). `create`/`update`/`list`/`get` tools are out of scope — not Tier-A on
  their own. Fails open on any error or unrecognized tool-name/tool-input shape.
- **`block-web-egress.py`** — PreToolUse (matcher `WebFetch|WebSearch`). Extends the egress rail to
  the native web tools (#360): neither had a hook nor a deny rule, even though block-egress.py's own
  block message points bypassed Bash egress traffic AT them. Reads `tool_input.url` (WebFetch's
  fetch target — WebSearch's `query` has no URL to check) and blocks on a non-http(s) scheme or a
  LITERAL loopback/link-local/private/reserved IP target or known metadata hostname (covers the
  169.254.169.254 cloud-metadata address, since it's link-local) — no DNS resolution performed, so a
  hostname that merely resolves to one of these is invisible here, same "speed bump, not a seal"
  honesty as block-egress.py. No repo state can prove a fetch target safe and there's no human to
  confirm in an autonomous session, so a match blocks unconditionally. Fails open on any error or
  unrecognized shape.
- **`block-write-overwrite.py`** — PreToolUse (matcher `Write`). Blocks a blind full-file overwrite
  of a git-tracked file that has uncommitted staged-or-unstaged changes (#364): every other
  "discard uncommitted work" guard here is Bash-scoped (block-destructive-git.py's
  `_reset_hard_hit`/`_discard_hit`), but Write fully replaces a file's content with no diff-aware
  merge and had zero enforcement. Runs `git status --porcelain` scoped to `tool_input.file_path` in
  the file's own directory; blocks when the file is tracked AND dirty (any porcelain line other than
  the untracked `??` marker) — reusing block-destructive-git.py's `_working_tree_dirty()` signal,
  scoped to one path. `Edit` is deliberately out of scope (it requires an exact `old_string` match,
  so it can't blindly clobber an unseen change the way Write can). Unconditional on a hit, same
  Tier-A shape as block-destructive-mcp.py. Fails open on any error, a relative `file_path`, or a
  target outside a readable git repo.
- **`audit-git-consequences.py`** — PostToolUse (matcher `Bash`). A complementary, last-resort net
  behind the PreToolUse argv rails above (#236): instead of recognizing a destructive git COMMAND
  before it runs, it snapshots the cwd's branch/remote-tracking ref tips (via `git_out()`/
  `git_returncode()`) after every Bash call and diffs that against the snapshot recorded after the
  PREVIOUS Bash call in the same repo. A ref that disappeared, or moved to somewhere its old tip
  isn't reachable from any current ref, means those commits were just discarded — regardless of how
  the command that did it was spelled, immune by construction to the bundling/wrapper/substitution
  bypass classes the argv rails keep individually patching. PostToolUse can't undo a completed tool
  call, so a hit here only prints a loud stderr warning (exit 2) for the model/user to react to, not
  a block. State is a small per-repo JSON snapshot under `tempfile.gettempdir()`, keyed by a hash of
  the repo's real toplevel path (so parallel worktrees never share a baseline); fails open on
  anything unreadable/unwritable/non-repo. Wired in settings.json under `hooks.PostToolUse`.

## Available but DISABLED by default

- **`verify-completion-claim.py`** — Stop hook. The "no completion claim without fresh evidence"
  rail: blocks stopping when the final message claims done/fixed/passing over edited product code
  and no verification command ran this turn. **Not wired** — a blocking Stop hook is disruptive on
  a false positive, so arm it only after watching it. To enable, add to settings.json `hooks`:

      "Stop": [
        { "hooks": [ { "type": "command", "command": "$HOME/.claude/hooks/verify-completion-claim.py" } ] }
      ]

  Then restart Claude Code. It fails open on any parse error and self-limits via `stop_hook_active`.

  **Shadow mode (#324)** — graduate it from "read the source" to "watch it run" without risking a
  disruptive false positive: wire it as a live Stop hook that only logs, never blocks, by setting
  `VERIFY_COMPLETION_CLAIM_SHADOW=1` in the `command` string itself:

      "Stop": [
        { "hooks": [ { "type": "command", "command": "VERIFY_COMPLETION_CLAIM_SHADOW=1 $HOME/.claude/hooks/verify-completion-claim.py" } ] }
      ]

  Every turn it evaluates appends one JSON line — `{"ts", "transcript_path", "would_fire",
  "reason"}` — to `~/.claude/verify-completion-claim.log` (override the path with
  `VERIFY_COMPLETION_CLAIM_LOG`) instead of exiting 2. Run it passively across real sessions, then
  review the log for false positives (`would_fire: true` on a turn that was actually fine) and
  false negatives (a turn you know should have fired but didn't) before ever dropping the
  `VERIFY_COMPLETION_CLAIM_SHADOW=1` prefix to arm it live. Summarize a log at a glance with:

      python3 -c "
      import collections, json
      c = collections.Counter()
      for line in open('$HOME/.claude/verify-completion-claim.log'):
          c[json.loads(line)['would_fire']] += 1
      print(c)"

## Testing a hook before you trust it

Pipe synthetic hook-input JSON to the script and check the exit code (2 = block, 0 = allow):

    echo '{"tool_name":"Agent","tool_input":{"subagent_type":"claude","prompt":"x"}}' \
      | ~/.claude/hooks/require-delegation-model.py; echo "exit=$?"

This recipe is now automated: `tests/test_hooks.sh` (run in CI inside the required `shellcheck` job) byte-compiles
every hook and asserts each one's exit-code contract — block, fork/model exemptions, malformed-JSON
fail-open. Add a case there when you add or change a hook so the contract stays enforced, not just prose.

The synthetic JSON above is hand-authored, so it shares whatever shape the author guessed — the exact
trap behind the recurring parse-shape bugs (#62/#80/#105/#108/#111/#112). Layer 3 of the same script
additionally drives each hook against a **real-shape fixture corpus** under `tests/fixtures/` (full
PreToolUse payloads + Stop-hook transcript JSONL, captured and redacted from real Claude Code output).
See `tests/fixtures/README.md` for the corpus and how to regenerate/redact it (#117).
