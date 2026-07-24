# `drain` — continuous audit-and-drain orchestrator (design)

_2026-07-24 · claude-config · Python 3.9 stdlib · self-approved under the "no human in
the loop" mandate. This is the reference implementation of the SuxOS fabric's
audit-and-drain engine — the deterministic core that the `orient` / `work` / `dispatch`
prose skills currently hand-roll per run._

## 1. Problem & end-state

Build a continuously-runnable, testable, local-first CLI that inventories all in-flight
work across authorized sources (local git clones, GitHub issues/PRs/CI, plus mock
adapters for anything unavailable), normalizes it into one record shape, classifies each
item's state, prioritizes a drain plan, performs **safe, reversible, idempotent** actions
automatically, gates everything destructive/privileged/irreversible, verifies claimed
completions against evidence, and re-audits until the queue is drained or every remaining
item carries a precise blocker or gate. It ships with automated tests, an append-only
audit trail, three run modes, and operator docs.

**End-state:** `python3 -m drain audit|plan|run|report` runs green against local + mock +
(where authorized) real GitHub sources, with a full test suite, redacted structured logs,
and a reproducible final report.

## 2. Why here, this stack (reconciliation with existing work)

- **Not a greenfield reinvention** (Cardinal #2). The fabric already has an audit-and-drain
  system: the `orient` skill (audit/"see"), `work`/`dispatch` (act/"drain"), and the
  `SuxOS/.github` three-loop pipeline (the cloud execution engine). `drain` does **not**
  replace them — it is the *deterministic, tested, portable* engine underneath the prose
  skills: it wraps the same real sources (`git`, `gh`, the fabric config, the pipeline)
  rather than inventing new ones, and can observe/feed the pipeline.
- **`sx` is the intended future home but is an empty Rust scaffold today** (Cargo.toml +
  README + flake, no source). Betting a runnable-this-session deliverable on unbuilt canon
  fails the spec. `drain` lands in `claude-config` (Python-native: every hook is Python;
  `ruff.toml`; CI; co-located with the orient/work/dispatch skills) and documents a
  graduation path into the Rust `sx fabric` engine once canon lands.
- **Python 3.9 stdlib only.** No build step, runs immediately, unit-testable with
  `unittest`, matches the workspace's script precedent (hooks, `vault-lint.py`). Lives at
  top-level `claude-config/drain/` — deliberately **outside** `home/.claude/`, which
  `install.sh` symlinks into live config; a tool must not auto-symlink into `~/.claude`.

## 3. Architecture (small, adapter-based, deterministic core)

```
discover ──▶ normalize ──▶ classify ──▶ prioritize ──▶ plan ──▶ act ──▶ verify ──▶ re-audit
  (adapters)   (record.py)  (classify)   (prioritize)  (policy)  (engine + audit_log)   ↑__loop__|
```

- **`config.py`** — loads `~/.claude/fabric.json` (workspace root, orgs, repos, pipeline)
  and an optional `drain.toml` policy (intervals, thresholds, retries, enabled adapters,
  mode). Everything discoverable and documented; safe defaults.
- **`record.py`** — the normalized `WorkItem`: `source, id, title, owner, status,
  priority, age_days, dependencies, evidence, next_action, last_audit, classification,
  key`. `key` is a content-stable dedup key (`sha1(source:native_id)`), not a timestamp.
- **`adapters/`** — `Adapter` ABC with `discover() -> List[dict]` (raw source records) and
  `act(item, action) -> ActionResult`. Real: `local_git` (branches, uncommitted,
  orphaned worktrees, ahead/behind, TODO/FIXME), `github` (issues/PRs/CI via `gh`). Mock:
  `mock` (JSON fixtures). Unavailable adapter → fail-safe skip, never a hard crash.
- **`classify.py`** — **deterministic rules** over normalized fields → one of
  `actionable | blocked | waiting | needs-review | completed | requires-gate | unknown`.
  No LLM in the default path. An optional `llm_enricher` hook is off by default (and never
  used in tests) — Cardinal #2: deterministic beats LLM; the 69-issue Opus eval was a
  one-off, its verdicts are captured as golden fixtures, not an inline dependency.
- **`prioritize.py`** — deterministic score from age, priority label, blocker-fan-in,
  failed-check, and duplicate signals → stable ordered plan (ties broken by `key` for
  reproducibility).
- **`policy.py`** — the safety spine. Classifies each candidate action as **auto**
  (inspect, run read-only checks, prepare a patch file, add/refresh an idempotent issue
  comment or label, link related, retry an idempotent check) or **gated** (delete,
  force-push, merge, permission/secret/financial/legal/production/secret-rotation). Gated
  actions are never executed — they are emitted as `requires-gate` with a
  `[GATE: <what> — assumed <X>, revisit]` line.
- **`engine.py`** — the loop + non-functionals: three modes (`read-only` audit, `dry-run`
  plan, `execute` run), per-action idempotency (audit-log key check + issue-comment
  sentinel), retries with injectable backoff + timeout, per-source circuit breaker (halt a
  source after N consecutive failures), bounded concurrency, and completion detection
  (loop until no `actionable` items remain or a max-round cap).
- **`audit_log.py`** — append-only JSONL of every decision/action/result with timestamps
  (injectable clock), plus secret redaction applied to all log payloads.
- **`report.py`** — final drain report (markdown + json): discovered, completed, actions
  taken, verification evidence, remaining items + exact blockers, unavailable
  integrations, gates & assumptions.

## 4. Modes & safety invariants

| mode | discovers | classifies | plans | **mutates?** |
|---|---|---|---|---|
| `audit` (read-only) | ✅ | ✅ | — | never |
| `plan` (dry-run) | ✅ | ✅ | ✅ | **never** (asserted by tests) |
| `run` (execute) | ✅ | ✅ | ✅ | only **auto** actions; gated → emitted, never run |

Invariants (each a test): dry-run performs zero writes; the same item observed twice
produces at most one action (idempotency); a gated action is never executed; an adapter
raising on discover/act degrades to a skipped source with a logged reason, never aborts
the run; completion is only declared when re-audit finds no actionable items; no claimed
completion is emitted without an `evidence` field.

## 5. Real-source exercise (Stage 5)

Beyond mock fixtures, `drain` is exercised against the **real** GitHub adapter to apply the
clear-cut subset of the 69-issue eval: the 4 `ALREADY_DONE` + 4 `STALE_SUPERSEDED` items
are closed **with their evidence comment** (safe, reversible), and the `DECIDE_AND_BUILD`
items have `needs-human` removed so the pipeline can select them — every mutation recorded
in the audit log as proof. `DEFER`/`HARD_BLOCKED` are emitted as gated/blocked with
reasons. This satisfies both the spec's "exercise against real sources" and the standing
org-drain mandate.

## 6. Testing

`unittest`, stdlib, fixtures-driven (no network): normalization, classification,
prioritization, gate handling, idempotency, retries/backoff, dry-run no-mutation,
completion detection, circuit breaker, adapter-unavailable fail-safe. Golden data: the 69
real eval verdicts. Wired into `ci.yml` as a step inside the existing ruleset-required
job (the established pattern for gating config-integrity checks without a ruleset change).

## 7. Non-goals

Not a hosted service; not a replacement for the `.github` pipeline or the orient/work/
dispatch skills; no new remote integrations beyond local-git + GitHub (others are mock
adapters + documented extension points); no LLM in the default classification path.

## 8. Gates & assumptions

- **[ASSUMPTION]** Home = `claude-config/drain/` (Python), not `sx` (unbuilt Rust). sx
  graduation is a documented extension point.
- **[ASSUMPTION]** CI wiring is a step in the existing required job, not a new required
  check (a new required check needs an org ruleset change, which is Colin-gated).
- Live GitHub mutations run only in `execute` mode against explicitly-listed items; `gh
  pr merge` / deletes stay gated regardless of mode.
