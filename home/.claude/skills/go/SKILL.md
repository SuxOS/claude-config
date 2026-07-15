---
name: go
description: The universal "do it" verb (the `!` act mood). Count sets the default level of every adverb at once — risk, parallel, model, tokens, effort, speed, assume, verify — and you name any adverb (name=value) to override that axis alone (go! parallel=wide, go!!! risk=low). Flags — free order: --dry, --suggest, --help, --force. Operates on the chunk in context; time floats. Use for "/go", "/go!!!", "just do it", "ship it", "handle it".
---

**`go` means: stop asking, start doing** — on whatever's in context (a task, a plan, a file, a repo, a half-idea, or, bare, everything in flight). Deliver outcomes, not plans or menus.

## `!` count = the default for every adverb at once

Count the `!` (×1 light · ×3 standard · ×5 maximal): it sets *all* the adverbs below to that tier as a default. You then **override any single axis by naming it** — the count is convenience, the adverbs are the real degrees of freedom. Time is not the constraint here; effort is. (Sibling `time` is the opposite — a fixed *time* budget, floating effort. Reach for it when the ask is "keep at it a while," not "spend this much.")

The adverbs (each independently specifiable):

These are **adverbs** — independent `name=value` axes (`=`, not `:`), order-free, each spanning a **wide** range. The `!` count sets them all to one default tier at once; **name an adverb to override just that axis** (`go! parallel=wide`, `go!!! risk=low`). Use the extremes when the chunk calls for it; don't cluster in the safe middle.

Flags (also order-free): `--dry` preview what would change, write nothing · `--suggest` propose + recommend, don't commit · `--help` show usage (→ `man`) · `--force` skip the soft clarify-gate and commit — hard rails still hold.
- **model** — `haiku ↔ fable`. Cheap/fast for mechanical work → top tier for hard reasoning. You can't reset the *current* session's model mid-task — buy this by *delegating* to subagents/workflows at a chosen tier, not by "becoming" a bigger model.
- **effort** — `low ↔ max` reasoning per call.
- **tokens** — `terse ↔ exhaustive`; how much you read, explore, and write.
- **parallel** — `serial ↔ fan-out N` (subagents / workflows / worktrees). **Specified, never assumed:** default serial; fan out only when the chunks are genuinely independent and you've chosen to — then batch those calls into one message. Wide, but on purpose.
- **risk** — `gentle ↔ forceful`; how bold the moves.
- **assume** — `ask-everything ↔ decide-all-and-log`; how much you commit without asking.
- **speed** — `slow-and-thorough ↔ fast-and-loose`.
- **verify** — `smoke-check ↔ adversarial`; how hard you exercise and prove the result.

**Set the adverbs per task; a high count is not "everything maxed."** A high-stakes prod change reads as `model=top verify=adversarial risk=low`. A big mechanical sweep reads as `model=cheap parallel=wide assume=high speed=fast`. A gnarly bug reads as `effort=max tokens=deep parallel=1`. Read the chunk, set the axes — the count just picks the default before you override. Low → conservative, ask when materially unsure; high → decide and move.

Whatever you decide without asking, you **log as an assumption** the user can veto after the fact — that's the trade for not stopping.

## How to run it

1. **Find the object (any domain).** What the user pointed at; or, if `/go` stands alone, everything in flight *for the domain you're in*. In code that's green/near-green PRs, open issues, stuck workflows, stalled changes, silent cron failures. Off-code it's the open loops there — unanswered mail, calendar conflicts, stale vault notes, pending errands. The verb is the same; the tools differ.
2. **Allocate the budget** across the dimensions above for *this* task.
3. **Decompose and fan out** — independent pieces run concurrently (worktrees for parallel mutators); don't serialize what doesn't depend.
4. **Do the whole thing** — build, fix, land. Chase root causes, not symptoms. Exhaustive where it's cheap; scoped by *difficulty*, not size.
5. **Verify** — exercise the change, run the checks, confirm it works before calling it done.

## Output

One line per item — outcome, not narration:
`[SHIPPED|MERGED|FIXED|BUILT|RERAN|ASSUMED: <what>|BLOCKED: <reason>] <short desc>`

At higher budget, follow with an **Assumptions** list and a one-line **Budget spend** note (where the units went) so the allocation is visible and vetoable.

## Rails that don't bend at any budget

Never force-push, merge/publish without confirmation, or do anything irreversible or destructive (hard-delete, empty trash, move money, change access controls, send on the user's behalf) without asking. Budget buys boldness on **reversible** decisions only — lean on git, branches, and flags so wrong calls stay cheap.
