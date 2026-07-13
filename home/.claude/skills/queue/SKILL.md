---
name: queue
description: The "capture it for later" dispatch verb — register a discrete unit of work to act on later, without doing it now. Action family; append "!", count scales formality (/queue! a quick task chip → /queue!!!!! a fully-specified tracked issue). Use for "/queue", "note this task", "add a todo", "capture for later", "make an issue", "backlog this".
---

**`queue` means: record the work so it isn't lost — but don't do it now.** The object is a piece of work worth remembering. `queue!` *captures*; execution is `run!`/`go!` later, scheduling is `cron!`, backgrounding-now is `fork!`.

## Pick the store by durability

- **Task chip** (`spawn_task`) — lightweight, this-machine, one-click spin-off into its own session later. Good for "noticed in passing, fix separately."
- **Tracked task** (`TaskCreate`) — in-session/short-horizon progress tracking.
- **GitHub issue** (`gh issue create`) — durable, shared, survives sessions; for real backlog items.

## `!` scales formality

- **`/queue!`** — a quick chip/note: title + one-line why.
- **`/queue!!!`** — a proper task: context, paths, what "done" means.
- **`/queue!!!!!`** — a fully-specified tracked issue: repro/acceptance/scope, ready for someone to pick up cold.

## How to run it

1. **Phrase it standalone** — include paths and context so it's actionable without this conversation.
2. **Choose the store** by durability, **create it**, confirm.
3. **Don't start doing it** — the whole point is deferral. If it should happen now, that's `run!`/`go!`.

## Hand-off

Later: `run!`/`go!` to execute, `cron!` to schedule, `fork!` to background it now.
