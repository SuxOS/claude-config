---
name: drainer
description: The looping domain-agnostic drain — run `/drain` bursts back-to-back until the backlog's dry (or a time/budget cap, or you halt it). Domain-agnostic sibling of `/developer`, which is the same loop narrowed to a git org's repos. Count scales persistence/reach; `@cadence` makes it recurring (e.g. a nightly Downloads sweep or inbox sort). Naturally long-running → background or scheduled, not blocking the thread. Use for "/drainer", "keep sorting until the folder's empty", "loop through the inbox until it's clear", "keep draining this until done", "clean out my downloads overnight".
---

**`drainer` means: keep draining until it's done** — `/drain` in a `while (not dry)`. Where `drain` runs one bounded burst and returns, `drainer` runs bursts back-to-back and only stops when a stop condition trips: the backlog's empty, a time/budget cap, or you halt it. It's `/developer`'s general-domain sibling — same looping shape, any backlog instead of a GitHub org.

## Stop conditions (always bounded — never an unbounded loop)

Every `drainer` run declares its bound up front, same discipline as `/developer`:

- **loop-until-dry** — stop after K consecutive passes yield nothing new to file/sort/answer (default K=2). The primary bound for a folder or inbox with a finite pile.
- **time/budget cap** — `time=1h` or a token budget; stop when spent. Use this for backlogs that regenerate (mail, a research queue) where "dry" may never truly happen.
- **cadence** — `@nightly` / `@*/30min` turns it into a recurring scheduled drain; each firing is one bounded pass, not an infinite loop. This is the shape for "keep my Downloads folder from piling back up" — regular small drains beat one heroic sweep.
- **manual halt** — you stop it.

A `drainer` run with no declared bound is a bug — pick one before starting.

## Locus — naturally long-running

Looping is slow, so `drainer`'s home is background or scheduled, matching `/developer`:

- **In-session loop** (`/loop /drain`, no interval given, self-paced) when you want to watch it drain now.
- **Background** (`fork!`) so the conversation stays unblocked while a big one-time sweep runs.
- **Scheduled** (`/cron! /drain @nightly`) for the standing role — persisting a recurring schedule always asks for confirmation first, same as any standing config change.

Between bursts it re-checks the taxonomy it's filing against — if a prior burst's assumption turns out wrong (the user vetoed a filing decision), the next burst should pick that up, not repeat the mistake.

## How to run it

1. **Declare the bound** — which stop condition, and where it runs (in-session / background / cadence).
2. **Loop `/drain`** — each iteration is one full `/drain` burst (identify backlog → sort deterministically where possible → act reversibly → verify). Accumulate what got cleared.
3. **Check dryness** — after each pass, is there new material? K empty passes → dry → stop.
4. **Self-heal** — if a pass hits something it can't resolve alone (an ambiguous file, a taxonomy gap, sensitive content needing a human call), flag it and continue past it rather than stalling the whole loop on one item.
5. **Report the drain** — totals across passes, not per-burst narration (`/drain` already reports per unit).

## Output

A drain summary, not a play-by-play:

`[DRAINED: <n items over p passes>|DRY|CAPPED: <bound hit>|HALTED|BLOCKED: <what needs a human>] <backlog, state now>`

## Hand off

- One unit, not a loop → `/drain` (this is just its atom).
- Code/git org backlog → `/developer` (the domain-specific sibling).
- Schedule the standing drain → `/cron!` (`drain! @nightly ~/Downloads`); pause it → remove the schedule.
- A jam it can't clear alone → surfaces to you.

## Rails

Inherits every `/drain` rail unchanged — no permanent deletion, no touching credentials, nothing irreversible without a yes. **One extra**, same as `/developer`: a long unattended loop makes whatever it's touching (disk space, a shared inbox, API rate limits) the scarce resource — a bound is mandatory, and hitting a limit is a stop-and-surface, never a "push through."
