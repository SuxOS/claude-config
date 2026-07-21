---
name: drummer
description: Launch a goal-directed autonomous scheduled loop that runs on a cadence until a goal criterion is met (GREEN) or it needs a human (AMBER), then self-disarms. Use for "start a drummer to <goal>", "run a daily sweep of X until Y", "keep working on <mandate> until done". Thin wrapper over create_scheduled_task — no new engine.
---

# drummer

**drummer means: a mandate-scoped orchestrator that runs to a verified stop, not forever.**
It reuses `~/.claude/scheduled-tasks` — no new engine, just one prompt template plus one
`create_scheduled_task` call. Each run does the next unit of work and checks a
stop-condition; it ends one of two verified ways: **GREEN** (the goal is certified met — it
disables itself) or **AMBER** (blocked on a human decision — keeps running unless the block
is fatal). `drummer-monitor` already watches `~/.claude/scheduled-tasks` for GREEN/AMBER and
surfaces it; drummer itself only launches and confirms.

## Scope

Any mandate that's better checked on a cadence than done in one sitting — a daily sweep, a
piece of work-product driven to a status, a monitor-and-surface loop. Not for one-shot work
(`work`/the built-in `Agent` do that in-thread) and not for the SuxOS pipeline (`dispatch`
owns that).

## How to run it

Given a goal (plus optional constraints/cadence/deadline):

1. **Derive four things** before calling anything:
   - a **cadence** (default daily if the user doesn't say one),
   - a checkable **STOP-CONDITION** predicate — an observable fact, not a vibe ("inbox has
     zero unactioned messages today", not "inbox feels handled"),
   - a **HARD-STOP** (max N runs or a date), so a bad predicate can't run forever,
   - the **per-run work-step** — what it actually does each firing.
2. **Call `create_scheduled_task`** with `taskId` `drummer-<slug>`, the cadence as
   `cronExpression`, and a `prompt` built from this template:

   ```
   You are the drummer "<goal>". MANDATE: <goal>. CONSTRAINTS: <constraints>.
   Each run: (1) do the next best unit of work toward the mandate (use /life, /sux, vault, mail, web, repos as needed); (2) record progress + current status to <status location: vault Matter/<slug>/STATUS.md for life-matters, or a vault note for others>; (3) evaluate STOP-CONDITION: <predicate>.
   - If STOP-CONDITION is met → call update_scheduled_task(taskId:"drummer-<slug>", enabled:false) to disable yourself, then report GREEN with a summary.
   - If blocked on a human decision → report AMBER / NEEDS-HUMAN with the specific ask; keep running unless the block is fatal.
   - HARD-STOP: after <N runs / date>, disable yourself and report regardless.
   Stay strictly within the mandate — no scope creep.
   ```
3. **Confirm back to the user**: the drummer created, its cadence, its stop-condition, and
   that `drummer-monitor` will surface GREEN/AMBER — they can list/inspect any time via the
   scheduled-tasks tools.

## Examples

- **Daily email sweep** — cadence daily; stop-condition = inbox triaged to zero-unactioned
  that day; this one runs indefinitely — it reports AMBER (not GREEN) whenever a reply
  needs the user, it doesn't stop on its own without an explicit hard-stop.
- **Med-mal legal work-product** — status location = vault `Matter/med-mal/STATUS.md`;
  stop-condition = that file reads `STATUS: GREEN`.
- **Study plan to refresh knowledge** — stop-condition = the plan is written AND the first
  week is scheduled on the calendar.
- **Job monitor + apply** — cadence daily; the per-run work-step surfaces new matches as
  AMBER for the user's approval — it never applies on its own.

## Output

`[LAUNCHED: drummer-<slug>, cadence <x>, stop <predicate>|DECLINED: <why>] <desc>`

## Rails

**Anti-bloat: this is a prompt template plus one `create_scheduled_task` call — nothing
else.** Do not build a new engine, DSL, or MCP for this; if a mandate needs more than the
template above, it isn't a drummer. The template's self-disable-on-GREEN step is
load-bearing — a drummer that never turns itself off is a bug, not a feature. "Apply",
"send", "delete", and other irreversible actions stay AMBER-and-ask, never automatic, no
matter what the mandate says.
