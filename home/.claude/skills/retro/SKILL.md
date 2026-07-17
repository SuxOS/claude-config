---
name: retro
description: End-of-session harvester — scans THIS conversation's transcript for lessons learned but never durably captured (a bug's root cause, a gotcha that cost time, a corrected assumption, a design tradeoff with a "why" worth remembering) and proposes concrete CLAUDE.md/doc edits for human approval. Use for "retro", "what should we remember from this session", "did we learn anything worth writing down", "wrap up this session", "any lessons to capture before we close this out". Never fires automatically at session end — always asked for. Proposes edits only; never writes docs without approval.
---

# retro

**means:** read this session's own transcript, pull out the lessons that were learned but
would otherwise evaporate with the thread, and propose surgical doc edits — never write them
without a human saying yes. It directly counters the documented recurring miss: incident
lessons and superseded docs consistently never get folded back into CLAUDE.md/docs.

## Step 1 — scan the transcript for candidates

Read back over this conversation (not other sessions — `retro` is scoped to what just
happened here). A candidate is one of:

- a bug's **root cause**, once actually found (not the symptom, not the fix mechanics)
- a **gotcha** — something that cost real time because it wasn't obvious upfront
- a **corrected assumption** — something believed true that turned out false
- a **design tradeoff** with a "why" that isn't reconstructable from the code alone

Filter out routine work: normal feature implementation, expected tool usage, anything
already written down elsewhere, anything too situational to recur. If nothing survives the
filter, say so and stop — an empty result is a valid result, not a reason to invent one.

## Step 2 — find the right target for each candidate

Don't default to "add a new CLAUDE.md line." Match the lesson to where it actually belongs:

- A gotcha specific to one repo's workflow → that repo's `CLAUDE.md`, under its existing
  "Known gotcha" section (or equivalent) if one exists — see `~/Code/SuxOS/sux/CLAUDE.md`
  for the exact target shape: terse, bolded lead phrase, one to three sentences, a concrete
  trigger condition, an issue/PR reference if one exists.
- A rule true everywhere → the global `~/.claude/CLAUDE.md` (this repo's
  `home/.claude/CLAUDE.md`) — only if it's truly universal; most lessons aren't.
  Prefer folding into an *existing* numbered rule or the gotchas list over adding a new one
  (per this repo's own rule 6: "fold the fix into an EXISTING rule/doc before adding a
  new one").
- A skill-specific pattern → that skill's `SKILL.md` or a `references/*.md` under it.
- A durable decision/plan with no natural doc home → flag it for the user to route (e.g. a
  memory note, a design doc under `docs/`) rather than guessing.

If a lesson doesn't clearly belong anywhere, say that instead of forcing it into the nearest
file.

## Step 3 — draft surgical edits, matching house style

For each candidate, produce a diff-shaped proposal, not a paragraph of prose:

```
**File:** <path>
**Why:** <one line — what would have been avoided if this existed at session start>
**Edit:**
<the exact bolded-lead-phrase line(s) to add/change, in the target doc's actual style>
```

Match the target doc's existing tone exactly — terse and declarative for CLAUDE.md-style
files (see `AUTHORING.md`'s house style: no nuance clauses, no padding), fuller prose only if
the target doc is already fuller prose. Keep each edit to the smallest change that captures
the lesson — one to three lines, not a new section, unless the lesson genuinely needs one.

## Step 4 — present for approval, then act only on yes

List every proposed edit together, ask which to apply (all / some / none). Apply only the
ones approved, via normal `Edit`/git — no silent writes, no "I'll just add this one since
it's obviously right." This mirrors the human-gated pattern used everywhere else in this
org (dispatch's holds, work's PR-not-push-to-main default): a proposal is not an action.

## Rails

- Scoped to the current session's transcript only — don't scan other sessions or invent
  lessons that weren't actually observed here.
- Never write to any file before the user approves that specific edit.
- No candidate, no edit — don't pad a thin session with a manufactured lesson.
- One edit per lesson, smallest surgical form — this is not a changelog or a summary.
