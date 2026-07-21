#!/usr/bin/env python3
"""Advisory check: catch hooks/README.md drift from settings.json / hook source (issue #269).

hooks/README.md has needed a standalone "fix the stale doc" issue at least six separate times
(#103, #124, #169, #216, #223, #249, ...) — every time a hook gains a predicate, changes its
matcher, or a documented premise gets disproven by testing, the prose silently falls behind
until someone happens to notice. This mechanically checks the two drift shapes that have
actually recurred, without a full prose parser:

  1. MATCHER-DRIFT — for every hook directly wired in settings.json's `hooks.PreToolUse` /
     `hooks.PostToolUse` (i.e. NOT one of the rails pretooluse-bash.py loads via `_RAIL_MODULES`,
     which have no matcher of their own), the matcher settings.json wires must equal the matcher
     hooks/README.md's "**`hook.py`**" bullet states in its "(matcher `...`)" aside.

  2. PREDICATE-COUNT-DRIFT — block-destructive-git.py's `offending()` dispatches a fixed set of
     `_..._hit()` predicates; hooks/README.md's bullet for it states that count in prose ("Eight
     narrowly-scoped predicates"). If the code adds/removes a dispatched predicate without the
     prose being updated, this flags the mismatch.

This is deliberately ADVISORY (a standalone CI job, not folded into the required `shellcheck`
job — see ci.yml): unlike lint-settings.py's regex-over-JSON checks, rule 2 parses hand-written
prose (a number word), which is inherently more fragile than parsing structured config. It also
can't judge free-form claims (e.g. "deliberately NOT extended to X") — only the two mechanical
facts above, which is what has actually drifted every time so far. Exit 0 = clean or nothing to
check; exit 1 = a drift found.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / "home" / ".claude" / "settings.json"
README_PATH = REPO_ROOT / "home" / ".claude" / "hooks" / "README.md"
BLOCK_DESTRUCTIVE_GIT_PATH = REPO_ROOT / "home" / ".claude" / "hooks" / "block-destructive-git.py"

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

README_MATCHER_RE = re.compile(r"\*\*`([a-zA-Z0-9_-]+\.py)`\*\*.*?\(matcher `([^`]+)`\)")
README_PREDICATE_COUNT_RE = re.compile(r"\b([A-Za-z]+)\s+narrowly-scoped\s+predicates")
HIT_CALL_RE = re.compile(r"(_[a-zA-Z0-9_]+_hit)\(")


def settings_hook_matchers(settings_path):
    """Return {hook_basename: matcher} for every hook directly wired in settings.json."""
    data = json.loads(settings_path.read_text())
    out = {}
    for event_entries in (data.get("hooks") or {}).values():
        for entry in event_entries:
            matcher = entry.get("matcher")
            for h in entry.get("hooks") or []:
                name = Path(h.get("command") or "").name
                if name:
                    out[name] = matcher
    return out


def readme_hook_matchers(readme_text):
    """Return {hook_basename: matcher} for every "**`hook.py`** ... (matcher `...`)" bullet."""
    return dict(README_MATCHER_RE.findall(readme_text))


def check_matcher_drift(settings_path, readme_path):
    problems = []
    wired = settings_hook_matchers(settings_path)
    documented = readme_hook_matchers(readme_path.read_text())
    for name, matcher in sorted(wired.items()):
        doc_matcher = documented.get(name)
        if doc_matcher is None:
            problems.append(
                f"{readme_path}: '{name}' is wired in {settings_path.name} (matcher '{matcher}') "
                f"but has no '(matcher `...`)' bullet in hooks/README.md to check it against."
            )
        elif doc_matcher != matcher:
            problems.append(
                f"{readme_path}: '{name}' matcher drift — settings.json wires '{matcher}', "
                f"README.md documents '{doc_matcher}'."
            )
    return problems


def _function_body(source, name):
    """Return the body text of `def {name}(...):` up to (not including) the next top-level def."""
    marker = f"\ndef {name}("
    start = source.find(marker)
    if start == -1:
        return None
    sig_end = source.index(":", start)
    next_def = source.find("\ndef ", sig_end)
    return source[sig_end:] if next_def == -1 else source[sig_end:next_def]


def check_destructive_git_predicate_count(hook_path, readme_path):
    body = _function_body(hook_path.read_text(), "offending")
    if body is None:
        return [f"{hook_path}: couldn't find offending() to count dispatched predicates"]
    actual = sorted(set(HIT_CALL_RE.findall(body)))

    readme_text = readme_path.read_text()
    section_m = re.search(
        r"\*\*`block-destructive-git\.py`\*\*.*?(?=\n- \*\*`|\Z)", readme_text, re.DOTALL
    )
    if not section_m:
        return [f"{readme_path}: no block-destructive-git.py bullet found to check predicate count"]
    count_m = README_PREDICATE_COUNT_RE.search(section_m.group(0))
    if not count_m:
        return []  # prose doesn't state a count in the expected shape; nothing to check
    documented = NUMBER_WORDS.get(count_m.group(1).lower())
    if documented is None or documented == len(actual):
        return []
    return [
        f"{readme_path}: block-destructive-git.py predicate count drift — README says "
        f"'{count_m.group(1)} narrowly-scoped predicates' but offending() dispatches "
        f"{len(actual)} ({', '.join(actual)})."
    ]


def main():
    problems = check_matcher_drift(SETTINGS_PATH, README_PATH)
    problems += check_destructive_git_predicate_count(BLOCK_DESTRUCTIVE_GIT_PATH, README_PATH)
    if problems:
        print(f"hooks/README.md drift check: {len(problems)} problem(s) found\n", file=sys.stderr)
        for p in problems:
            print("  ✗ " + p, file=sys.stderr)
        sys.exit(1)
    print("hooks/README.md drift check: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
