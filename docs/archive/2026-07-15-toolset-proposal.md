# SuxOS toolset proposal — full scope

**Date:** 2026-07-15
**Status:** proposal, not yet applied
**Scope:** every tool/service surfaced across this session's audit, corrected against a
sourced research pass (124 extracted claims, deep-research workflow). Paid services
allowed — budget is not the constraint; evidence is.

## Corrected finding — GHAS is not the clear win it looked like

Earlier this session I recommended buying GitHub Advanced Security outright. The research
pass **corrects that** with real, sourced numbers:

- GHAS needs GitHub Enterprise Cloud (~$21/user/mo) **plus** the GHAS add-on
  (~$49/committer/mo) **plus a separate Secret Protection license** (~$19/committer/mo)
  for secrets specifically. (Org is already on Enterprise per an earlier check, so only
  the add-on costs are marginal — but it's still $49–68/committer/mo, not free.)
- CodeQL (GHAS's scanner) covers ~12 languages and runs ~3x slower than Semgrep,
  5–20+ min per run, blocking PRs.
- Semgrep Team ($40/dev/mo) needs no Enterprise gate, covers 40+ languages, and its
  Supply Chain product cuts SCA false positives ~98% vs. Dependabot via reachability
  analysis.
- Counter-evidence exists too: in one benchmark CodeQL found *more* planted
  vulnerabilities than Semgrep (21/27 vs 19/27, behind Snyk's 23/27) — GHAS isn't
  strictly worse on detection, just pricier and narrower in language coverage.
- **The research's own convergent advice for small/solo teams: run two of the three
  (GHAS/Semgrep/Snyk) together, not one** — no single tool is a complete answer.
- Snyk's free tier works on *any* GitHub plan (not Enterprise-gated) with monthly caps
  (100 SAST/400 SCA/300 IaC scans) — the most accessible free option for a solo operator.

**Revised recommendation:** keep GitHub's native secret scanning + push protection
everywhere ($0, already 3/4 repos, fix `sux-fileops`'s gap) as the floor. Add
**Semgrep Team ($40/mo)** as the primary SAST/SCA layer — cheaper, faster, broader
language coverage, no platform-tier prerequisite. **Skip the GHAS/CodeQL add-on** — the
evidence doesn't support its cost premium over Semgrep at this org's scale. Revisit GHAS
only if Semgrep's detection proves insufficient in practice.

## New finding the research surfaced, not previously on the radar

**Hallucinated-dependency squatting.** A cited risk specific to AI-driven autonomous
coding: LLMs sometimes recommend package names that don't exist, and attackers squat on
those names, waiting for an agent to `npm install` one. This is a direct risk for
`issue-build`'s unattended builder. **Socket** (or Semgrep Supply Chain, which the pipeline
would already have) is the cited mitigation — a small, concrete addition worth building
into the build gate (`npm audit` already runs; verify it or Socket also flags typosquats,
not just known-CVE packages).

## What the research validates about the existing pipeline design

- **Native GitHub auto-merge over a merge queue: strongly validated.** Multiple
  independent sources converge on the same threshold — merge queues (Mergify/Kodiak/
  GitHub's own) only earn their keep past ~10 engineers, ~20 PRs/day, ~30 min CI, or
  monorepo contention. All well above a solo operator. The actual outgrowth trigger to
  watch for isn't volume — it's needing *conditional/differentiated* gating logic
  (different rules for bot PRs vs. human, docs vs. code) that a single button can't
  express. That's the concrete signal to revisit this decision on, not a PR-count metric.
- **The claim-and-unstick mechanisms already built are directly validated by failure
  data**, not just designed on intuition:
  - 22.1% of unmerged agent PRs fail because another PR already fixed the same issue —
    exactly the race `issue-build`'s `building` label claim exists to prevent.
  - 9.2% of unmerged agent PRs are closed from pure inactivity — exactly the rot
    `pr-unstick.yml`'s daily retry sweep exists to catch before a static `hold` label
    would otherwise let a PR silently die.
- **"Always ship ≥1 PR" carries a real, quantified cost, not just a theoretical one.**
  46.41% of agent-authored fix PRs get rejected in one large empirical dataset (AIDev,
  3,225 PRs); rejected PRs still cost real review/CI cycles (median 81–293 LOC of churn)
  even when discarded. 30.1% of rejections are priority/duplicate-related rather than
  code defects — which argues *for* the priority-tiered (HIGH/MED/LOW) selection already
  in the redesigned `issue-build.yml`, since no-prioritization is measurably worse, but
  doesn't make the waste zero. Worth watching the actual reject rate once the pipeline
  runs for real and comparing against this baseline.
- **Bot review-comment volume is anti-correlated with both merge speed and relevance** —
  more automated comments, not fewer, correlates with slower and lower-quality reviews.
  Keep `security-review`'s output terse and advisory, as designed; don't add a second,
  noisier automated reviewer.

## What the research pushes back on — one open disagreement, not auto-adopted

Nearly every source found (Anthropic's own Claude Code GitHub Actions docs included)
describes a **human-approves-every-merge** pattern as the safe default, not a fully
autonomous ships-and-rolls-back model. Anthropic's own docs explicitly forbid the agent
self-approving or merging, gating on CI-green + human approval. This is a real,
load-bearing divergence from this org's Tier-B design — but not automatically "wrong":
the sourced advice is aimed at teams without this org's specific context (private repos,
one trusted operator nearby, explicit preference for ship-and-roll-back over
block-and-wait, stated repeatedly this session). **Flagging as an informed, deliberate
disagreement with common practice, not adopting it** — the operator has already reasoned
through this trade-off explicitly (cardinal rule #4). Worth knowing the industry consensus
leans the other way, in case the observed reject/rework rate ever argues for tightening.

## The rest of the toolset — as established this session, now consolidated

### Buy
- **Semgrep Team** ($40/mo) — see correction above. Replaces the earlier GHAS-only plan.

### Free, install/configure now
- **Nix** — `sux/flake.nix` already exists (reproducible dev shell, `node_22`) but Nix
  isn't installed locally, so it's dead weight. Install it; don't expand beyond the
  existing minimal flake unless multi-machine drift becomes a real problem.
- **`SEMGREP_APP_TOKEN`** — generate one at semgrep.dev/orgs/-/settings/tokens to finish
  the MCP findings-API login (CLI scanning already works without it).
- **Fix `sux-fileops`'s secret-scanning gap** — the one repo with `secret_scanning` +
  `push_protection` fully disabled while the other three have it on. Free, just a toggle.

### Free, already installed/connected, keep using
`ast-grep` (structural code search — proven on real `sux` code), `gh search code` (default
for "how do others solve this" — proven against a real GH Actions pattern), `grep.app`
(regex-capable complement, `gh search code`'s own docs admit no regex support),
`context7` (confirmed working — returned real Wrangler Action docs), `typescript-lsp`
(connected, fires naturally on TS edits), `gitleaks`, `shellcheck`, `actionlint`,
`yamllint`, `jq`, `ripgrep`, `fd`.

### Cloudflare — specific products, specific jobs, all grounded in what's actually provisioned
- **Vectorize** — for `sux`'s `recall` tool specifically. `_embed.ts` already computes
  embeddings via the existing `AI` binding; `recall.ts` compares them with a hand-written
  `cosine()` function — a brute-force scan with no real vector index. Filed as
  [SuxOS/sux#472](https://github.com/SuxOS/sux/issues/472). Migrate: add a `vectorize`
  binding, upsert on ingest, replace the `cosine()` loop with a Vectorize query.
- **Workers Observability** — already the right post-merge health signal for `sux`
  specifically (verified: 90k+ real events/week, a working `$metadata.error exists`
  filter). Wire into the pipeline (e.g. a step in `pr-unstick.yml` or a new check) to
  query for a regression after an automerge and flag a revert-candidate.
- **Grafana Cloud** — connected, real datasources (Prometheus/Loki/Tempo), but genuinely
  empty for `sux` (it's not the deploy target). Whether `suxrouter`/`sux-fileops` need it
  depends on whether they're Cloudflare Workers too (unconfirmed) — a separately
  dispatched task is already checking this.
- **Grafana OnCall** — already connected and paid for. **Don't buy PagerDuty/incident.io**
  — this is sitting unused and covers the same job.
- **KV (`MEMORY_KV`, new namespace)** — the shared-memory design: a small key/value store
  both this local Claude Code session (via the connected Cloudflare MCP) and the GitHub
  Actions bot (via a `curl` to a thin endpoint on `sux`, which already has an HTTP adapter
  and MCP tool registrations) can read/write. Anthropic's `memory_20250818` tool is the
  right *contract* (client-managed storage, model reads/writes files) — it doesn't host
  storage itself, so this KV namespace is the backend that makes memory actually shared
  across the two environments, following the same deterministic-write/model-read (Safe
  Outputs) shape the pipeline already uses everywhere. Natural next step once Vectorize
  lands: back the same memory layer with semantic search instead of exact-key lookup.
- **D1** — no unmet need found (zero databases provisioned, no relational-shaped logic in
  `sux`). Not recommending speculatively.

### Explicitly not buying, and why
- **Sentry / Datadog** — redundant with Cloudflare Workers Observability + Grafana Cloud,
  both already paid for and already covering this job.
- **Snyk / additional SAST beyond Semgrep** — the research says small teams benefit from
  running two tools, so Snyk's generous free tier is worth layering in alongside Semgrep
  rather than paying for a third platform — free complement, not a purchase.
- **Renovate Pro / Mergify / Kodiak** — the merge-queue-adoption research strongly
  confirms the three-loop design's existing choice (native auto-merge, no queue) was
  correct at this scale; buying a merge-queue product now would contradict a decision the
  evidence just validated.
- **Linear / Jira** — would break one-source-of-truth; GitHub issues are the declared
  truth here and the pipeline is built entirely around that.

## Open, not yet answered

- Whether `suxrouter`/`sux-fileops` need their own observability wiring (Cloudflare or
  Grafana) — pending the already-dispatched instrumentation task's findings.
- Exact shape of the `MEMORY_KV` schema (key namespacing, TTL, what "the bot learned X"
  actually gets written as) — a brainstorm-then-build task of its own, not decided here.
