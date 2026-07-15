---
name: org-watch
description: Org-management radar over a whole GitHub org and its local clones — the cross-cutting health checks that no single-repo view can surface. Runs a set of dimension checks (cross-repo GitHub survey of issues/PRs/Actions/settings; local git drift and thrashing; local↔remote coverage gaps; concurrent Claude Code sessions stepping on each other; MCP-server and HTTP-endpoint discovery and live health/connector testing) and synthesizes what's wrong *between* repos and sessions, not within one. Use whenever the user wants to monitor, watch, audit, or summarize "the org" / "all our repos" / "everything across the org", wants a cross-repo or org-wide status digest, asks what's inconsistent or drifting or colliding across repos or sessions, wants to know if two sessions are stepping on each other, wants a recurring org health report, or asks to discover/test/health-check MCP servers or API endpoints across a set of repos. Trigger even when only one signal is named ("check Actions across all repos", "are my sessions colliding", "test our MCP servers") — each is one dimension of this skill, not a separate task.
---

# org-watch

**org-watch means: the org-management radar — the cross-cutting checks that only show up *between* repos and sessions, never within one.** A per-repo scan is the raw input; the deliverable is what emerges when you compare repos, clones, and live sessions against each other.

## The framework — a spine + pluggable dimensions

Every check shares one spine: **resolve scope → run the selected dimensions (each filters itself to signal) → synthesize what's cross-cutting → report.** Each dimension is independent and self-contained, so the skill scales by *adding a dimension file*, not by growing this spine. Run only the dimensions the request calls for — a bare `/org-watch` runs them all; "are my sessions colliding" runs just one.

| Dimension | When to run it | Playbook | Script |
|---|---|---|---|
| **GitHub survey** | default; any cross-repo issue/PR/Actions/settings question | `references/github.md` | (gh calls) |
| **Local drift** | clones exist under cwd; "what's uncommitted / drifting locally" | `references/local.md` | `scripts/local_drift.py` |
| **Sessions colliding** | "stepping on each other", concurrent-work risk | `references/sessions.md` | `scripts/session_collisions.py` |
| **Endpoints & MCP** | "discover/test our MCP servers or endpoints" | `references/endpoints.md` | `scripts/discover_endpoints.py` |

Read a dimension's reference file only when you're running it — that's the progressive-disclosure win of this layout. Don't inline their detail here.

## Step 0 — resolve scope (cwd is the org root)

Run `scripts/resolve_scope.py [tokens...]` from the directory the user means (usually cwd). Returns `{org, repos, mode, inferred}`.

Token syntax (space-separated, combine freely):
- *(none)* — infer from cwd. cwd is itself a repo → scope to that repo. Else scan immediate subdirs that are git repos, take the most common remote owner as the org, scope to the whole org. Falls back to the directory basename if nothing's inferable — **say so when this fallback fires**, it's a guess.
- `org:<name>` — explicit org, all repos, ignores cwd.
- `repo:<name>` — single repo, org inferred from cwd.
- `repo:<owner>/<name>` — single repo, fully explicit.
- Multiple tokens — union.

Don't make the user spell out the org when it's inferable — the whole point of the cwd-as-root convention is that `/org-watch` just works from inside a workspace of clones. Ask only when genuinely ambiguous (e.g. subdirs split evenly across two orgs).

## Step 1 — run the selected dimensions

Fan them out — the dimensions are independent, so run their scripts/agents concurrently, not one after another. Each dimension's reference file owns its own "filter to signal" rules; the spine's only job is to collect their findings. **The filter is the discipline of this whole skill: a healthy repo, a clean clone, a working endpoint, a solo session all get zero lines.** The report names what's *off*.

## Step 2 — synthesize + report

Some findings are single-dimension (a broken endpoint). The highest-value ones are *cross-dimension* — a live session (sessions) sitting on a diverged branch (local drift) that has an open PR (GitHub). Join across dimensions where the evidence lines up; that correlation is the payoff of running them together instead of as four separate tools.

```markdown
# Org Watch: <org>
_Scope: <mode>, N repos · dimensions run: <list>_

## Sessions & collisions        ← highest severity when live; lead with it if present
## Cross-repo findings          ← repeated bugs · dependency/version drift · settings drift · blocked-by
## Local drift                  ← uncommitted/diverged · thrashing/stale branches · coverage gap
## Endpoints & MCP              ← failed handshakes · not-installed connectors (offer to install) · unhealthy endpoints · schema drift

## Per-repo snapshot            ← one line each, reference only — not the point of the report
```

Any section with nothing to report says "none found" in one line — don't omit it (the user should see it was checked) and don't pad it. Lead with whatever's most urgent this run; live session collisions outrank a stale endpoint.

## Recurring digests

On-demand by default. For a recurring org-health digest, wire it through the `cron` verb / `schedule` skill — org-watch does the survey-and-report, `cron!` owns *when*. Don't build scheduling in here.

## Extending the framework — adding a dimension

The whole point of the spine is that a new check is a new *file*, not a rewrite. To add one: drop a `references/<dim>.md` playbook (what to gather, how to filter to signal), add its deterministic scan to `scripts/` if there is one, add a row to the dimension table above and a section to the report skeleton. Keep each dimension self-contained and self-filtering so the spine never grows. Read `AUTHORING.md` in the skills root for the house style; the cwd-as-org-root convention here is worth reusing in any skill that operates over multiple repos.
