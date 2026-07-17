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

## Known open gap — #109 (slash-command invocation record shape)

`verify-completion-claim.py` treats a `/verify`, `/bet`, or `/run` in the turn as evidence a
verification ran (its `VERIFY` regex matches `/verify\b` etc.). The `edit-claim-*-slash.jsonl`
fixtures pin that via the slash reference appearing in **assistant text / a real `pytest`
`tool_use`** — record shapes that are stable and certain.

What is **not** yet live-validated is the exact record a *user slash-command invocation* writes to
the transcript. `verify-slash-invocation-only.jsonl` uses the best-guess
`<command-name>/verify</command-name>` shape, but its assertion is deliberately shape-robust
(a standalone `/verify` turn edits no product code, so the hook allows regardless of the tag
form). Before arming `verify-completion-claim.py` as a live Stop hook (it ships DISABLED), capture
a real `/verify` / `/bet` / `/run` invocation per step 2 above and confirm whether the recorded
token carries the leading slash — if it does not, the `VERIFY` regex would miss it and the hook
would false-positive. That confirmation is issue **#109**; this corpus is its home.
