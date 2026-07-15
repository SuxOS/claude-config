# Dimension: GitHub survey + cross-repo synthesis

The fan-out-then-barrier core. Survey every repo in parallel, then one pass reads all surveys at once — because the valuable findings only exist *between* repos and can't be seen one repo at a time.

## Get the repo list

If scope resolved to org mode (`repos: null`), list them:
`gh repo list <org> --limit 1000 --json name,isArchived,updatedAt`
Drop archived repos unless the user asked to include them — they're not in-progress and only add noise to the comparison.

## Fan out — one agent per repo

Prefer **`Workflow`** (`parallel()` → barrier → synthesis): the cross-repo comparison genuinely needs every repo's data at once, so it's a barrier, not a pipeline. If the user hasn't opted into `Workflow` this session, fire one `Agent` per repo in a single message (still parallel), then synthesize yourself.

Each survey agent returns **structured data (schema), not prose** — the synthesis step compares fields across repos and that's brittle against free text. Gather via `gh`:
- Issues: `gh issue list --repo <r> --state open --json number,title,labels,body,updatedAt`
- PRs: `gh pr list --repo <r> --state open --json number,title,isDraft,updatedAt,mergeable`
- Actions: `gh run list --repo <r> --limit 10 --json status,conclusion,name,createdAt` — flag *repeated* failures, not just the latest run
- Settings: `gh api repos/<r>` (default branch, visibility) and `gh api repos/<r>/branches/<default>/protection` (required checks, review rules — a 404 means no protection, which is itself a finding, not an error)
- Dependency manifests, root-level only, if light: `package.json`, `go.mod`, `requirements.txt`, `Cargo.toml` — feeds version-drift. Don't deep-crawl.

## Synthesize — the actual deliverable

One pass over all surveys, looking only for what no single repo's view shows:

- **Repeated bugs/errors** — same failure signature (error string, failing check name, crash pattern) in issues or Actions across 2+ repos. Group by signature, not by repo.
- **Dependency/version drift** — a *shared* package/tool pinned to different versions across repos. Only for genuinely shared deps — two unrelated repos differing on an unrelated third-party lib is coincidence, not drift.
- **Org-settings drift** — branch protection / required checks / merge settings inconsistent across repos with no apparent reason. State the majority/expected setting and which repos deviate.
- **Blocked-by relationships** — issues/PRs referencing another repo (`owner/repo#N`, "blocked by", "depends on") or work that can't land until another repo changes. Prefer explicit textual links; if inferring, say so and show the evidence.

Report only what genuinely crosses repo boundaries. Unrelated single-repo bugs restated per repo is what `gh issue list` already does — not this skill's job. Nothing cross-repo this run? Say so plainly; don't pad.
