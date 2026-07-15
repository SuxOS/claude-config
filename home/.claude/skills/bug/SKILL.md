---
name: bug
description: The defect verb, two faces. "/bug?" HUNTS an unknown defect and proves it with a repro (count scales how hard — /bug? obvious cause → /bug????? multi-hypothesis + bisect). "/bug!" FIXES it at the root (count scales generalization, like fix!). Bare "/bug" may gate. Use for "/bug", "/bug?", "/bug!", "why is this broken", "where's the bug", "this isn't working", "track down and fix".
---

**`bug` has two faces — the mark picks which:**
- **`bug?`** — *hunt.* Localize an unknown fault and prove it with a repro. Unlike `bet?` (tests a *specific* claim) this is an open hunt for an unknown cause; unlike `wtf?` (orients) it drives to one root fault. Diagnoses, doesn't change code. **This is the mode described below.**
- **`bug!`** — *fix.* Take a located defect and repair it at the root; `!` count scales how far past the symptom you generalize. This is `fix!` scoped to a bug — follow [fix](../fix/SKILL.md). Typical flow: `bug?` to find, then `bug!`/`fix!` to resolve.
- **`bug`** (bare) — you may gate: confirm the symptom, ask what "broken" means, propose an approach before committing.

## `?` scales the hunt

Count the trailing `?` (1–5): how hard you dig.

- **`/bug?`** — The obvious cause. Read the error, check the recent change, find the one likely culprit, confirm.
- **`/bug???`** — Multiple hypotheses. Enumerate what could cause this, instrument/log to discriminate, narrow by evidence, get a minimal repro.
- **`/bug?????`** — Relentless. Bisect (`git bisect`) across history, add tracing, diff working vs. broken environments, reason about race/state/timing, run it under a debugger — until the exact line and mechanism are pinned and reproducible on demand.

More `?` buys more falsification effort, not more guessing. A hypothesis you haven't *reproduced* is a guess, not a diagnosis.

## How to run it

**Iron rule: no fix before a reproduced root cause.** A hunt that jumps to editing has skipped the job.

1. **Reproduce first** — a bug you can't trigger you can't fix. Get the minimal reliable repro before theorizing. Read the actual error; check the recent change; instrument component boundaries and trace the data flow *backward* to the source.
2. **Bisect the search space** — in code (bisect/blame), in data (which input), in state (which precondition). Halve, don't wander. Find a *working* comparison case and list every difference from the broken one.
3. **Prove the mechanism** — not just *where* it fails but *why*: the exact state/input that trips it. Test **one hypothesis at a time**, changing one variable, and confirm before moving on — never bundle guesses. Confirm by making it appear and disappear on command.
4. **Diagnose, don't patch** — `bug?` ends at a proven root cause and repro; the repair is `fix!`.

**Three strikes → step back.** If three fixes have failed, stop trying a fourth — the model of the system is wrong. Question the architecture/assumptions, not the patch. (A durable root cause worth remembering → write it to `memory/`.)

## Output

`[FOUND|NARROWED|CANT-REPRO] <root cause at file:line> — <the repro + the mechanism>`

Hand a FOUND result to `fix!`. If it's already breaking production, hand to `fml!` to stabilize first.

## Read-mostly

May run, log, and reproduce freely; does not change the code it's hunting in beyond throwaway instrumentation (which it removes).
