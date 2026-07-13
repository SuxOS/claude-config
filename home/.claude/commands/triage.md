---
description: Independently investigate untriaged GitHub issues and queue most for build (stage 2 of propose → investigate → build; see /fixer and /issue-build)
---

You are the investigator — stage 2 of a three-stage pipeline: propose (`/fixer`) → investigate (you) → build (`/issue-build`). You are independent of whoever filed an issue: judge the substance, not the filer's framing or self-rated confidence.

## Scope

Operate only on the git repo rooted at the current working directory. Confirm it's a repo and identify its GitHub remote before doing anything else.

## Select untriaged issues

"Untriaged" = open, and carrying NONE of: `queued-for-build`, `building`, `hold`, `triaged`.

```
gh issue list --state open --limit 200 --json number,title,body,labels
```

Filter to issues whose label set has none of those four. If there are none, say so and stop.

## Investigate each

For every untriaged issue, read it in full (`gh issue view <n>`) and read enough of the actual code to form your own view — do not trust the filer's framing or their `confidence:*` label.

> **Collect verdicts, then label — never delegate the write.** You may fan out to sub-agents to investigate issues in parallel, but a sub-agent's job is to **return a verdict** (`{number, type, confidence, buildable, reason, research_note}`), NOT to apply labels and NOT to be trusted when it says "done." Labels get applied by YOU, once, in the single pass below, after every verdict is in hand. Delegating the label write to a child and reporting complete on the child's say-so is the exact bug this skill must avoid: the parent reports finished while the writes never landed. Mirror the `triage.yml` workflow — model produces verdicts, one deterministic step applies them.

### Research — only where the code can't answer it

Most issues are decided from the repo alone; **do not research those.** Research only when your confidence/buildable call genuinely hinges on an external fact the code cannot settle — e.g.:

- an upstream library/API/runtime's *actual* documented behavior or contract (the repo shows how it's *called*, not whether that's correct),
- whether a reported error or symptom is a *known* bug/CVE/regression (and if it's already fixed upstream),
- what a spec / standard / RFC actually mandates,
- current best practice for a "should we do X" feature where the right answer isn't in-repo.

When (and only when) one of those is the deciding factor, do a **focused** lookup — 1–3 targeted `WebSearch`/`WebFetch` queries (or the `sux` connector's research functions if available), not open-ended browsing. Then fold the finding into your decision. Do **not** research style/refactor calls, anything the repo is the source of truth for, or to pad a decision you could already make.

If research materially changed or confirmed your call, record it: `gh issue comment <n> --body "🤖 Triage research: <finding + source URL>"` — so the finding is auditable and the `/issue-build` stage inherits the context instead of re-discovering it. Cite the source; don't state researched facts as if from memory.

Decide, on your own read:
- **type**: `bug` | `enhancement` | `security` | `documentation`
- **confidence**:
  - `high` — you confirmed it's real by reading the code AND the change is narrow, unambiguous, low-risk. This is the bar that lets a build merge with **no human review** (see `/issue-build`), so reserve it — most net-new features and anything you couldn't fully confirm are NOT high.
  - `medium` — real/worthwhile but with scope or judgment to it.
  - `low` — weak, big, ambiguous, or you couldn't confirm it.
- **buildable**: true unless an unattended coding session genuinely can't do it — a question, a duplicate, needs credentials/private access/a human *decision*, or is too vague/large to attempt safely. **Default to true** — the aim is that most work drains autonomously, not that most work stalls waiting on a human. Note: "needs external info" is often *not* a blocker anymore — if you can research the missing fact yourself (above) and drop it on the issue, it becomes buildable. Only reserve `needs-human` for what research genuinely can't resolve.

## Apply labels — you apply them, in one pass, after all verdicts are in

Only start this once you hold a verdict for **every** issue (if you fanned out, after every sub-agent has returned — the parent does the writing, not the children).

Create the labels first if they don't exist (`gh label create <name> --description "..." --color <hex>`): `triaged`, `confidence:high` (`0e8a16`), `confidence:medium` (`fbca04`), `confidence:low` (`ededed`), `needs-human` (`d93f0b`).

For every issue, apply its labels yourself with a real `gh issue edit` call — one issue, one call, atomically:
- Always add `triaged` (so it isn't re-investigated next run) + your `type` + `confidence:<level>`.
- If buildable: also add `queued-for-build` (this is what fires `/issue-build`).
- If not buildable: also add `needs-human` and comment why: `gh issue comment <n> --body "🤖 Triage held this off autonomous build: <reason>. Add queued-for-build yourself to override."`

Put the whole set on in one edit, e.g.:
```
gh issue edit <n> --add-label triaged --add-label <type> --add-label confidence:<level> --add-label queued-for-build
```

## Verify it landed — before you report anything

This is the gate that closes the race. After the apply pass, **re-query ground truth** and confirm every issue you investigated now actually carries `triaged`:

```
gh issue list --state open --limit 300 --json number,labels \
  --jq '[.[] | select((.labels|map(.name)) | index("triaged") | not) | .number]'
```

Every number you just processed must be **absent** from that list. If any is still present, its labels did not land — re-apply for those, then re-query. **Do not report done until this check is clean.** Never treat "I issued the command" or a sub-agent's "completed" as proof; only the re-query is proof.

## Output

Report only after the verify gate is clean. Summarize: how many issues investigated, how many needed research (and what it changed), how many queued (by confidence tier), how many held as `needs-human` (with why), and confirm the post-apply re-query showed zero of your issues still untriaged. Mention `/issue-build` is the next stage.
