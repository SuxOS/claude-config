---
name: fork
description: The "return async / split it off" dispatch verb — hand work to a background agent, workflow, or separate session and return immediately instead of blocking the conversation. Action family; append "!", count scales parallelism/independence (/fork! one background agent → /fork!!!!! a fanned-out workflow or several sessions). Use for "/fork", "in the background", "async", "split this off", "spin up a session", "don't block".
---

**`fork` means: don't block on it — hand it off and come back fast.** This is the "should I return async / split the session" decision made into a verb. Reach for it when work is slow, parallelizable, or a *distinct workstream* that shouldn't share this context.

## Pick the mechanism

- **Background agent** (`Agent`, run in background) — one self-contained task; you're notified on completion.
- **Workflow** — fan-out / pipeline over many items; deterministic orchestration.
- **Separate session** (`spawn_task` → user spins it) — a distinct workstream that deserves its own context (one workstream per context; context degrades under summarization).
- If it should *also* recur → that's `cron!`; if it's just "later, not now" → `queue!`.

## `!` scales the fan-out

- **`/fork!`** — one background agent, return.
- **`/fork!!!`** — a small parallel set or a workflow stage.
- **`/fork!!!!!`** — a full fanned-out workflow or several concurrent sessions.

## How to run it

1. **Scope a self-contained handoff** — the fork can't see this thread; put paths, context, and acceptance criteria in its prompt.
2. **Launch** via the chosen mechanism and **return immediately** — tell the user what's running and how results arrive.
3. **Don't poll in a loop** — background work notifies on completion; block on one `wait`/`--watch` only if you must have the result before continuing (then reconsider whether it should've been `fork!` at all).

## Rails

A fork carries no standing authority — it can't pre-authorize irreversible actions on the user's behalf; those still gate inside the fork.
