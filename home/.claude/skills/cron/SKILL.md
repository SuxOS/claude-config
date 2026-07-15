---
name: cron
description: The "schedule it" directive — make work recur on a cadence or fire at a future time. Action family; append "!" and the count scales scope (/cron! one simple recurring check → /cron!!!!! a full standing automation). Picks the right scheduler for the job. Creating persistent schedules needs explicit confirmation. Use for "/cron", "schedule this", "every morning", "run it later", "remind me", "keep running", "automate".
---

**`cron` means: set work to run on its own — later, or on repeat.** The object is a task plus a *when*: a recurring check, a nightly job, a one-shot future run, a reminder, a poll.

## Pick the right scheduler (know your tools)

Match the mechanism to the job — don't reach for system `cron` reflexively:

- **Claude scheduled agents / routines** (`schedule` skill, scheduled-tasks MCP, `CronCreate`) — for work *I* should do on a cadence in the cloud (babysit PRs, morning digest, recurring triage). This is usually the right answer.
- **`ScheduleWakeup` / `/loop`** — for staying alive *within* a session to continue or poll on an interval; pairs with `time!`. Sub-5-min cadence keeps the cache warm.
- **System schedulers** — for jobs on *this machine*: **launchd** is native on macOS (this box is darwin — prefer it over `crontab` for anything durable), `crontab`/`cron` on Linux, `at`/`systemd-timer` for one-shots and units. Use these when the work is a shell job that must run regardless of any session.

## `!` scales scope

Count the trailing `!` (1–5): how ambitious the automation.

- **`/cron!`** — One simple scheduled thing: a single recurring check or a one-shot future run.
- **`/cron!!!`** — A real routine: sensible cadence, failure handling, a clear report each run.
- **`/cron!!!!!`** — A standing automation: the full loop — trigger, do, verify, report, self-heal — wired to survive and to alert when it can't.

## How to run it

1. **Pin the *when* and the *what*** — exact cadence/time (convert relative → absolute; mind the timezone) and the precise action each run takes.
2. **Choose the scheduler** from the list above and set it up.
3. **Make each run observable** — it must report success/failure, not fail silently. A silent broken cron is worse than none.

## Confirm before persisting

A recurring schedule is **standing persistent configuration** — per the safety rules that requires explicit user confirmation before creation. State the schedule, the mechanism, and what each run will do, and get a yes before wiring it. Never point a schedule at an irreversible action that will fire unattended. Removing/altering an existing schedule needs the same care — look at what's there first.
