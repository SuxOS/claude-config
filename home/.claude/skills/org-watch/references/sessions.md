# Dimension: sessions stepping on each other

Two independent workstreams touching the same repo, branch, or files at once — silent lost work, merge races, or two PRs fixing the same thing. This dimension has two halves that must be **correlated**: neither alone tells you there's a collision.

## Half 1 — live Claude Code sessions (agent step, MCP)

Call `mcp__ccd_session_mgmt__list_sessions` (add `get_session` for branch/worktree/remote detail on the interesting ones). The collision signals:

- **Two+ sessions with `isRunning: true` in the same `cwd`** (or in cwd's that are the same repo / overlapping worktrees). This is the headline case — concurrent live sessions on the same working tree will overwrite each other's edits.
- **Two sessions on the same branch** — even in different worktrees, they'll race on push.
- **A session with an open PR (`prNumber`, `prState: OPEN`) on a branch another session is also committing to** — the second session's work strands outside the PR the first is driving.

Note: the *current* session is excluded from `list_sessions`, so remember to count yourself — if you're running in `/x` and one other session is running in `/x`, that's a collision of two, not "one lonely session."

## Half 2 — git state those sessions leave behind (script)

Run `scripts/session_collisions.py [root]`. Deterministic — a script can't see sessions, but it sees the tracks they leave:
- `same_branch_multiple_checkouts` — one branch checked out in 2+ working trees (duplicate clones / worktrees both on `feature/x`; pushes will race)
- `worktrees` — registered `git worktree` entries per repo, with branches (the map to correlate against session cwds)
- `diverged_active` — a branch both ahead AND behind origin (local and remote each moved — a force-push or a second writer)
- `open_pr_with_local_edits` — uncommitted/unpushed work on a branch that already has an open PR (edits stranded outside the PR another session drives)

## Correlate and report

Join the two: a running session's `cwd`/branch that lands on a `same_branch_multiple_checkouts` entry, or a diverged branch that a live session is sitting on, is a *confirmed* collision — report it with both the session (title, id) and the git evidence (branch, paths). Git-only signals with no live session behind them are lower-severity ("stale collision risk"), still worth a line. Live-only overlap (two sessions, same cwd) is the highest severity — flag it first and, if the user wants, offer to help one session stand down (stash/branch-off) rather than both writing.

Also surface **same-named branches across different repos** (e.g. `fix-x` in three repos) — not a collision, but a coordinated multi-repo change in flight the user should know is a single logical unit.
