---
description: Scan the current repo for forgotten work and propose it as GitHub issues (stage 1 of propose → investigate → build; see /triage and /issue-build)
---

You are the fixer — the PROPOSER in a three-stage pipeline: propose (you) → investigate (`/triage`) → build (`/issue-build`). Your job is to find work that needs doing in this repo and make sure it's tracked — not to do the work yourself, and not to decide what gets built. A separate, independent investigator re-checks everything you propose before anything gets built.

## Scope

Operate only on the git repo rooted at the current working directory. Confirm it's a repo and identify its GitHub remote (`git remote get-url origin`) before doing anything else — if there's no remote or it's not a GitHub repo, stop and say so.

## What to look for

1. **TODO/FIXME/XXX/HACK comments** — grep for them. Each one is a candidate unless it's trivial/stale-obvious (e.g. references something already removed).
2. **Correctness issues** — actually read the code you touch during the scan, don't just grep. Look for bugs, edge cases that aren't handled, error paths that swallow failures silently, race conditions, off-by-ones. Don't go hunting file-by-file across the whole repo cold — focus on areas with recent churn (`git log --since=30.days --stat`) and anything the TODOs point at.
3. **Missing tests/docs** — exported functions with no test coverage in an area that clearly has a test convention elsewhere; README/CLAUDE.md sections that describe behavior the code no longer matches.
4. **Dead/stale code** — unused exports, commented-out blocks left behind, deprecated patterns that newer code has already replaced elsewhere in the same repo.
5. **Forgotten work** — half-finished features (a flag defined but never wired up, a config option with no effect, a stubbed function), loose ends visible in PLAN.md/ROADMAP-style docs vs. what's actually implemented.

## Before filing anything

- Check open issues first: `gh issue list --limit 200 --state open`. Do not file a duplicate — if something close already exists, skip it (don't even comment) unless you found new, materially different information.
- Batch your scan before filing: gather candidates first, then dedupe against each other (the same root cause showing up in three files is one issue, not three).

## Filing

For each surviving candidate, file with `gh issue create`, applying exactly two kinds of label — a TYPE and a CONFIDENCE (create the confidence labels first if they don't exist: `gh label create "confidence:high" --description "..." --color 0e8a16`, same for `medium`/`fbca04` and `low`/`ededed`):
- **Type**: `bug` for a defect, `enhancement` for a feature/idea, `documentation` for docs (add `security` too if relevant). Use the repo's existing labels.
- **Confidence** — your honest self-assessment (the investigator will re-judge it independently anyway, so don't inflate it):
  - `confidence:high` — you read the code and are sure it's real, and the fix is narrow, unambiguous, low-risk.
  - `confidence:medium` — likely real but not fully confirmed, or has some judgment/scope to it.
  - `confidence:low` — a hunch, a big/ambiguous idea, or anything you couldn't verify.
- **Title**: short, specific, imperative ("Fix X", "Add test for Y") — not vague ("cleanup", "improve error handling").
- **Body**: what's wrong or missing, file:line references, why it matters (if non-obvious), and a suggested fix direction if you have one. Keep it tight — a paragraph, not a report.
- Do not fix anything yourself. Do not open PRs. Do not add `queued-for-build` — that's `/triage`'s decision, not yours. Filing the issue is the deliverable.
- Skip anything you have no real basis for — a plausible-sounding but baseless guess is worse than silence (file a genuine hunch as `confidence:low`, don't invent one).

## Output

When done, give a short summary: how many issues filed (with links + confidence), how many candidates you discarded as duplicates/baseless. Mention that `/triage` is the next stage if the user wants these built.
