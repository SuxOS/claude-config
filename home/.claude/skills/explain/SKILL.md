---
name: explain
description: The "teach me this" directive — build a real mental model of ONE thing from first principles and ground truth. Inquiry family; append "?" and the count scales depth (/explain? gist → /explain????? full model). Read-only. Deeper and narrower than wtf. Use for "/explain", "explain this", "how does this work", "walk me through", "help me understand X".
---

**`explain` means: make me actually understand it — don't summarize, teach.** The object is one specific thing: a function, a subsystem, a protocol, a decision, a concept, an error. Where `wtf` orients you across a whole situation, `explain` goes *deep on one thing* until the mental model is real.

## `?` scales depth

Count the trailing `?` (1–5): how deep you go.

- **`/explain?`** — The gist. What it is, what it does, why it exists — a few sentences from the actual source.
- **`/explain???`** — The working model. Trace the real control/data flow, the key invariants, the non-obvious parts, the gotchas. Enough to safely modify it.
- **`/explain?????`** — First principles. Build it up from the ground: the problem it solves, the design forces, the alternatives not taken (read the history/commits for *why*), the failure modes, the edges. Enough to have *designed* it.

More `?` buys depth and rigor of grounding, never more words for their own sake. Cut filler at every level.

## How to run it

1. **Read the real thing** — the source, the spec, the commit that introduced it. Never explain from assumption; if you're inferring, say so and go check.
2. **Find the *why*, not just the *what*** — history, blame, and docs carry the reasoning the current code doesn't.
3. **Teach in layers** — one-line essence first, then the model, then the subtleties. Concrete examples over abstract prose. Name what's surprising.
4. **Mark the edges of your knowledge** — what you verified vs. what you're inferring vs. what you couldn't determine.

## Output

Lead with the one-sentence essence, then the layered explanation at the requested depth, citing source (file/commit) so it's checkable. If understanding it revealed something *wrong*, flag it and hand to `bug?` or `fix!`.

## Read-only

`explain` teaches; it never changes the thing. Acting on the understanding is `go!`/`fix!`.
