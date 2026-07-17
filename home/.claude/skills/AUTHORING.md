# Authoring the tools

How to write or edit a skill so it stays consistent with the rest. Read it before adding a
tool, adding a dimension, or reshaping a `SKILL.md`. The locus tools themselves are
`orient`, `work`, `dispatch`, `paste`, plus the meta helper `how` (find the right
skill/MCP/agent for a goal — not locus-scoped); the model they live in is in
[`../CLAUDE.md`](../CLAUDE.md) and [`../../../WORKFLOW.md`](../../../WORKFLOW.md).

## The one rule that catches everything: test before you write

Writing a skill is TDD for prose. **No skill (or edit) without a failing test first.**

1. **RED** — run the pressure scenario *without* the change. Give a fresh model the bare
   request the skill is meant to handle and watch what it does wrong — capture the actual
   failure/rationalization verbatim ("this is too simple to plan", "the linter passed so
   it's fine"). That failure is the spec.
2. **GREEN** — write the minimal skill text that addresses *those words*. Not a general
   essay on the topic — the specific counter to the observed failure.
3. **REFACTOR** — re-run the scenario. Close the loopholes the model now wriggles through.
   Repeat until it holds under pressure, not just when cooperating.

A skill written from imagination ("what should a good `foo` skill say?") instead of from an
observed failure is how you get 60 lines nobody needed. If you can't make the base model
fail without it, you may not need it.

## Eval fixture schema

Every `evals/evals.json` is enforced by CI (`.github/scripts/lint-evals.py`, job
`evals-lint`) — not just linted for valid JSON. Top level is an object:

```json
{
  "skill_name": "how",
  "evals": [
    {"id": 1, "prompt": "...", "expected_output": "...", "files": []}
  ]
}
```

- `skill_name` — non-empty string, must equal the owning directory name
  (`skills/<name>/evals/evals.json` → `skill_name` is `<name>`).
- `evals` — a non-empty list of eval items, each requiring:
  - `id` — an integer, unique within the file.
  - `prompt` — a non-empty string: the pressure scenario given to a fresh model.
  - `expected_output` — a non-empty string: the grader's rubric for what a pass looks like.
  - `files` — a list of fixture files the scenario needs (`[]` when none).

Write the `prompt`/`expected_output` pair from an observed RED failure (see above), not
from imagination — the fixture is the encoded discipline, not busywork for the linter.

## The frontmatter `description` is a trigger, not a summary

The highest-leverage, most-broken field. The `description` decides *when* the skill fires;
the body decides *what it does*. Keep them separate.

- **Describe triggering conditions only** — what situation/phrasing should invoke this.
  Never summarize the workflow in the description; models follow it and skip the body, so a
  workflow-summary gets half-followed from the frontmatter.
- **Pack the triggers** — the plain-English phrasings a user actually types ("what's going
  on", "ship it", "stop the remote workflows") and the boundary against neighbors (what
  makes this `orient` and not `work`). The recall system matches against this text.
- **Lead the body with `means:`** — one bold sentence of what the tool *is*, then how it
  differs from its nearest sibling. Orientation before mechanics.

## Two skill shapes

**Action tool** (`work`, `dispatch`) — a playbook that produces a change. Skeleton:
`**means:** …` → **Scope** (what it operates on) → **How to run it** (the numbered
playbook, where folded-in rigor lives as *procedure*) → **Output** (`[STATE|STATE] <desc>`)
→ **Rails** (what doesn't bend; state only the tool-specific additions — universal rails
are in CLAUDE.md).

**Domain skill** (`orient`) — a self-contained capability with its own architecture.
Follow the pattern `orient` proved:

1. **A spine that never grows** — resolve scope → run dimensions → synthesize → report.
   The backbone stays tiny; domain knowledge lives in pluggable pieces the spine collects.
2. **Self-contained, self-filtering dimensions — one file each** (`references/<dim>.md`),
   with a `scripts/<dim>.py` only where the logic is genuinely exact/non-trivial (rule #2);
   prefer inline `gh`/`git`. A dimension table maps *when to run it* → *its file*. Read a
   dimension's file only when running it. **The filter is the discipline: a healthy thing
   emits zero lines.**
3. **Synthesis is the deliverable** — the value is what emerges *across* dimensions, which
   no single one sees.
4. **Read one declared source of truth as the front door** (`~/.claude/fabric.json`), never
   a resolver; fall back to a convention only when it's absent, ask only when ambiguous.
5. **Hand off** — even a domain skill ends by naming which tool acts on each finding. It
   surveys and routes; it doesn't repair.

## The locus-detection convention (shared by every locus tool)

Every tool that acts on the workspace/org/repo tree resolves its locus the same way — a
few deterministic lines, no LLM, no per-tool reinvention:

- Read `~/.claude/fabric.json` for `workspace_root` and `orgs`.
- `git rev-parse --show-toplevel` succeeds and sits under an org dir → **repo** locus
  (scope = that repo).
- cwd is an org dir directly under `workspace_root` → **org** locus (scope = that org's
  `repos`).
- cwd is `workspace_root` → **workspace** locus (scope = all orgs).
- fabric absent → infer from cwd and *say you're guessing*.

Don't grow a script for this; it's a convention, not a component.

## Form follows failure

Pick the shape from what goes wrong without the skill:

- **Discipline violation** (skips a step under pressure) → prohibition + the
  rationalizations it'll reach for, named so they're pre-empted.
- **Wrong-shaped output** → a positive recipe/contract (the register table in `paste`).
- **Omitted element** → a required slot in a template (the `Output` line shape).
- **Conditional behavior** → an observable predicate, not a vibe ("if two passes came back
  empty", not "if it seems done").

## House style

- Terse, declarative, em-dash-driven. No preamble. Read `orient`/`work` before writing.
- **DRY.** A rule true for every tool goes in CLAUDE.md and is referenced, not copied —
  duplication rots when one copy changes.
- No nuance/exemption clauses ("unless you feel it's unnecessary") — that's the loophole
  the pressure scenario drives straight through.
- Keep it short. A skill that needs 200 lines is probably two skills.
- No `@`-auto-loaded links in the body; reference sibling files by relative path in prose.

## When you change the fabric or the tool set

Changes ripple. After editing `fabric.json`'s shape or renaming a tool: grep the whole
`skills/` tree (and `WORKFLOW.md`, `CLAUDE.md`, `README.md`) for the old field/name, update
every reference, and delete anything a change makes redundant. Leave no dangling pointer —
a stale reference is worse than none.
