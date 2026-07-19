# Real-shape hook fixture corpus (#117)

A large share of the hook bug history is **one** root cause: the hooks under
`home/.claude/hooks/` parse real Claude Code tool-input / transcript JSON and repeatedly get the
*shape* wrong — substring-matching the whole blob (#62), mistaking tool-result records for the
turn boundary (#80), matching `tool_use` inputs instead of prose (#108), reading `gh api` field
flags as writes (#111), bundled short-flags (#105), versioned interpreters (#112).

`tests/test_hooks.sh` layer 2 exercises the hooks with **hand-authored synthetic JSON** — the
same shape the author already guessed. A wrong guess in the hook and a matching wrong guess in
the test pass together, so the synthetic suite structurally *cannot* catch this bug class.

This corpus is the fix: fixtures captured (and redacted) from the **real** Claude Code envelope
shapes, driven by `tests/run_fixture_corpus.py` (layer 3), asserting each hook's exit-code
contract (2 = block, 0 = allow) against them. A schema drift that breaks a hook now fails CI here
instead of surfacing at runtime as a wedged session or a silently-neutered gate.

## Layout

```
tests/fixtures/
  manifest.json          # cases: {hook, stdin|transcript, expect_exit, desc}
  pretooluse/*.json      # full PreToolUse hook-input payloads (Bash + Agent)
  transcripts/*.jsonl    # Stop-hook transcript turns (post-Edit, /verify, /bet, /run)
  README.md              # this file
```

Two payload families, matching the two hook event types:

- **PreToolUse hook-input** (`pretooluse/*.json`) — one JSON object piped to the hook on stdin.
  Real shape: `session_id`, `transcript_path`, `cwd`, `hook_event_name: "PreToolUse"`,
  `tool_name`, `tool_input`. `require-delegation-model.py` reads `tool_name` + `tool_input`
  (`subagent_type`, `model`); `block-egress.py` reads `tool_name` + `tool_input.command`.
  The subagent launcher has shipped under both `tool_name` values `"Agent"` (current) and
  `"Task"` (historical), so the hook and the settings matcher (`"Agent|Task"`) accept either,
  and the corpus pins a delegation under each name (#138). If a live capture ever shows a
  third name, widen `SUBAGENT_TOOL_NAMES` and the matcher in lockstep and add a fixture here.
- **Stop-hook transcript** (`transcripts/*.jsonl`) — JSONL, one record per line, the session
  transcript. The runner synthesizes the Stop envelope (`stop_hook_active: false`,
  `transcript_path` pointing at the fixture) and pipes that. `verify-completion-claim.py` reads
  the transcript: it walks back to the last genuine user message (skipping `tool_result`
  carriers), collects `Edit`/`Write` `file_path`s, extracts the final assistant text, and scans
  the turn for a verification command.

`block-checkout-held-branch.py` additionally reads LIVE `git worktree list` state from the
fixture's `cwd`, which a static JSON file can't capture (#170). Its `pretooluse/bash-checkout-
*.json` fixtures use a `"cwd": "__HELD_BRANCH_REPO__"` placeholder and set `"cwd_template":
"held_branch_repo"` on their manifest case; the runner swaps the placeholder for a throwaway repo
it builds (branch `held` checked out in a second worktree) before piping the fixture, then tears
the repo down after the run.

## Adding a case

1. Drop the fixture under `pretooluse/` (a full hook-input object) or `transcripts/` (JSONL).
2. Add a case to `manifest.json`: `hook` (a file under `home/.claude/hooks/`), `stdin` **or**
   `transcript` (path relative to `tests/fixtures/`), `expect_exit` (2 block / 0 allow), `desc`.
3. Run `bash tests/test_hooks.sh` — layer 3 runs the corpus. `json-validate` (CI) also parses
   every `*.json` here; `*.jsonl` is exempt from it (JSONL is not single-document JSON).

## Regenerating / capturing real payloads

The fixtures here are **redacted best-known shapes**, not live captures. To refresh them against
a specific Claude Code version (do this whenever the schema is suspected to have drifted):

1. **Capture PreToolUse inputs.** Temporarily point the matcher at a tee instead of the hook, in
   a throwaway `settings.json`:

   ```json
   { "type": "command", "command": "cat >> /tmp/pretooluse-capture.jsonl" }
   ```

   Then run the tool forms you want to pin (a `Bash` egress one-liner, a `gh api` write, an
   `Agent`/`Task` delegation with and without `model=`). Each stdin blob is appended as one line.
2. **Capture the transcript.** It already exists on disk — find it via the `transcript_path`
   field of any captured PreToolUse input (or under `~/.claude/projects/<project>/<session>.jsonl`).
   Copy the turn(s) you care about: a post-`Edit` turn, and the exact records for `/verify`,
   `/bet`, `/run` invocations.
3. **Redact** before committing — the corpus is public. Scrub real paths (→ `/home/user/...`),
   `session_id`/`sessionId`/UUIDs (→ zeros or `11111111-...`), any tokens/secrets, and real repo
   or org names (→ `example-org/example-repo`). Keep the *structure* (keys, nesting, block types)
   byte-for-byte — that structure is the thing under test.
4. Update `manifest.json` and re-run `bash tests/test_hooks.sh`.

## Resolved — #109 (slash-command invocation record shape) / #83 (mention vs. execution)

`verify-completion-claim.py` used to treat a `/verify`, `/bet`, or `/run` substring ANYWHERE in
the serialized turn as evidence a verification ran — including a bare mention in assistant prose
("I'll confirm with /verify before calling it done") with no actual tool call behind it. #83
replaced that blob-wide regex with `verification_ran()`, which walks the turn's `tool_use` blocks
directly: a `Bash` call whose command matches a verify command, a `SlashCommand` call whose
`input.command` starts with `/verify`/`/bet`/`/run`, or a `Skill` call whose `input.skill` names
one of them — captured against a live session as the real invocation shapes (#109). The
`edit-claim-*-slash.jsonl` fixtures now pin the corrected behavior: a slash command named only in
prose, with no matching tool_use, is NOT evidence and the hook blocks (`expect_exit: 2`).
`verify-slash-invocation-only.jsonl` still allows, but only because that turn edits no product
code at all — the hook never reaches the verification check.
