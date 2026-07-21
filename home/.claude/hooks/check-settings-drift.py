#!/usr/bin/env python3
"""SessionStart hook — warn (never block) when live ~/.claude/settings.json has drifted from
the claude-config repo source on the security/behavior-critical fields.

WHY THIS EXISTS (2026-07-21): live settings.json is COPIED, not symlinked (Claude Code rewrites
it in place — install.sh:67), so it silently diverges from the repo source. A dual-account
logout/login rewrote the live file to a bare baseline and LOST the entire `permissions.deny` list
and all PreToolUse/PostToolUse hooks; the hook FILES stayed symlinked on disk but were unwired in
the live settings, so every safety rail went inert for a whole session before anyone noticed. That
is the exact failure this catches at the top of the next session instead of hours later.

install.sh --apply already merges missing deny rules + hook commands INTO live, but (a) it only
runs when a human runs it, and (b) it does not cover `disableClaudeAiConnectors` / plugin drift.
This hook is the always-on detector: it runs every SessionStart, compares live vs repo source on
the fields whose loss is dangerous, and emits an additionalContext banner so the operator (or
Claude) reconciles immediately — typically by running `claude-config/install.sh --apply` or
copying the repo source over live.

CRITICAL fields (loss = a real safety regression, like the incident above):
  - permissions.deny            (the Tier-A block list)
  - hooks                       (the PreToolUse/PostToolUse safety rails)
  - permissions.defaultMode     (bypassPermissions relies on deny doing all the enforcing)
  - disableClaudeAiConnectors   (a flip to false re-double-loads claude.ai connectors in Code)
CONFIG fields (drift is usually intentional — reported as a softer note):
  - enabledPlugins

The repo source is located via THIS FILE's own path: it is symlinked from
claude-config/home/.claude/hooks/check-settings-drift.py into ~/.claude/hooks/, so
realpath(__file__)/../settings.json is the repo source with zero hard-coded clone path or
fabric.json lookup. If that resolution fails (hook copied instead of symlinked, sparse checkout),
the hook fails OPEN — a config-drift detector must never wedge session start (repo convention:
every rail fails open on any error).

Output: the Claude Code SessionStart additionalContext JSON contract. Silent (exit 0, no output)
when there is no critical/config drift.
"""
import json
import os
import sys


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _emit(context):
    """Emit a SessionStart additionalContext banner and exit 0 (advisory, never blocking)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    sys.exit(0)


def main():
    # Read (and ignore) the SessionStart envelope so stdin never blocks the pipe.
    try:
        sys.stdin.read()
    except Exception:
        pass

    live_path = os.path.expanduser("~/.claude/settings.json")
    # realpath resolves the ~/.claude/hooks symlink back to the repo source tree.
    repo_path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "settings.json")
    )

    # Fail open on anything unreadable — never wedge session start.
    if os.path.realpath(live_path) == os.path.realpath(repo_path):
        return  # settings.json is symlinked to the source (nothing to drift)
    try:
        live = _load(live_path)
        repo = _load(repo_path)
    except Exception:
        return

    critical = []  # (field, human description of the drift)
    config = []

    # --- deny: compare as sets (order-insensitive); report what LIVE is missing/extra ---
    live_deny = set(live.get("permissions", {}).get("deny", []))
    repo_deny = set(repo.get("permissions", {}).get("deny", []))
    missing = repo_deny - live_deny
    extra = live_deny - repo_deny
    if missing:
        critical.append(f"permissions.deny is MISSING {len(missing)} rule(s) present in the repo "
                        f"source (e.g. {', '.join(sorted(missing)[:3])}) — the Tier-A block list "
                        f"has been weakened in the live file")
    if extra:
        config.append(f"permissions.deny has {len(extra)} live-only rule(s) not in the repo "
                      f"source (e.g. {', '.join(sorted(extra)[:3])}) — persist them to the repo")

    # --- hooks: compare the full structure; loss of a rail is the incident above ---
    if live.get("hooks") != repo.get("hooks"):
        live_cmds = _hook_commands(live.get("hooks", {}))
        repo_cmds = _hook_commands(repo.get("hooks", {}))
        missing_hooks = repo_cmds - live_cmds
        if missing_hooks:
            critical.append(f"hooks are MISSING {len(missing_hooks)} rail(s) wired in the repo "
                            f"source (e.g. {', '.join(sorted(missing_hooks)[:3])}) — a safety hook "
                            f"has fallen out of the live settings")
        elif live_cmds != repo_cmds:
            config.append("hooks differ from the repo source (wiring changed) — reconcile")

    # --- defaultMode + disableClaudeAiConnectors: single-value critical flips ---
    if live.get("permissions", {}).get("defaultMode") != repo.get("permissions", {}).get("defaultMode"):
        critical.append(
            f"permissions.defaultMode is '{live.get('permissions', {}).get('defaultMode')}' live vs "
            f"'{repo.get('permissions', {}).get('defaultMode')}' in the repo source")
    if bool(live.get("disableClaudeAiConnectors")) != bool(repo.get("disableClaudeAiConnectors")):
        critical.append(
            f"disableClaudeAiConnectors is {live.get('disableClaudeAiConnectors')} live vs "
            f"{repo.get('disableClaudeAiConnectors')} in the repo source — connectors may be "
            f"double-loading in Code")

    # --- enabledPlugins: usually intentional, reported softly. Normalize false ≡ absent (Claude
    # Code drops disabled plugins on rewrite), so only a genuine on↔off flip is drift, not the
    # serialization difference between an explicit `false` and a missing key. ---
    lp, rp = live.get("enabledPlugins", {}), repo.get("enabledPlugins", {})
    diffs = sorted(k for k in set(lp) | set(rp) if bool(lp.get(k)) != bool(rp.get(k)))
    if diffs:
        config.append(f"enabledPlugins differ on {len(diffs)} plugin(s) "
                      f"(e.g. {', '.join(diffs[:4])}) — persist intentional changes to the repo")

    if not critical and not config:
        return

    lines = ["⚠️  settings.json drift: live ~/.claude/settings.json differs from the "
             "claude-config repo source."]
    if critical:
        lines.append("\n🔴 SECURITY-CRITICAL (a safety rail may be weakened — reconcile now):")
        lines += [f"  • {c}" for c in critical]
    if config:
        lines.append("\n🟡 config drift (persist intentional changes; noise otherwise):")
        lines += [f"  • {c}" for c in config]
    lines.append("\nReconcile: run `claude-config/install.sh --apply` (merges deny+hooks into "
                 "live), or update the repo source home/.claude/settings.json to match live and "
                 "open a PR. See suxos-claude-code-config-reorg-2026-07-21.")
    _emit("\n".join(lines))


def _hook_commands(hooks_obj):
    """Flatten a hooks config to the set of 'event:command' strings for structural comparison."""
    out = set()
    if not isinstance(hooks_obj, dict):
        return out
    for event, entries in hooks_obj.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for h in (entry or {}).get("hooks", []):
                cmd = (h or {}).get("command")
                if cmd:
                    out.add(f"{event}:{cmd}")
    return out


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A drift detector must never wedge session start.
        sys.exit(0)
