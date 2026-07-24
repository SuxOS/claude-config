# `drain` — continuous audit-and-drain orchestrator

Local-first, stdlib-only (Python 3.9+) CLI that inventories in-flight work across
configured sources, classifies each item deterministically, prioritizes a drain plan,
performs **safe, reversible, idempotent** actions automatically, **gates** everything
destructive, verifies claimed completions against evidence, and re-audits until the queue
is drained or every remaining item carries a precise blocker.

It is the deterministic engine underneath the `orient` / `work` / `dispatch` prose skills —
it wraps the same real sources (`git`, `gh`, the fabric config) rather than inventing new
ones, and complements (does not replace) the `SuxOS/.github` cloud pipeline.

## Install / run

No install, no build. From the repo root:

```bash
python3 -m drain audit      # read-only inventory + classification
python3 -m drain plan       # dry-run prioritized action plan (no mutations)
python3 -m drain run        # execute auto actions (gated emitted, idempotent)
python3 -m drain report     # render the persisted audit log's history
```

Common flags: `--source local|github|mock` (repeatable), `--limit N`, `--config
drain.config.json`, `--fabric ~/.claude/fabric.json`, `--log PATH`, `--json`.

## Modes (safety)

| mode | discovers | classifies | plans | mutates? |
|---|---|---|---|---|
| `audit` | ✅ | ✅ | — | **never** |
| `plan` | ✅ | ✅ | ✅ | **never** (dry-run) |
| `run` | ✅ | ✅ | ✅ | only **auto** actions; gated → emitted, never run |

Default is read-only-friendly: `audit` and `plan` never touch a source. `run` performs
only safe, reversible, idempotent actions.

## States

Every item is classified into exactly one: `actionable`, `blocked`, `waiting`,
`needs-review`, `completed`, `requires-gate`, `unknown`. Classification is a fixed,
ordered set of deterministic rules over normalized fields — no model call (see
`classify.py`).

## Actions: auto vs gated

**Auto** (run in `run` mode): inspect, run/retry an idempotent check, prepare a patch
file, add/refresh an idempotent comment, add/remove a label, link related items, close an
issue **with evidence** (reversible: reopen), noop.

**Gated** (never executed — emitted as `[GATE: <what> — assumed <X>, revisit]`): delete,
force-push, merge, secret rotation, deploy, payment, legal signature, permission change.
The gate set is closed and conservative — anything not provably safe is gated.

## Adapters

- **`local`** (real) — scans local clones under `workspace_root`: uncommitted trees,
  branches ahead of upstream, orphaned worktrees. Read-only; never rewrites history.
- **`github`** (real) — issues/PRs via `gh`. Discovery is read-only; comment / remove-label
  / close-with-evidence run only in `run` mode, made idempotent by a sentinel HTML comment
  (`<!-- drain:KEY -->`) checked before acting.
- **`mock`** (fixtures) — deterministic in-memory tracker from a JSON fixture. Stands in
  for any unavailable integration and drives the test suite with no network.

An unavailable adapter degrades to a *skipped source* with a logged reason — it never
aborts the run. Add a new source by subclassing `adapters.base.Adapter`; nothing else
changes.

## Configuration

Optional `drain.config.json` (stdlib JSON — `tomllib` is 3.11+, unavailable on the 3.9
target). See `drain.config.example.json`. Fabric truth is `~/.claude/fabric.json`
(workspace root, orgs, repos). Every key has a safe default; `drain` runs with zero config.

## Reliability

Retries with exponential backoff (injectable sleep), per-source circuit breaker (halts a
source after N consecutive failures), bounded concurrency for discovery, append-only JSONL
audit trail with secret redaction, and idempotency via the audit log + adapter sentinels.

## Scheduling

`drain` is a single-shot command; schedule it however the environment prefers (cron, a
`schedule` skill, a CI cron). Each run is idempotent, so re-runs are safe. Example:

```bash
*/30 * * * *  cd /path/to/repo && python3 -m drain run --log ~/.local/state/drain/audit.jsonl
```

## What requires human approval

Only genuinely-impossible-for-an-agent atoms: minting a secret value, cloud/console
bootstrap tied to an identity, payment, legal signature, physical hardware action, manual
portal export. These surface as `[GATE: ...]` lines in the report — never performed
implicitly.

## SuxOS-specific: applying eval verdicts

`exercise.py` maps the 69-issue Opus classification verdicts into drain records
(`ALREADY_DONE`/`STALE`/`DEFER` → close-with-evidence; `DECIDE_AND_BUILD` → clear
`needs-human`; `HARD_BLOCKED` → gate). This demonstrates feeding an external
classification source into the same deterministic action/gate machinery.

## Extension: graduation to `sx`

`drain` is the runnable reference implementation. The intended long-term home is the typed
Rust `sx fabric` engine (`SuxOS/sx`) once its canon lands — the state machine, adapter
interface, and policy set here are the executable spec for that port.

## Troubleshooting

- **"adapter unavailable" for github** — `gh auth status` must be green.
- **Nothing discovered from local** — `~/.claude/fabric.json` must have `workspace_root`
  pointing at your clones (or pass `--fabric`).
- **A gated item you expected to be actioned** — that is by design; perform it yourself and
  re-run (the tool will see it resolved).

Tests: `python3 -m unittest discover -s drain/tests -t .`
