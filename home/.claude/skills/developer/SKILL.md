---
name: developer
description: The looping autonomous developer — run `/develop` bursts back-to-back until the backlog's dry (or a time/budget cap, or you halt it). The standing "keep the pipeline draining" role. Count scales persistence/reach; `@cadence` makes it recurring. Naturally long-running → background/scheduled. Use for "/developer", "keep draining", "loop the developer", "keep shipping until done", "drain the org overnight".
---

**`developer` means: keep developing until it's done** — the loop around `develop`. Where `develop` runs one burst and returns, `developer` runs bursts back-to-back and only stops when a stop condition trips: the backlog's dry, a time/budget cap, or you halt it. It's the standing role that keeps the pipeline draining without you re-invoking.

`developer` = `develop` in a `while (not dry)`. One turn of the crank vs. keeping the crank turning.

## `!` scales persistence and reach

- **`/developer`** — drain the current repo: loop `develop` bursts until dry, then stop.
- **`/developer!!!`** — drain the org: loop across opted-in repos until the whole backlog's dry.
- **`/developer!!!!!`** — standing drain: loop wide, top model on the consequential stages, self-heal jams mid-loop, keep going until dry or capped.

Bare **gates** (confirms the stop condition + locus before it starts a long run); any `!` **produces**. Hint and adverbs pass straight through to each `develop` burst (`developer!!! repos=all risk=low`).

## Stop conditions (always bounded — never an unbounded loop)

Every developer run declares its bound up front:

- **loop-until-dry** — stop after K consecutive passes yield no new buildable work (default K=2). The primary bound.
- **time / budget cap** — `time=2h` or a token budget; stop when spent.
- **cadence** — `@nightly` / `@*/30min` turns it into a recurring scheduled drain (nominalizes `cron!`); each firing is one bounded drain, not an infinite loop.
- **manual halt** — you stop it; `hold` on an issue/PR still blocks automation per the fabric.

A developer run with no declared bound is a bug — pick one before starting.

## Locus — naturally long-running

Looping is slow, so developer's home is **background or scheduled**, not blocking your thread:

- **In-session loop** (the `loop`/`time` mechanism) when you want to watch it drain now.
- **Background / scheduled** (`@cadence`, `fork!`) for the standing role — the nightly org drain, the every-30-min jam-watch. This is where "keep the pipeline draining" lives without a human awake.

Between bursts it **preflights** like `develop`: a jam mid-drain drops to local worktree-safe recovery, then the loop resumes — the drain self-heals instead of piling onto a jam.

## How to run it

1. **Declare the bound** — which stop condition, and the locus (in-session / background / cadence).
2. **Loop `develop`** — each iteration is one full `develop` burst (preflight → route → execute → verify). Accumulate what shipped.
3. **Check dryness** — after each pass, is there new buildable work? K empty passes → dry → stop.
4. **Self-heal** — a jam between passes routes to local recovery, then resume; never dispatch onto a jam.
5. **Report the drain** — totals across passes, not per-burst narration (`develop` already emits per unit).

## Output

A drain summary, not a play-by-play:

`[DRAINED: <n shipped / m dispatched over p passes>|DRY|CAPPED: <bound hit>|HALTED|BLOCKED: <jam>] <repos, state now>`

## Hand off

- One unit, not a loop → `develop` (this is just its atom).
- Schedule the standing drain → `cron!` (`developer @nightly`); pause it → remove the schedule or `hold`.
- A jam it can't clear → surfaces to you (the `fml!` escape hatches: metered-key revert, manual re-queue).

## Rails

Inherits every `develop` rail unchanged — no force-push, no auto-merge past CI + security-review, nothing irreversible without a yes, config changes (metered-key revert) ask first. **One extra:** a long unattended loop makes the shared subscription pool the scarce resource — a bound is mandatory, and pool exhaustion is a stop-and-surface, never a "push through."
