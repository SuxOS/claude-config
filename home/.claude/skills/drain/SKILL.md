---
name: drain
description: The domain-agnostic backlog-drain verb — find the highest-value doable item in ANY backlog (a Downloads folder, a Dropbox Inbox, a mail queue, a notes vault, a research reading list, the `/queue` backlog) and take it end-to-end, as **one bounded burst**, then return. Act family; sibling of `/develop`, which is the same pattern narrowed to git/PR. Bare/no-args self-scopes to whatever backlog is in context ("just sort it out"); a hint scopes what, the `!` count + adverbs scope how hard and how wide. Its looping sibling `/drainer` runs bursts until dry. Use whenever the "develop" pattern applies outside a git repo — "/drain", "clear out my downloads", "work through the inbox", "sort this folder", "drain the queue", "the backlog's piling up", "file these away".
---

**`drain` means: find the backlog and clear the highest-value slice of it, end-to-end** — no ceremony. `develop` is this exact pattern with the domain pinned to git (branch → code → verify → PR). `drain` is the general case: the object is any pile of undifferentiated stuff that needs sorting, filing, answering, or discarding-into-order — a folder, an inbox, a mail queue, a stack of open questions. It runs **one burst** then hands the thread back. To keep going until the pile is empty, that's the looping sibling `/drainer` (this verb in a `while (not dry)`).

## Why a separate verb from `develop`

The cardinal grammar says "any domain, one grammar" — but `develop`'s SKILL.md is written entirely in git terms (worktrees, `gh pr create`, merge queues) because that's the domain it was built for. Trying to force a Downloads-folder cleanup through `develop`'s branch/PR/CI vocabulary doesn't fit, and generalizing `develop` in place would blur a skill that's tuned hard for one domain. `drain` exists so the *pattern* (find highest-value unit → do it → verify → repeat) has a home that isn't wearing git's clothes.

## The locus router (what runs where)

Same iron rule as `develop`: **never dispatch onto a jam.** Before doing anything, figure out what kind of backlog you're draining — the domain picks the tools, not the verb:

- **Files** (Downloads, Desktop, an inbox folder) → `mv`/checksum-dedup/pattern-classify against an existing taxonomy if one exists (check for a spine folder, an INDEX.md, a prior sort pass) rather than inventing a new one each time.
- **Life/mail/vault** (unread mail, a Dropbox Inbox, Obsidian notes) → the `sux:life` skill's capture/organize machinery.
- **Local task backlog** → the `/queue` skill's contents, or `TaskList`.
- **Code, but scoped to one non-PR unit** (a lone script, a config fix with no repo ceremony) → still `drain`, not `develop` — `develop` is specifically the branch→PR shape.
- **Research/reading backlog** (a list of open questions, unread papers) → `deep-research` or plain investigation per item.

If the backlog itself is unhealthy — a folder so large or ambiguous that sorting it blind would be guessing, a taxonomy that doesn't exist yet — that's a jam: stop and propose the taxonomy first rather than drain into disorder.

## `!` count + hint = scope

No mark **gates** (proposes what it'll do first, especially before any file move or send); any `!` **produces**.

- **`/drain`** (bare) — self-scope: look at what's obviously piling up in context (a folder just discussed, an open inbox), pick the top doable unit, **propose it, then act on your ok**.
- **`drain!`** — pick and clear one unit, here, now. Skip the gate.
- **`drain!!!`** — clear a whole cluster: dedupe, file the obvious cases, fan out independent sub-piles (a batch of files can go through pattern-classification concurrently; a batch of emails cannot — use judgment, don't force parallelism where the items aren't independent).
- **`drain!!!!!`** — full sweep of everything currently backlogged in the domain, in one bounded pass. (Repeat-until-dry across *sessions* is `/drainer`.)

**Hint = the noun**: `drain! ~/Downloads` · `drain! the Dropbox Inbox` · `drain! my unread mail`. **Adverbs tune the rest** — `risk=` (how bold the moves — deleting vs. just relocating), `verify=` (spot-check the result vs. `bet?` it), `parallel=`. `--dry` shows the plan and touches nothing · `--suggest` proposes + recommends · `--force` skips the soft gate (hard rails still hold).

## How to run it

1. **Identify the backlog and its existing taxonomy.** Don't invent a new filing scheme if one already exists (an INDEX.md, a folder structure, a labeling convention) — extend it. If none exists and the pile is nontrivial, propose one before moving anything.
2. **Prefer deterministic sorting over per-item judgment calls** (cardinal rule #2) — checksum-dedup against a known-good archive, pattern-match by extension/filename, before falling back to reading content one file at a time.
3. **Size to one burst.** Take the highest-value slice that fits in one session; overflow is for `/drainer` or `fork!`, not a churning context.
4. **Act, reversibly.** Moves, not deletes — see Rails below. Never guess on anything that touches credentials, legal/medical/financial documents, or another person's data; flag and ask rather than filing on assumption.
5. **Verify + hand back.** Spot-check that things landed where the taxonomy says (`bet?` at higher rigor if the batch was large or the content sensitive).

## Output

One line per unit — outcome, not narration:

`[FILED|SORTED|ANSWERED|CLEARED|FLAGGED: <needs a human call>|BLOCKED: <reason>] <short desc>`

At higher count, follow with an **Assumptions** list (self-scoped picks and any new taxonomy decisions are things the user can veto) and a one-line count of what's left in the pile.

## Hand off

- Git repo, branch/PR shape → `/develop` (this verb's code-specific sibling).
- Keep clearing until the pile's empty → `/drainer`.
- Recurring/unattended → `/cron! /drain @nightly` or `/drainer @nightly` (persisting a schedule asks first).
- Don't block the thread → `fork!`.
- Just capture one item without acting → `/queue!`.
- Prove a big sort actually landed right → `bet?`.

## Rails that don't bend

Never permanently delete, empty trash, send on the user's behalf, or touch credentials/keys without asking — see the global safety rules. A high count buys boldness only on **reversible** moves (file relocation within the user's own filesystem/storage). Anything that looks like it crosses into "explicit permission required" (sending a message, publishing, entering data into a form) or "prohibited" (deleting, credentials) stops and asks, regardless of `!` count. Moving files into a clearly-labeled holding folder is always safer than deleting when in doubt — leave the undo path open.
