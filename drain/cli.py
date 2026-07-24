"""Command-line interface: ``python3 -m drain {audit|plan|run|report}``.

audit  = read-only inventory + classification.
plan   = dry-run prioritized action plan (no mutations).
run    = execute auto actions (gated emitted, idempotent, evidence-verified).
report = render the persisted audit log's history.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import report as _report
from .audit_log import AuditLog
from .config import build_adapters, load_config, load_fabric
from .engine import Engine

DEFAULT_LOG = os.path.expanduser("~/.local/state/drain/audit.jsonl")


def _build_engine(args: argparse.Namespace, mode: str) -> Engine:
    fabric = load_fabric(args.fabric)
    config = load_config(args.config)
    only: Optional[List[str]] = args.source or None
    adapters = build_adapters(config, fabric, only=only)
    log = AuditLog(args.log)
    return Engine(
        adapters=adapters,
        audit_log=log,
        mode=mode,
        max_rounds=config.get("max_rounds", 3),
        limit=args.limit if args.limit is not None else config.get("limit"),
        retries=config.get("retries", 2),
        backoff_base=config.get("backoff_base", 0.2),
        breaker_threshold=config.get("breaker_threshold", 3),
        concurrency=config.get("concurrency", 4),
    )


def _emit(args: argparse.Namespace, result) -> int:
    if args.json:
        print(json.dumps(_report.to_dict(result), indent=2, sort_keys=True))
    else:
        print(_report.to_markdown(result))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    return _emit(args, _build_engine(args, "audit").run())


def _cmd_plan(args: argparse.Namespace) -> int:
    return _emit(args, _build_engine(args, "plan").run())


def _cmd_run(args: argparse.Namespace) -> int:
    return _emit(args, _build_engine(args, "run").run())


def _cmd_apply_verdicts(args: argparse.Namespace) -> int:
    from .exercise import VerdictAdapter

    default = os.path.join(os.path.dirname(__file__), "fixtures", "eval-verdicts-69.json")
    with open(os.path.expanduser(args.verdicts or default), encoding="utf-8") as fh:
        verdicts = json.load(fh)
    config = load_config(args.config)
    adapter = VerdictAdapter(verdicts, limit=config.get("github_limit", 200))
    engine = Engine(
        adapters=[adapter],
        audit_log=AuditLog(args.log),
        mode=args.mode,
        max_rounds=config.get("max_rounds", 3),
        limit=args.limit if args.limit is not None else config.get("limit"),
        retries=config.get("retries", 2),
        backoff_base=config.get("backoff_base", 0.2),
        breaker_threshold=config.get("breaker_threshold", 3),
        concurrency=config.get("concurrency", 4),
    )
    return _emit(args, engine.run())


def _cmd_report(args: argparse.Namespace) -> int:
    log = AuditLog(args.log)
    entries = log.entries()
    actions = [e for e in entries if e.get("event") == "action"]
    gates = [e for e in entries if e.get("event") == "gate"]
    plans = [e for e in entries if e.get("event") == "plan"]
    summary = {
        "log": args.log,
        "total_entries": len(entries),
        "actions": len(actions),
        "actions_ok": len([a for a in actions if a.get("result") == "ok"]),
        "plans": len(plans),
        "gates": len(gates),
    }
    if args.json:
        print(json.dumps({"summary": summary, "gates": gates}, indent=2, sort_keys=True))
    else:
        print("# drain audit-log report")
        for k, v in summary.items():
            print(f"- {k}: {v}")
        if gates:
            print("\n## Gates")
            for g in gates:
                print(f"- {g.get('gate')} ({g.get('source')})")
    return 0


def _add_global_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help="path to drain.config.json")
    parser.add_argument("--fabric", default=None, help="path to fabric.json (default ~/.claude/fabric.json)")
    parser.add_argument("--source", action="append", help="limit to adapter(s): local|github|mock (repeatable)")
    parser.add_argument("--limit", type=int, default=None, help="cap items acted on")
    parser.add_argument("--log", default=DEFAULT_LOG, help="audit-log path")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")


def build_parser() -> argparse.ArgumentParser:
    # Globals live on a shared parent so they are accepted both before AND after the
    # subcommand (argparse otherwise only honors main-parser options before the subcommand).
    common = argparse.ArgumentParser(add_help=False)
    _add_global_args(common)

    p = argparse.ArgumentParser(
        prog="drain", description="continuous audit-and-drain orchestrator", parents=[common]
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("audit", _cmd_audit), ("plan", _cmd_plan), ("run", _cmd_run), ("report", _cmd_report)):
        sp = sub.add_parser(name, help=f"{name} mode", parents=[common])
        sp.set_defaults(func=fn)
    av = sub.add_parser(
        "apply-verdicts", help="feed an external classification (eval verdicts) into the drain", parents=[common]
    )
    av.add_argument("--verdicts", default=None, help="path to verdicts JSON (default: bundled 69-issue eval)")
    av.add_argument("--mode", default="plan", choices=("audit", "plan", "run"), help="drain mode (default plan)")
    av.set_defaults(func=_cmd_apply_verdicts)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
