---
name: fml
description: The "it broke — recover" directive — something is failing, stuck, or on fire, and the job is to get back to a good state fast. The number of "!" (1–5) scales how aggressive the recovery. Abstract across damage. Read-and-repair sibling of wtf (wtf diagnoses; fml stabilizes). Use for "/fml", "/fml!!!", "it's broken", "everything's on fire", "I'm stuck", "undo this", "get me out of this".
---

**`fml` means: stop the bleeding, then get back to green.** The object is a broken or stuck state — red CI, a botched change, a hung system, a wedged repo, a deploy gone wrong, a corner you've painted yourself into. Priority order is **stabilize → restore → understand**, not the reverse: get to a safe state first, root-cause after.

## `!` scales aggressiveness

Count the `!` (1–5): how big a hammer you're cleared to swing.

- **`/fml`** — Unstick the small thing. Diagnose the immediate failure, apply the minimal targeted fix, confirm it's unblocked.
- **`/fml!!`** — Restore known-good. Prefer reverting to the last green state over forward-fixing a mess; reset the wedged thing; clear the jam. Then diagnose what happened.
- **`/fml!!!`** (and up) — Full recovery. Take the fastest reversible path back to working — revert the bad commit/PR, roll back the change, reset the branch, kill and restart the hung fleet — *then* run the root-cause pass so it doesn't recur. Bias hard to reversible moves that restore service now.

More `!` means bolder restoration, **not** more destruction. The fastest safe path back is almost always a *revert*, not a delete — reverting is reversible, deleting isn't.

## How to run it

1. **Assess the blast radius** — what's broken, what's still working, what's actively getting worse. Don't make it worse while looking.
2. **Stabilize** — stop the failure from spreading (revert, roll back, reset, pause the cron, kill the loop).
3. **Restore** — get back to a known-good, working state by the most reversible route.
4. **Root-cause** — once safe, find *why*, and leave the fix or a clear flag so it doesn't repeat. (This step is `wtf`'s method, applied after the fire's out.)

## Output

`[STABILIZED|REVERTED|RESTORED|STILL-BROKEN: <blocker>] <what> — <state now + cause if known>`

Hand off: if recovery needs real rebuilding, that's `go`; if you can't tell what broke, that's `wtf`; if you're unsure the restore actually worked, that's `bet`.

## Rails hold even under fire

An emergency does **not** unlock the irreversible list. Recover by reverting, resetting, and restarting — never by force-pushing over shared history, hard-deleting data, or destroying anything you can't get back. If the only apparent fix is irreversible, stop and surface it — a wrong destructive "fix" is worse than the outage.
