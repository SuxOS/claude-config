#!/usr/bin/env python3
"""Lint the skill eval fixtures (home/.claude/skills/*/evals/evals.json) for structural rot.

AUTHORING.md makes test-first the one governing rule — "No skill (or edit) without a failing test
first" — and each skill ships an evals.json of {prompt, expected_output} pressure scenarios that
encode that discipline. `json-validate` already proves every tracked JSON *parses*, but a file that
parses can still be a useless test corpus: an eval with no `expected_output` has no graded target,
an empty `prompt` exercises nothing, a `skill_name` that drifts from its directory silently mis-files
the whole suite. Those failures are invisible today, and #21/#61 keep adding evals.json by hand and
by agent, so the shape rots unless something enforces it. This turns the contract into a CI gate
(issue #95) — the deterministic first rail (advisory-first, like settings-lint) under the larger
"run each skill against its evals and grade the transcript" harness that issue also envisions.

The enforced contract per file:

  1. top level is an object with `skill_name` (non-empty string) and `evals` (a non-empty list).
  2. `skill_name` matches the owning skill directory — home/.claude/skills/<name>/evals/evals.json.
  3. each eval item is an object carrying:
       - `id`            : an integer, unique within the file.
       - `prompt`        : a non-empty string (the pressure scenario given to a fresh model).
       - `expected_output`: a non-empty string (what a pass looks like — the grader's rubric).
       - `files`         : a list (fixture files the scenario needs; [] when none).

Exit 0 = every fixture is well-formed; exit 1 = one or more violations (each printed with file +
what + why + fix). Invalid JSON is itself a failure. Paths: argv[1..], else every tracked fixture
under home/.claude/skills/*/evals/evals.json relative to the repo root.
"""
import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_GLOB = "home/.claude/skills/*/evals/evals.json"


def skill_name_from_path(path):
    """The owning skill directory for .../skills/<name>/evals/evals.json, or None if not that shape."""
    parts = path.resolve().parts
    try:
        # last occurrence: an ancestor dir (e.g. a checkout under ~/dev/skills/) can also be named
        # "skills", but the fixture layout is always .../skills/<name>/evals/evals.json.
        i = len(parts) - 1 - parts[::-1].index("skills")
    except ValueError:
        return None
    # skills/<name>/evals/evals.json  → <name> is the segment right after "skills".
    return parts[i + 1] if i + 1 < len(parts) else None


def nonempty_str(value):
    return isinstance(value, str) and value.strip() != ""


def lint(fixture_path):
    problems = []
    path = Path(fixture_path)
    where = str(path)

    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return [f"{where}: file not found"]
    except json.JSONDecodeError as e:
        return [f"{where}: invalid JSON — {e}"]

    if not isinstance(data, dict):
        return [
            f"{where}: EVALS-NOT-OBJECT  top level is {type(data).__name__}, expected an object with "
            f"'skill_name' and 'evals'. Fix: wrap the scenarios as "
            f'{{"skill_name": "...", "evals": [...]}}.'
        ]

    if not nonempty_str(data.get("skill_name")):
        problems.append(
            f"{where}: EVALS-MISSING-SKILL-NAME  no non-empty 'skill_name'. Fix: add "
            f'"skill_name": "<skill>" naming the skill this suite exercises.'
        )
    else:
        owner = skill_name_from_path(path)
        if owner is not None and data["skill_name"] != owner:
            problems.append(
                f"{where}: EVALS-SKILL-NAME-MISMATCH  'skill_name' is {data['skill_name']!r} but the "
                f"fixture lives under skills/{owner}/. Fix: set 'skill_name' to {owner!r} so the suite "
                f"grades the skill it ships with."
            )

    evals = data.get("evals")
    if not isinstance(evals, list):
        problems.append(
            f"{where}: EVALS-MISSING-EVALS  'evals' is {type(evals).__name__}, expected a list. Fix: "
            f"make 'evals' a list of {{id, prompt, expected_output, files}} scenarios."
        )
        return problems
    if not evals:
        problems.append(
            f"{where}: EVALS-EMPTY  'evals' is empty — an inert corpus enforces nothing (AUTHORING.md: "
            f"no skill without a failing test). Fix: add at least one pressure scenario."
        )
        return problems

    seen_ids = set()
    for idx, item in enumerate(evals):
        tag = f"evals[{idx}]"
        if not isinstance(item, dict):
            problems.append(
                f"{where}: EVAL-ITEM-NOT-OBJECT  {tag} is {type(item).__name__}, expected an object with "
                f"id/prompt/expected_output/files."
            )
            continue

        item_id = item.get("id")
        if not isinstance(item_id, int) or isinstance(item_id, bool):
            problems.append(
                f"{where}: EVAL-BAD-ID  {tag} 'id' is {item_id!r}, expected an integer. Fix: give each "
                f"scenario a unique integer id."
            )
        elif item_id in seen_ids:
            problems.append(
                f"{where}: EVAL-DUPLICATE-ID  {tag} reuses id {item_id} — ids must be unique within the "
                f"file. Fix: renumber the duplicate."
            )
        else:
            seen_ids.add(item_id)

        if not nonempty_str(item.get("prompt")):
            problems.append(
                f"{where}: EVAL-MISSING-PROMPT  {tag} has no non-empty 'prompt' — nothing to run against "
                f"the model. Fix: add the pressure scenario as 'prompt'."
            )
        if not nonempty_str(item.get("expected_output")):
            problems.append(
                f"{where}: EVAL-MISSING-EXPECTED-OUTPUT  {tag} has no non-empty 'expected_output' — an "
                f"eval with no graded target can never fail, so it enforces nothing. Fix: describe what a "
                f"pass looks like in 'expected_output'."
            )
        if not isinstance(item.get("files"), list):
            problems.append(
                f"{where}: EVAL-BAD-FILES  {tag} 'files' is {type(item.get('files')).__name__}, expected a "
                f"list (use [] when the scenario needs no fixture files)."
            )

    return problems


def discover(argv):
    if argv:
        return [Path(a) for a in argv]
    return sorted(REPO_ROOT.glob(FIXTURE_GLOB))


def find_missing_fixtures():
    """Skill dirs (containing SKILL.md) with no evals/evals.json — silently skipped by the glob."""
    missing = []
    for skill_md in sorted(REPO_ROOT.glob("home/.claude/skills/*/SKILL.md")):
        skill_dir = skill_md.parent
        if not (skill_dir / "evals" / "evals.json").exists():
            missing.append(
                f"{skill_dir}: EVALS-MISSING-FIXTURE  no evals/evals.json for this skill. Fix: add "
                f'{skill_dir}/evals/evals.json with {{"skill_name": "{skill_dir.name}", "evals": [...]}}.'
            )
    return missing


def main():
    argv = sys.argv[1:]
    fixtures = discover(argv)

    all_problems = []
    for fixture in fixtures:
        all_problems.extend(lint(fixture))

    all_problems.extend(find_missing_fixtures())

    if not fixtures and not all_problems:
        print("evals lint: no eval fixtures found")
        return 0

    if all_problems:
        print(f"evals lint: {len(all_problems)} problem(s) found\n", file=sys.stderr)
        for p in all_problems:
            print("  ✗ " + p, file=sys.stderr)
        return 1

    print(f"evals lint: OK ({len(fixtures)} fixture(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
