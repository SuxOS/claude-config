---
name: audit
description: The "sweep it for problems" directive — systematically review a whole surface for bugs, risks, and rot. Inquiry family; append "?" and the count scales coverage + number of parallel lenses (/audit? one pass → /audit????? exhaustive multi-agent). Read-only; produces ranked findings, fixes nothing. Use for "/audit", "review this", "what's wrong with", "find issues in", "security pass", "check the whole X".
---

**`audit` means: comb the whole surface and surface everything worth fixing.** The object is a breadth: a codebase, a diff, a config, a dependency set, an infra setup. Where `bug?` chases one known fault, `audit?` enumerates *unknown* issues across the whole thing — breadth over depth.

## `?` scales coverage

Count the trailing `?` (1–5): how wide and how many lenses.

- **`/audit?`** — One careful pass for the obvious problems (correctness, glaring risk).
- **`/audit???`** — Multi-lens: correctness, security, performance, error handling, resource leaks, dead code, test gaps — each considered deliberately across the surface.
- **`/audit?????`** — Exhaustive. Fan out parallel reviewers, each owning a dimension and a slice; dedup and rank the union; adversarially re-check the high-severity findings (that's `bet?`) before reporting. Log any coverage you *didn't* reach — silent truncation reads as "all clear" when it isn't.

More `?` buys breadth and independent perspectives, not lower confidence per finding. Rank by severity; a wall of nits buries the one that matters.

## How to run it

1. **Bound the surface** — exactly what's in scope (these files, this diff, this service). Say what's out.
2. **Enumerate by lens** — sweep each dimension across the whole surface rather than reading each file once for everything; fan lenses out in parallel.
3. **Rank and verify** — severity-order the findings; adversarially confirm the serious ones so nothing plausible-but-wrong survives.
4. **Report, don't repair** — `audit?` produces the list; fixing is `fix!` (per finding) or `go!` (the batch).

## Output

Findings, most-severe first — each: `[severity] <file:line> — <the defect> — <the failure it causes>`. End with coverage notes (what was and wasn't reached). Hand the list to `fix!`/`go!`.

## Read-only

Reviews; never edits. (This is `/code-review`'s energy generalized to any surface — prefer that skill when it fits a code diff.)
