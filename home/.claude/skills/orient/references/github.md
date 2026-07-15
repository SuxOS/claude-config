# Dimension: GitHub survey + cross-repo synthesis

Fan-out-then-barrier. Survey every in-scope repo in parallel, then one pass reads all
surveys at once — the valuable findings only exist *between* repos.

## Get the repo list

From the resolved locus: the in-scope org's `repos` in `~/.claude/fabric.json` (repo locus
= just the current one). That declared set is also what surfaces *coverage* drift (an org
repo missing from the list, or a listed repo with no clone). Only enumerate live when the
fabric is absent:
`gh repo list <org> --limit 1000 --json name,isArchived,updatedAt` (drop archived unless asked).

**Tool choice: `gh` by default; GitHub MCP (`mcp__github__*`) when connected** (needs
`GITHUB_PERSONAL_ACCESS_TOKEN`; check via `ToolSearch` before assuming). Prefer MCP for
structured calls; `gh` is the always-works fallback. Don't block on the MCP.

## Fan out — one survey per repo, structured output

Each repo's survey returns **structured data (schema), not prose** — synthesis compares
fields across repos and that's brittle against free text. Gather via `gh`:

- Issues: `gh issue list --repo <org>/<r> --state open --json number,title,labels,body,updatedAt`
- PRs: `gh pr list --repo <org>/<r> --state open --json number,title,isDraft,updatedAt,mergeable,labels`
- Actions: `gh run list --repo <org>/<r> --limit 10 --json status,conclusion,name,createdAt` — flag *repeated* failures, not just the latest
- Settings: `gh api repos/<org>/<r>` (default branch, visibility) + `gh api repos/<org>/<r>/branches/<default>/protection` (required checks, review rules — a 404 = no protection, itself a finding)
- Manifests, root-level only, if light: `package.json`/`go.mod`/`requirements.txt`/`Cargo.toml` — feeds version-drift. Don't deep-crawl.

If the user opted into `Workflow` this session, use it (`parallel()` → barrier →
synthesis). Otherwise fire one `Agent` per repo in a single message, then synthesize.

## Synthesize — the actual deliverable

One pass over all surveys, only what no single repo's view shows:

- **Repeated bugs/errors** — same failure signature (error string, failing check name) in
  2+ repos. Group by signature, not by repo.
- **Dependency/version drift** — a *shared* package/tool pinned to different versions
  across repos. Genuinely shared deps only.
- **Org-settings drift** — branch protection / required checks / merge settings inconsistent
  across repos with no reason. State the majority setting and which repos deviate.
- **Blocked-by** — issues/PRs referencing another repo (`owner/repo#N`, "blocked by",
  "depends on"). Prefer explicit textual links; if inferring, say so and show the evidence.

Report only what genuinely crosses repo boundaries. Nothing cross-repo this run? Say so
plainly; don't pad.
