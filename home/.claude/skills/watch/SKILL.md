---
name: watch
description: Stand up a watch — a scheduled probe of ONE external condition that can't push an event, which pings Colin when it trips and stands itself down; hard expiry date mandatory. Use for "watch X until Y", "ping me when <portal/API/external thing> changes", "keep checking <door> until it opens". Refuses any goal whose stop condition isn't a deterministic shell check — that class is pipeline work (dispatch), a milestone, or a reminder (timer). Replaces the retired "drummer" mechanism (2026-07-23).
---

# watch

**Standing automation is one of exactly four words.** If someone (including you) asks
"what is this thing?", the answer is always one row of this table:

| Word | What it is | Stop semantics |
|---|---|---|
| **routine** | fires on a cadence, no goal (morning brief, journal) | runs until Colin says stop |
| **timer** | fires once at a moment, then gone | auto-disables after firing (`fireAt`) |
| **watch** | polls one external condition that can't push, pings on trip | self-disarms on trip or expiry — this skill |
| **milestone** | a dev goal; the `.github` pipeline drains its issues | GitHub close-at-merge; never a local loop |

**The rule that governs all four: no schedule without an end.** A watch's end is its
expiry date; a timer's is its moment; a milestone's is its close; a routine is the only
open-ended kind and only Colin creates those.

## What makes a watch a watch

- The condition is **external and unpushable** (a portal door, an upstream release page,
  a mail-in decision). If GitHub/CI/sux can emit an event for it, wire the event — refuse
  the watch.
- The stop predicate is a **deterministic shell check** — runnable, greppable, exit-code
  or output-line decidable. "Feels handled" is not a predicate. If the goal needs judgment
  or produces work-product each run, it is NOT a watch: send it to `dispatch` (pipeline) or
  do it in-thread. Refuse and route.
- **Hard expiry is mandatory** — a date after which the watch announces expiry and stands
  down even if the condition never tripped. No expiry, no watch.

## Anatomy (all state in ONE place: the task dir)

```
~/.claude/scheduled-tasks/watch-<slug>/
  SKILL.md    ← courier prompt only (template below), no policy prose
  check.sh    ← the ENTIRE brain: expiry, probe, dedup stamps, verdict
  state/      ← stamp files written by check.sh itself (announced-<x>, last-run)
```

`check.sh` prints a line-oriented contract; the LLM run is a **courier** that acts only
on these lines and does nothing else:

```
HEARTBEAT <iso8601>           # always, when a pass completes
STATUS <item> <state>         # informational
NOTIFY <message...>           # courier sends this as a push notification, verbatim
VERDICT CONTINUE              # courier exits
VERDICT DISARM <reason>       # courier disables+deletes this task, then exits
```

Non-negotiables inside `check.sh`: the **expiry check is the first branch** (past expiry →
`VERDICT DISARM expired`); notification **dedup is a stamp file written by the script**
(the courier never tracks what was announced); a trip both NOTIFYs and, when all items
have tripped, DISARMs. Worst case if a disarm fails is a repeated visible "expired" ping
next fire — never silent work past the goal.

## Courier prompt template (the whole SKILL.md of a watch)

```
You are the courier for the watch "<slug>". Run exactly this and act only on its output:
  sh ~/.claude/scheduled-tasks/watch-<slug>/check.sh
For each NOTIFY line: send it as a push notification (PushNotification tool, verbatim).
If a line is `VERDICT DISARM <reason>`: call update_scheduled_task(taskId:"watch-<slug>",
enabled:false), then delete_scheduled_task(taskId:"watch-<slug>"), then push one final
notification: "watch-<slug> stood down: <reason>".
Do NOTHING else — no extra probes, no notes, no judgment. If check.sh itself fails to
run (non-zero exit, missing file), push: "watch-<slug> BROKEN: <error>" so the failure
is visible, and stop.
```

## Arming procedure

1. Derive: the probe commands, the trip predicate, the dedup stamps, the **expiry date**
   (ask if not stated — mandatory), and a cadence matched to how fast the external state
   actually changes (an hourly portal sync ≠ a 5-minute API).
2. Write `check.sh`. **Dry-run it once, now, in-thread, and read its output** — never arm
   an unverified probe. Busybox/GNU drift, auth, and empty-body traps live here (probe
   substance: HTTP code + body size + marker, never a bare grep count — an empty response
   greps as "success").
3. `create_scheduled_task` with taskId `watch-<slug>`, the cadence, and the courier
   template as prompt. Place `check.sh` in the created dir.
4. Confirm back: one line — what it watches, trips on, expires when, fires how often.

## Rails

- **Registry is truth.** Armed = the task exists in `list_scheduled_tasks`. Never record
  arm/disarm state in prose, memory notes, or vault files — that dual-truth caused the
  2026-07-22 zombie re-arm incident. Disarm = delete the task.
- Probes are **read-only**; a watch never logs in, writes remote state, or takes the
  action it's watching for. Irreversible follow-ups are Colin's, prompted by the ping.
- One external condition per watch. A second condition is a second watch.
- Heartbeat: `check.sh` stamps `state/last-run`; external staleness alerting (sux KV
  `gatherHealth` ingest) is tracked in SuxOS/.github — wire it when that lands.
- Doctrine + history: `SuxOS/.github` `docs/standing-automation.md` (why drummer died,
  design spec, the four-word taxonomy).

## Output

`[ARMED: watch-<slug>, trips on <predicate>, expires <date>, every <cadence>|REFUSED: <routed where + why>]`
