#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — single envelope dispatcher for the Bash-command rails (#163).

`block-egress.py` and `block-checkout-held-branch.py` are both PreToolUse hooks matched on
`Bash`, and each independently re-implemented the same envelope boilerplate: `json.load(sys.stdin)`
(fail-open on error), the `tool_name != "Bash"` guard, extracting/validating `tool_input.command`,
running the check inside a try/except that exits 0 on any exception, and print+exit-2 on a hit.
Wiring both as separate `hooks.PreToolUse` entries also meant every Bash tool call spawned two
Python processes that each parsed the identical stdin envelope.

This dispatcher reads the envelope ONCE and runs a registered list of pure
`check(command, cwd) -> message | None` predicates — one per rail, defined in each rail's own
module so `block-egress.py`/`block-checkout-held-branch.py` stay independently readable and
independently testable via stdin (see hooks/README.md's "Testing a hook before you trust it").
The first predicate to return a message wins; settings.json wires only this one script under
`hooks.PreToolUse` for the `Bash` matcher instead of N.

Adding a rail: give its module a `check(command, cwd) -> message | None` function (see the
existing ones for the shape) and append its module name to _RAIL_MODULES below.

Fail-open on any error — a hook bug (this dispatcher's or any one rail's) must never wedge the
session (repo convention). Exit 2 = block; exit 0 = allow. That includes a rail module that
fails to even IMPORT (a syntax error, a broken sibling import): `_load_checks()` loads each rail
module independently and drops any that raise, rather than letting one broken module crash the
whole dispatcher before `main()` is ever reached (#180) — a broken rail degrades to "not
enforced", never to "no Bash command runs".
"""
import importlib.util
import json
import os
import sys

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

# Registered rail modules, in the order they're checked. Each must define
# `check(command, cwd) -> message | None`; the first to return a message wins.
_RAIL_MODULES = (
    "block-egress",
    "block-checkout-held-branch",
    "block-sleep-loop",
    "block-suppressed-stderr",
)


def _load(module_name):
    """Load a sibling hook module by filename (hyphenated, so not a normal `import`)."""
    path = os.path.join(_HOOKS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_checks():
    """Load every rail module's `check`, skipping (not crashing on) one that fails to load."""
    checks = []
    for module_name in _RAIL_MODULES:
        try:
            checks.append(_load(module_name).check)
        except Exception:
            continue  # a broken sibling module degrades to "not enforced", never a crash (#180)
    return tuple(checks)


CHECKS = _load_checks()


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = (data.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        sys.exit(0)

    cwd = data.get("cwd") or None

    for check in CHECKS:
        try:
            message = check(command, cwd)
        except Exception:
            continue  # never let one rail's bug block a call or wedge the session
        if message:
            print(message, file=sys.stderr)
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
