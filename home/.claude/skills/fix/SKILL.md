---
name: fix
description: The "repair this known defect" directive — make one identified problem right, at the root. Action family; append "!" and the count scales boldness/generalization (/fix! minimal patch → /fix!!!!! fix the whole class). Use for "/fix", "fix this", "patch it", "make it right", applied to a KNOWN bug/finding/failure.
---

**`fix` means: repair the specific known thing — properly, at the root.** The object is an *identified* defect: a `bug?` diagnosis, an `audit?` finding, a red test, a reported failure. Narrower than `go!` (general "do the work") and calmer than `fml!` (crisis recovery) — this is deliberate repair of a known fault.

## `!` scales generalization

Count the trailing `!` (1–5): how far past the single symptom you go.

- **`/fix!`** — The targeted patch. Correct exactly this defect, minimally, and verify it's gone.
- **`/fix!!!`** — Root, not symptom. Fix the actual cause, and the sibling cases that share it. Add the regression test.
- **`/fix!!!!!`** — The whole class. Generalize the fix so this *kind* of bug can't recur — the mechanism, not the instance — and harden with tests around the edges. Refactor boldly if that's the real fix.

More `!` fixes wider and deeper, never sloppier. Every level ends **verified**, not assumed (that's `bet?`).

## How to run it

1. **Confirm the cause** — don't fix what you haven't localized. If the root isn't proven, that's `bug?` first.
2. **Write the failing test first** — the test that *would have caught it*, before the fix. Run it, watch it fail for the right reason (red) — a test that passes before you've touched anything proves nothing. This is the regression guard, written up front; at high `!`, cover the sibling cases and the class.
3. **Repair the root** — change the mechanism that's wrong, not just the visible symptom, until the test goes green. Minimal change to pass; match surrounding code style; refactor only once green.
4. **Verify end-to-end** — exercise the actual flow and confirm fixed + nothing else broke. Never claim fixed without having just watched it pass (the completion-verification rail). Hand to `bet?` if confidence matters.

## Output

`[FIXED|FIXED+GENERALIZED|PARTIAL: <what remains>] <defect> — <root cause + what changed + how verified>`

If the fix turns out to need broad rebuilding, that's `go!`; if it's an active outage, stabilize with `fml!` first.

## Rails

Same as `go!`: repair via reversible edits; never force-push, publish, or destroy to "fix" something without confirmation.
