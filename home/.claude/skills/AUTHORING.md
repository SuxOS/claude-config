# Authoring the verb family

How to write or edit a verb skill so it stays consistent with the rest of the family. This is the
meta-skill the family had no home for — read it before adding a verb, changing the grammar, or
reshaping an existing `SKILL.md`. The grammar itself lives in [`../CLAUDE.md`](../CLAUDE.md); this
is about the *files* that implement it.

## The one rule that catches everything: test before you write

Writing a skill is TDD for prose. **No skill (or edit) without a failing test first.**

1. **RED** — run the pressure scenario *without* the change. Give a fresh model the bare request the
   skill is meant to handle and watch what it does wrong — capture the actual failure/rationalization
   verbatim ("this is too simple to brainstorm", "the linter passed so it's fine"). That failure is
   the spec.
2. **GREEN** — write the minimal skill text that addresses *those* words. Not a general essay on the
   topic — the specific counter to the observed failure.
3. **REFACTOR** — re-run the scenario. Close the loopholes the model now wriggles through. Repeat
   until it holds under pressure, not just when cooperating.

A skill written from imagination ("what should a good `foo` skill say?") instead of from an observed
failure is how you get 60 lines nobody needed. If you can't make the base model fail without it, you
may not need it.

## The frontmatter `description` is a trigger, not a summary

This is the highest-leverage and most-broken field. The `description` decides *when* the skill fires;
the body decides *what it does*. Keep them separate.

- **Describe triggering conditions only.** What situation/phrasing should invoke this? Never summarize
  the workflow in the description — models follow the description and skip reading the body, so a
  workflow-summary description gets half-followed from the frontmatter.
- **Pack the triggers.** Include the symbolic form (`/go`, `/bug?`), the plain-English phrasings
  ("just do it", "why is this broken"), and the boundary against neighbors (what makes this `bug?`
  and not `wtf?`). The recall system matches against this text — literal user phrasings earn their
  place.
- **Lead the body with `means:`** — one bold sentence of what the verb *is*, then how it differs from
  its nearest sibling. Orientation before mechanics.

## The section skeleton every verb follows

Match it so the family reads as one system. Not every verb needs every section; keep the order.

1. **`**verb** means: …`** — the one-line essence + the contrast with the nearest sibling.
2. **The mark / count dial** — how `.`/`?`/`!` and the ×1/×3/×5 tiers read *for this verb* (what
   intensity buys here — depth, generalization, coverage, aggressiveness). Illustrate the three
   canonical tiers; don't restate the generic "more = not sloppier" caveat (it's said once in
   CLAUDE.md).
3. **How to run it** — the numbered playbook. This is where folded-in rigor lives (iron rules,
   phase gates) — as *procedure the verb runs*, never as a competing auto-gate.
4. **Output** — the exact result line/shape, `[STATE|STATE] <desc>` where it fits.
5. **Hand off** — the boundaries: which verb takes over when this one's done or out of scope.
6. **Rails** — what doesn't bend regardless of count. Reversible-only boldness; irreversible/
   destructive still gates. State only the verb-specific additions; the universal rails are in
   CLAUDE.md.

## Form follows failure

Pick the shape from what goes wrong without the skill:

- **Discipline violation** (skips a step under pressure) → prohibition + the rationalizations it'll
  reach for, named so they're pre-empted (`bug`'s three-strikes, `fix`'s test-first).
- **Wrong-shaped output** → a positive recipe/contract (the register table in `paste`). Prohibitions
  backfire here — say what right looks like.
- **Omitted element** → a required slot in a template (the `Output` line shape).
- **Conditional behavior** → an observable predicate, not a vibe ("if three fixes failed", not "if
  it's being stubborn").

## House style

- Terse, declarative, em-dash-driven. No preamble, no "in this section we will". Match the voice of
  `go`/`wtf`/`fix` — read three before writing.
- **DRY across the family.** A rule true for every verb goes in CLAUDE.md and is referenced, not
  copied into each file — duplication rots when one copy changes. Fold into an existing section
  before adding a new one.
- No nuance/exemption clauses ("unless you feel it's unnecessary") — they're the loophole the
  pressure scenario will drive straight through.
- Keep it short. A verb that needs 200 lines is probably two verbs, or is restating the grammar.
- No `@`-style auto-loaded links in the body; reference sibling files by relative path in prose.

## When you change the grammar itself

Grammar changes (a new mark, a new adverb, a mode like `--loop`) ripple. After editing CLAUDE.md:
grep the whole `skills/` tree for the old form, update every verb that illustrated it, and delete
verbs that a new mode makes redundant (as `--loop` retired `developer`/`drainer`). Leave no dangling
`/oldverb` reference — a stale pointer is worse than none.
