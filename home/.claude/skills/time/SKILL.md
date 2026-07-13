---
name: time
description: The "keep at it" directive with a wall-clock budget. The number of "!" (1–5 → up to 5.0 units) is a quantity of TIME to spend on whatever's in context — you float effort to fill it. Abstract across time; effort floats. Sibling of go (which fixes effort, floats time). Use for "/time", "/time!!!", "keep going", "spend a while on", "stay on it", "babysit", "run this for a bit".
---

**`time` means: stay on it and fill the duration.** Where `go` spends a fixed lump of *effort* and takes however long, `time` commits a fixed lump of *wall-clock* and pours in however much effort fits. The object is whatever's in context — a task, a watch, a search, a polish job, a system to keep nudging.

## `!` is a time budget, not a dial

Count the `!`: **1–5 = 1.0–5.0 units of time.** Not a fixed number of minutes — a *quantity of persistence*. Low = a quick, bounded pass. High = a sustained campaign: keep iterating, deepening, revisiting, and monitoring until the budget is spent or the work is genuinely done. `time` is abstract across time; effort floats — you decide the intensity moment to moment, the *duration* is the constraint.

Spend the budget by **staying alive across wall-clock**, using the machinery for it:

- **Iterate** — repeated passes that each improve the result (loop-until-dry, refine, harden), not one-and-done.
- **Persist** — background agents/workflows and `ScheduleWakeup`/loop to keep working across turns instead of blocking.
- **Poll & watch** — for external state that changes over time (CI, deploys, queues, dashboards): check on a sane cadence, react when it moves. Block on a `--watch`/`wait` where one exists; don't busy-loop.
- **Deepen** — when the obvious work is done and time remains, go further: edge cases, coverage, adversarial verification, the completeness pass `go` would skip.

Don't burn the budget idling. If you truly run out of useful work before the time is spent, say so and stop early — filling time with noise is a failure, not success.

## How to run it

1. **Find the object** and what "done" would even mean.
2. **Set the loop** — pick the mechanism (iterate / background / poll / deepen) that fits, and a cadence that respects the cache and the user's attention.
3. **Work in rounds**, reporting outcomes as they land — not play-by-play. Keep the conversation unblocked; hand slow work to background.
4. **Converge or expire** — stop when the work is done *or* the budget is spent, and say which.

## Output

Rounds of outcomes, most recent last:
`[round N] [PROGRESSED|LANDED|WATCHING <what>|NO-CHANGE|DONE|TIME-UP] <short desc>`

Close with where things stand and the natural next move — hand off to `go` if what remains is a bounded effort, or to `wtf` if what remains is understanding.

## Rails that don't bend

Same as `go`: never force-push, merge/publish without confirmation, or do anything irreversible/destructive without asking. Long running time doesn't grant standing permission — each irreversible action still needs its own yes.
