#!/usr/bin/env python3
"""Lint home/.claude/settings.json permission rules for the fail-OPEN-silently traps.

settings.README.md documents a class of permission-rule bugs that fail open with NO warning from
Claude Code, so a typo reads as a control while enforcing nothing. This turns that prose checklist
into an enforced CI gate (issue #82). It flags three shapes as hard failures:

  1. MCP-DENY-NOT-NAMESPACED — a concrete `mcp__…` deny that is not `mcp__plugin_<plugin>_<server>
     __<tool>`. Plugin-bundled MCP tools (everything in enabledPlugins here) are addressed with the
     `plugin_…` prefix; a bare `mcp__<server>__<tool>` deny never matches and Claude Code emits no
     startup warning (the typo check exempts any identifier with `_`/`*`). Glob denies (`mcp__*…`)
     are allowed by the docs and skipped. (settings.README.md:51-60)

  2. BASH-DENY-CONSTRAINS-ARGS — a `Bash(…)` deny whose glob embeds an interior flag/character to
     constrain arguments (`Bash(tar *x*)`): a wildcard glued to argument text mid-command. These
     read as scoped but match by accident and are trivially evaded. (settings.README.md:28-49)

  3. ALLOW-DENY-OVERLAP — the exact same pattern in both `allow` and `deny` (e.g. `Bash(gh api *)`
     was on both). Deny always wins, so the allow entry is a contradiction that misreads as intent.

Exit 0 = clean; exit 1 = one or more violations (each printed with file + rule + why + fix).
Invalid JSON is itself a failure. Path: argv[1], else home/.claude/settings.json next to the repo.
"""
import json
import re
import sys
from pathlib import Path

DEFAULT_SETTINGS = Path(__file__).resolve().parents[2] / "home" / ".claude" / "settings.json"

# A Bash deny "constrains arguments" if, after stripping ONE leading wrapper `*` (the legitimate
# `Bash(*wrangler …)` indirection form), any whitespace-separated token glues a `*` to argument
# text: a flag fenced by wildcards (`*x*`) or a wildcard embedded inside a token (`git*log`).
FLAG_FENCED = re.compile(r"\*[^\s*]+\*")   # *x*  — wildcard-flag-wildcard
STAR_EMBEDDED = re.compile(r"[^\s*]\*[^\s*]")  # a*b — wildcard inside an argument token


def bash_inner(pattern):
    """Return the command glob inside a `Bash(...)` rule, or None if it isn't one."""
    m = re.fullmatch(r"Bash\((.*)\)", pattern)
    return m.group(1) if m else None


def bash_constrains_args(pattern):
    """True if a Bash deny glob embeds an interior wildcard-fenced flag / argument constraint."""
    inner = bash_inner(pattern)
    if inner is None:
        return False
    inner = inner.strip()
    if inner.startswith("*"):  # drop the leading wrapper wildcard (`*wrangler deploy` is fine)
        inner = inner[1:]
    for tok in inner.split():
        if tok == "*":
            continue
        if FLAG_FENCED.search(tok) or STAR_EMBEDDED.search(tok):
            return True
    return False


def mcp_deny_bad_namespace(pattern):
    """True if a concrete (non-glob) MCP deny is not plugin-namespaced and so silently fails open."""
    if not pattern.startswith("mcp__") or "*" in pattern:
        return False  # not MCP, or a glob deny (allowed for deny per settings.README.md:60)
    parts = pattern.split("__")
    # want mcp__plugin_<plugin>_<server>__<tool>: >=3 non-empty parts, server segment `plugin_…`.
    return len(parts) < 3 or not all(parts) or not parts[1].startswith("plugin_")


def lint(settings_path):
    problems = []
    path = Path(settings_path)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return [f"{settings_path}: file not found"]
    except json.JSONDecodeError as e:
        return [f"{settings_path}: invalid JSON — {e}"]

    perms = data.get("permissions") or {}
    allow = perms.get("allow") or []
    deny = perms.get("deny") or []
    where = str(path)

    for rule in deny:
        if not isinstance(rule, str):
            continue
        if mcp_deny_bad_namespace(rule):
            problems.append(
                f"{where}: MCP-DENY-NOT-NAMESPACED  deny '{rule}' is not "
                f"'mcp__plugin_<plugin>_<server>__<tool>' — it never matches and fails OPEN with no "
                f"startup warning. Fix: use the plugin-namespaced identifier (settings.README.md:62-76)."
            )
        if bash_constrains_args(rule):
            problems.append(
                f"{where}: BASH-DENY-CONSTRAINS-ARGS  deny '{rule}' embeds an interior wildcard to "
                f"constrain arguments — it matches by accident and is trivially evaded. Fix: deny the "
                f"tool/subcommand outright, not by argument pattern (settings.README.md:28-49)."
            )

    overlap = [r for r in allow if isinstance(r, str) and r in set(deny)]
    for rule in overlap:
        problems.append(
            f"{where}: ALLOW-DENY-OVERLAP  '{rule}' is in both allow and deny — deny always wins, so "
            f"the allow entry is inert and contradictory. Fix: remove it from one list."
        )

    return problems


def main():
    settings_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SETTINGS
    problems = lint(settings_path)
    if problems:
        print(f"settings.json lint: {len(problems)} problem(s) found\n", file=sys.stderr)
        for p in problems:
            print("  ✗ " + p, file=sys.stderr)
        sys.exit(1)
    print(f"settings.json lint: OK ({settings_path})")
    sys.exit(0)


if __name__ == "__main__":
    main()
