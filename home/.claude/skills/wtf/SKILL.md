---
name: wtf
description: The universal "make sense of it" directive — figure out whatever's confusing by pulling on every knowledge source at once. Inquiry family; append "?" and the count scales breadth (/wtf? quick read → /wtf????? triangulate everything). Read-only counterpart to go. Use for "/wtf", "/wtf???", "wtf is this", "what's going on", "how does this work", "why did this happen", "catch me up", "where did I leave off".
---

**`wtf` means: figure it out and tell me straight.** It's the read-only twin of `go` — `go` acts, `wtf` understands. The object is whatever's in context: a chunk of code, an error, a decision you can't remember making, a system's behavior, the state of the world right now, or a plain "what is happening." Deliver an *answer*, not a research plan.

## The move: triangulate across everything

Don't answer from one source or from memory. Pull the relevant threads in **parallel**, then reconcile them into one account:

- **The thing itself** — read the code, the error, the file, the diff, the live state. Ground truth first.
- **Commits & history** — `git log`, blame, PRs. *Why* it's this way lives in the history, not the current file. Read the reasoning, not just the change.
- **Durable knowledge** — the memory files (`memory/` + `MEMORY.md`), project docs, CLAUDE.md. Decisions and lessons already written down.
- **Past sessions** — prior work on this, via session-history/search tools, when the answer is "what was I doing."
- **The wider vault** — notes, mail, files, and the web via recall/search (sux) when the answer lives outside the repo.
- **Live systems** — running tasks, workflows, CI, dashboards, logs when the question is "what's happening right now."

Follow the threads the question actually pulls on — a code question leans on history and the code; a "where did I leave off" leans on sessions, git status, and in-flight work. Chase contradictions between sources until they resolve; a mismatch between what's written and what's true is usually the most interesting part of the answer.

## Output

Lead with the answer in one or two sentences — the actual "here's what's going on." Then the supporting detail, tight and scannable: what's true, why, and where it came from (cite the commit / file / note so it's checkable). Flag what you *couldn't* resolve rather than papering over it.

For a bare "/wtf" (make sense of the world): group as **In progress** / **Needs you** / **Idle-stale** — what's active, what's waiting on a decision, what stalled. Point stale items at `/go`.

## Read-only

`wtf` observes; it never changes anything. The moment the answer implies action, that's `go`'s job — name the next move and hand off, don't take it.
