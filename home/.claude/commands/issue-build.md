---
description: Cluster queued-for-build issues (n issues → m PRs) and build one PR per cluster (stage 3 of propose → investigate → build; see /fixer and /triage)
---

You are the collator+builder — stage 3 of a three-stage pipeline: propose (`/fixer`) → investigate (`/triage`) → build (you). Merge is opt-out by default: a cluster where every issue is `confidence:high` auto-merges; everything else opens a PR that stages for human review.

## Scope

Operate only on the git repo rooted at the current working directory. Confirm it's a repo and identify its GitHub remote before doing anything else.

## 1. List and cluster

```
gh issue list --state open --label queued-for-build --json number,title,body,labels
```

If empty, say so and stop. Otherwise group RELATED issues together — same root cause, same feature area, or issues that would touch the same files — into clusters (n issues → m clusters, m can be less than n; **never collapse everything into one cluster** unless the backlog genuinely is one connected piece of work).

**Confidence-purity rule**: never put a `confidence:high` issue in the same cluster as a non-`confidence:high` issue. A pure all-high cluster is what makes its PR eligible to auto-merge unattended; mixing tiers would either wrongly auto-merge an unverified change or force a genuinely-safe change to stage. Split by confidence tier first, then group by relatedness within each tier.

For each cluster, name it (kebab-case id), and write a one-line PR title (conventional-commit style) and a short summary.

## 2. Claim

For every issue you're about to build, swap its label: `gh issue edit <n> --remove-label queued-for-build --add-label building`. This is the claim — if this session dies partway, the issue stays visibly `building` rather than silently vanishing from the queue (a human or a future `/issue-build` run can requeue it by re-adding `queued-for-build`).

## 3. Build each cluster — isolated, in parallel where possible

For each cluster, work in an isolated **detached scratch worktree** (never build multiple clusters in the same checkout — they'd collide):

```
git fetch origin main --quiet
git worktree add --detach /tmp/issue-build-<cluster-id> origin/main
```

Inside that worktree, on a new branch (`bot/issue-build-<cluster-id>`): implement every issue in the cluster (`gh issue view <n>` for full detail) as one coherent change. Run the repo's actual gates (type-check/test/lint/build — check `CLAUDE.md`/`package.json`/CI config for the real commands, don't guess). Commit (conventional-commit message) only if the gates pass.

If multiple clusters exist, use the Agent tool to run their builds concurrently (one agent per cluster, each in its own worktree) rather than sequentially — they're independent by construction (confidence-pure, unrelated-file clusters).

If a cluster's gates don't pass and you can't fix it within reason: do NOT push a broken commit. Instead, `gh issue edit <n> --remove-label building --add-label queued-for-build` (requeue) and comment why on each issue in the cluster.

## 4. Push and open the PR

For a cluster that got a real commit: push the branch, then determine eligibility **from the issues' actual current labels** (never from the title you wrote — that would be circular): eligible only if EVERY issue in the cluster has `confidence:high` and NONE has `hold`.

```
gh pr create --base main --head bot/issue-build-<cluster-id> \
  --title "<title>" \
  --body "<summary>

Closes #<n1>, Closes #<n2>, ...

🤖 Built by /issue-build." \
  --label "<automerge if eligible, else needs-review>"
```

Then clear the claim label on each issue: `gh issue edit <n> --remove-label building`.

Clean up the worktree after: `git worktree remove /tmp/issue-build-<cluster-id>`.

## Output

Summarize: clusters built (with PR links + automerge/needs-review), clusters requeued (with why), total issues closed vs. still open.
