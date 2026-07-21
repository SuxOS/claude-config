#!/usr/bin/env python3
"""Check `<!-- doc-fact: ... -->` annotations in tracked docs against live repo state (#278).

This repo has filed and fixed an unusually large number of narrow "doc claims X but code/config
says Y" drift issues (#38, #59, #64, #103, #169, #173, #175, #176, #216, #221, #222, #223, #224,
#226, #268, ...). #269 added a CI check scoped specifically to hooks/README.md vs settings.json /
hook source (see lint-hooks-doc.py) — this generalizes the same idea to any doc: a markdown file
can annotate a concrete, checkable claim about the repo's own state with a `doc-fact` comment
immediately next to the prose making that claim, and this script verifies every such annotation
against the live repo instead of trusting the prose to stay in sync by hand.

Annotation syntax — an HTML comment (invisible when the markdown renders), one per fact:

    <!-- doc-fact: <checker> <arg> [<arg> ...] -->

Args are shell-word-split (shlex), so an arg containing spaces needs quotes:

    <!-- doc-fact: file-exists .github/workflows/pr-drain.yml -->
    <!-- doc-fact: file-absent .github/workflows/pr-auto-update.yml -->
    <!-- doc-fact: settings-deny "Bash(tar *)" -->
    <!-- doc-fact: grep-count home/.claude/hooks/block-destructive-git.py "_[a-zA-Z0-9_]+_hit\\(" ge 5 -->

Checkers:
  file-exists   <path>                     path (repo-root-relative) must exist.
  file-absent   <path>                     path (repo-root-relative) must NOT exist.
  settings-deny <rule>                     rule must be exactly an entry in
                                            home/.claude/settings.json's permissions.deny.
  grep-count    <path> <regex> <op> <n>    count of non-overlapping <regex> matches in <path>
                                            (re.findall over the whole file) must satisfy
                                            <op> (eq/ne/ge/le/gt/lt) <n>.

This only checks facts a doc author chose to annotate — it doesn't parse prose, so it complements
lint-hooks-doc.py's two hand-built drift checks rather than replacing them. Exit 0 = every
annotation holds (or none exist); exit 1 = one or more annotated claims no longer match reality.
"""
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / "home" / ".claude" / "settings.json"

DOC_FACT_RE = re.compile(r"<!--\s*doc-fact:\s*(.+?)\s*-->")

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "ge": lambda a, b: a >= b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
}

_settings_cache = None


def _settings():
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = json.loads(SETTINGS_PATH.read_text())
    return _settings_cache


def check_file_exists(args):
    if len(args) != 1:
        return f"file-exists takes exactly 1 arg (path), got {args!r}"
    if not (REPO_ROOT / args[0]).exists():
        return f"claims '{args[0]}' exists, but it does not"
    return None


def check_file_absent(args):
    if len(args) != 1:
        return f"file-absent takes exactly 1 arg (path), got {args!r}"
    if (REPO_ROOT / args[0]).exists():
        return f"claims '{args[0]}' does not exist, but it does"
    return None


def check_settings_deny(args):
    if len(args) != 1:
        return f"settings-deny takes exactly 1 arg (rule), got {args!r}"
    deny = _settings().get("permissions", {}).get("deny", [])
    if args[0] not in deny:
        return f"claims settings.json permissions.deny contains {args[0]!r}, but it does not"
    return None


def check_grep_count(args):
    if len(args) != 4:
        return f"grep-count takes exactly 4 args (path, regex, op, n), got {args!r}"
    path, pattern, op, n = args
    if op not in _OPS:
        return f"grep-count: unknown op '{op}' (expected one of {sorted(_OPS)})"
    try:
        expected = int(n)
    except ValueError:
        return f"grep-count: expected an integer count, got '{n}'"
    target = REPO_ROOT / path
    if not target.exists():
        return f"grep-count: '{path}' does not exist"
    actual = len(re.findall(pattern, target.read_text()))
    if not _OPS[op](actual, expected):
        return f"claims {path} matches /{pattern}/ {op} {expected} times, but it matched {actual} times"
    return None


CHECKERS = {
    "file-exists": check_file_exists,
    "file-absent": check_file_absent,
    "settings-deny": check_settings_deny,
    "grep-count": check_grep_count,
}


def check_doc(doc_path):
    problems = []
    rel = doc_path.relative_to(REPO_ROOT)
    for lineno, line in enumerate(doc_path.read_text().splitlines(), start=1):
        m = DOC_FACT_RE.search(line)
        if not m:
            continue
        try:
            tokens = shlex.split(m.group(1))
        except ValueError as e:
            problems.append(f"{rel}:{lineno}: malformed doc-fact annotation: {e}")
            continue
        if not tokens:
            problems.append(f"{rel}:{lineno}: empty doc-fact annotation")
            continue
        checker = CHECKERS.get(tokens[0])
        if checker is None:
            problems.append(
                f"{rel}:{lineno}: unknown doc-fact checker '{tokens[0]}' "
                f"(known: {', '.join(sorted(CHECKERS))})"
            )
            continue
        problem = checker(tokens[1:])
        if problem:
            problems.append(f"{rel}:{lineno}: {problem}")
    return problems


def tracked_markdown_files():
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [REPO_ROOT / p for p in out.splitlines() if p]


def main():
    problems = []
    for doc_path in tracked_markdown_files():
        problems += check_doc(doc_path)
    if problems:
        print(f"doc-facts check: {len(problems)} problem(s) found\n", file=sys.stderr)
        for p in problems:
            print("  ✗ " + p, file=sys.stderr)
        sys.exit(1)
    print("doc-facts check: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
