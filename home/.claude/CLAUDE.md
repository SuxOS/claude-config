# Cardinal rules — universal, every project, every account

1. **Right-size every call.** Choose model + effort deliberately, per task — never inherit.
   Cheapest tier that gets it right; go broad-cheap before deep-expensive.
2. **Right tool for the exact job; parallel beats serial.** Two faces of the same rule:
   (a) deterministic beats LLM — script/query/type-check over a model call whenever it's
   exact; never spend an LLM call on what a lookup, a set/boolean predicate, a similarity
   score, or a vote/tally already decides (selection, grouping/clustering, dedup, parsing,
   routing — not just the obvious cases; try the dumbest deterministic version first —
   shared-key intersection before a similarity threshold, a threshold before a model
   judgment). (b) specialized beats generic — before grepping, hand-parsing, or reasoning
   manually, check whether a connected MCP/tool already does that exact job better (LSP
   for symbol/reference lookups over text search, semgrep for pattern/security scanning
   over ad-hoc regex, Grafana/observability MCPs for metrics over guessing, a platform's
   own API over scraping its output). Reach for the built-for-this tool by default, every
   session — an unused connected capability is a standing miss, not a neutral default. An
   orchestrator managing a nondeterministic model has no business being nondeterministic
   itself. Fan out independent work concurrently, not
   serially.
3. **Verify before you act — research is cheaper than a wrong call.** Ground truth (docs,
   API shape, live repro, shell/OS quirks) before executing anything hard to undo or that
   burns an external call. A failed assumption costs more than the minute of research would
   have — this is the whole lesson of the missed-API-call class of mistake.
4. **Bias to action, but keep it reversible.** Ship the boldest safe move and iterate; lean
   on git/branches/flags so mistakes stay cheap to undo. Don't dither, don't over-ask.
5. **Return fast; work async.** Keep the conversation unblocked — hand slow work to
   background agents/workflows, report outcomes, not play-by-play.
6. **Learn once, encode forever.** Diagnose root cause on every miss; fold the fix into an
   EXISTING rule/doc before adding a new one, or the list rots and you stop reading it.
7. **Persist durable knowledge to the repo, not chat.** Every decision/lesson/plan that
   should outlive this conversation goes to a file, via normal review — chat is ephemeral.
8. **Generalize the mechanism, not the symptom.** Fix root causes over special-casing.
   Delete/rewrite/regenerate freely — no ego, no sunk cost.
9. **Be exhaustive where it's cheap; stay minimal where it's not.** Mechanical sweeps (full
   coverage, every case) are free for a tireless worker — do them completely. Scope by
   DIFFICULTY not size: avoid ambiguous, open-ended design sprawl.
10. **One workstream per context.** Don't mix unrelated work in one long session — context
    degrades silently under summarization. Fresh session per domain; continuity lives in
    the repo/memory, not the thread.

## Dev-speed tactics (not rules — the concrete moves that make the above fast)
- Batch independent tool calls into one message; never poll in a loop — block on one
  `--watch`/`wait` call instead.
- Isolate parallel git mutators in detached scratch worktrees + explicit refspec pushes —
  never `git checkout` a branch that might be held by a stale worktree (silent no-op, not
  an error).
- Don't suppress a command's stderr if you might need it to diagnose — `2>/dev/null` on a
  step you'll have to re-debug just moves the cost, it doesn't remove it.
- Verify shell/OS assumptions before looping a command across N items (zsh glob rules ≠
  bash; macOS coreutils ≠ GNU) — one failed dry run beats N failed real ones.
- Prompt-cache long-lived context (this file, project CLAUDE.md) at the front of a
  session; don't re-paste large docs when a file reference will do.
- **Never put comments in a code snippet meant to be copy-pasted.** Strip all explanatory
  comments from any snippet the user will paste elsewhere — the explanation belongs in your
  surrounding prose, not in the pasted artifact.
- **Under `defaultMode: bypassPermissions`, only `permissions.deny` enforces** — `allow`/
  `autoMode.allow` are inert. Deny rules are anchored globs (not prefixes) that can't reliably
  constrain Bash arguments, and a plugin MCP deny must be `mcp__plugin_<plugin>_<server>__<tool>`
  or it silently fails open with no warning. Verify the matcher against the live tool surface
  before scoping any rule in `settings.json` (see `home/.claude/settings.README.md`).
- **An issue-build branch can itself lag `origin/main`**, not just an issue's cited line
  numbers — when a sibling build merges first, the branch this build was cut from predates
  that merge. Before editing a shared file (e.g. `block-egress.py`, `tests/test_hooks.sh`),
  `git fetch origin main` and diff/rebase against it, then re-derive the fix from the
  rebased HEAD — otherwise you can reintroduce something a merged sibling already fixed, or
  hit an avoidable rebase conflict.
- **An assigned issue may already be fully fixed on HEAD** — a prior batch's squashed commit
  message can cite an issue number (`(#131)`) without using a `Closes #131`/`Fixes #131` keyword,
  so the issue never auto-closes even though the fix (and its test, usually citing the same
  number) already merged. Before reading deep into an issue, `grep -rn '#<N>'` across the repo —
  this codebase cites issue numbers in code comments and test descriptions pervasively, so an
  already-resolved issue usually self-documents in one grep instead of a full re-investigation.
  This has recurred across separate batches (#131/#152, then #169/#170) even after being
  documented once — when your own commit message resolves an issue, use `Closes #N`/`Fixes #N`
  (not just `(#N)`) so GitHub auto-closes it instead of leaving it to be rediscovered and
  re-investigated by a later build.
- **Security issues can cite stale line numbers/rules.** The issue-authoring loop can snapshot
  an aggregate/planned state across several in-flight security PRs rather than HEAD, so a
  security issue's cited line numbers or its claim that a deny rule "already exists" may not
  match the live file. Re-derive the fix from `settings.json` at HEAD, never trust the issue's
  line refs or already-added claims at face value.
- **This bot's GitHub token is scoped to `SuxOS/claude-config` only** (#156) — a `suxbot[bot]`
  GitHub-App installation token (`ghs_…`): `gh api user` 403s and `gh repo view`/`gh api` against
  any OTHER SuxOS repo (e.g. `SuxOS/.github`) 404s, while this repo works. So an issue that says
  "copy/reference the pattern in another SuxOS repo" is UNBUILDABLE as worded — the referenced
  file's content must be pasted inline into the issue body, never left as a bare cross-repo link.
  File such issues with the content inline, and drop/flag any that only link out.
- **`block-egress.py` argv parsing is one canonicalization pass, not per-form branches** (#129):
  `strip_prefixes()` removes ALL leading prefixes (env-assign/sudo/wrappers) and `inline_payloads()`
  decomposes every bundled/glued/separate inline-flag shape in a single walk. A new bypass form
  (another tokenization edge case) should EXTEND that pass, never add a sibling branch — the
  per-form branch drip is exactly what caused #105/#115/#119/#120/#121/#126.
- **Extending `WRAPPERS` in `strip_prefixes()` can silently create a new false positive** (#179):
  a wrapper-shaped word may have an inspection-only flag that reports on the next word instead of
  executing it (`command -v curl` / `-V` prints curl's path, it never runs it). Blindly stripping
  through such a wrapper turns a safe, common idiom into a false block on the reported-about name —
  check for that mode and leave it unstripped before adding any new wrapper word.
- **A PreToolUse(Bash) hook that needs repo state must read `cwd` from the hook-input JSON and pass
  it to its git/subprocess calls** (#123, `block-checkout-held-branch.py`) — the hook process's own
  cwd isn't reliably the project dir, so inspecting `git worktree list`/branch without the input
  `cwd` reads the wrong repo. Fail open (exit 0) whenever that context can't be resolved.
- **Test hook JSON-shape logic against the real-shape corpus, not just synthetic JSON** (#117):
  the recurring hook bug class is mis-modeling the real Claude Code tool-input/transcript shape
  (#62/#80/#105/#108/#111/#112), and a hand-authored case in `tests/test_hooks.sh` shares the
  author's wrong guess so it can't catch a shape drift. Layer 3 drives each hook against redacted
  real-envelope fixtures under `tests/fixtures/` (its `README.md` documents capture/redact) — add
  a fixture there whenever a hook's shape assumptions change.
- **`install.sh` symlinks every entry under `home/.claude/` into `~/.claude/`** (except
  `settings.json`, which is copied because Claude Code rewrites it in place), so repo-/CI-only
  tooling must NOT live there or it lands in the user's live config — put linters, CI scripts,
  etc. under `.github/` instead. Adding a new
  required CI check also needs the main-branch ruleset AND `automerge.yml` `required-gates` updated
  in lockstep, or the automerge reusable refuses to arm (it verifies the ruleset first). Because of
  that, the config-integrity linters (settings/hooks/json/evals) run as STEPS INSIDE the one
  ruleset-required `shellcheck` job in `ci.yml` (#122), not as standalone jobs — that gates them on
  auto-merge with no ruleset change. Keep them folded there; splitting them back into their own jobs
  silently un-gates them until a human requires the new names in the ruleset.

## The tools — locus, not a grammar
Work is organized by **where it happens** (workspace ⊃ org ⊃ repo), not by punctuation.
The tools detect the locus from cwd and adapt. See [`WORKFLOW.md`](../../WORKFLOW.md) for
the daily loop.

- **`orient`** — *see.* Read the current locus and report only what's off (this repo's
  state, or the cross-repo radar at org).
- **`work`** — *do.* Take the highest-value doable unit end-to-end, locally, now
  (worktree → code → verify → land). Self-heals local git jams.
- **`dispatch`** — *send.* Seed and control the autonomous `SuxOS/.github` three-loop
  pipeline (`hold`, cron toggle, file issues/PRs). Generic async is the built-in
  `schedule`/`Agent`, used directly — not re-wrapped.
- **`paste`** — format output for wherever it's going (email/Slack/GitHub/terminal).

Plain English is the whole surface — no marks, counts, or adverbs. "carefully work the
flaky auth tests across all repos" is a complete instruction. `~/.claude/fabric.json` is
the one declared truth (workspace root, orgs, repos, the pipeline pointer); the cloud
pipeline lives in `SuxOS/.github` and is never duplicated here.

**One recognized exception: scope operators.** Across every skill, `scope <op> <value>`
modifies the tool's *default* self-scope (its normal locus-derived resolution — e.g.
`work`'s "survey every clone in the org, pick the top unit") instead of replacing it with
free text:
- `scope+=X` — add X to the default scope (union)
- `scope-=X` — remove X from the default scope (exclusion)
- `scope=X` — set scope to exactly X (override, default doesn't apply)
`work org scope-=automation` means: this org's normal self-scope, minus anything
automation/pipeline-related — NOT "scope := automation" (that would need `scope=automation`).
Free-text hints (`work the flaky auth tests`) are still the norm everywhere else; this one
grammar exists because include/exclude is genuinely ambiguous in prose and worth a fixed
notation instead of guessing.
