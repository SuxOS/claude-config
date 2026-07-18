#!/usr/bin/env python3
"""Run each skill's evals.json against a fresh model and grade the transcript (issue #140).

`lint-evals.py` is the deterministic FIRST rail issue #95 shipped: it proves each fixture is a
usable test corpus (non-empty prompt + gradable expected_output, unique ids, skill_name matches its
dir). But #95 also envisioned the layer above it — a runner that actually *runs* each skill against
its evals and grades the result — and that never got built (#140). So today the evals encode
AUTHORING.md's one governing rule ("No skill or edit without a failing test first") as graded
scenarios that nothing ever executes; the corpus is inert beyond parse/shape checks.

This is that runner. For each eval it:
  1. RUN   — invokes the `claude` CLI headless (`-p`) with the eval `prompt`, injecting the skill's
             SKILL.md as an appended system prompt so the skill is "active," plus any fixture
             `files` as context. Tools are disabled (`--disallowedTools`) so a skill run grades the
             model's REASONING/RESPONSE (what every current eval rubric actually tests — "asks a
             clarifying question," "returns the Use/Prompt shape," "refuses to skip test-first"),
             never triggering real side effects.
  2. GRADE — an LLM judge (a second `claude -p` call) is given the prompt, the `expected_output`
             rubric, and the model's actual response, and must return strict JSON
             {"verdict": "pass"|"fail", "reason": "..."}. expected_output is a prose rubric
             (e.g. how/evals/evals.json), so an LLM judge is the natural grader.

## Advisory, and skip-safe by design (the gate-vs-advisory decision)

A model call in CI means cost, secrets, and non-determinism, so this is ADVISORY, not a merge gate:
  - It is wired as its OWN CI job (see .github/workflows/ci.yml `skill-evals`), NOT folded into the
    ruleset-required `shellcheck` job — native auto-merge only waits on ruleset-required checks, so a
    standalone job never blocks merge (the inverse of the config-integrity linters, which had to be
    folded IN to become required — see CLAUDE.md).
  - It SKIPS cleanly (prints a reason, exits 0) whenever there is no model access — the `claude` CLI
    is not on PATH, or no auth token is set (ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN /
    ANTHROPIC_AUTH_TOKEN). CI has no such secret configured, so the job is a clean no-op there until a
    human adds one; nothing flakes. Locally (or once a secret is added) it does the real run.
  - `--gate` flips it to exit 1 on any FAIL, for a human running it deliberately. Default is
    advisory: report pass/fail, exit 0 (unless a runtime/parse error occurs).

Lives under .github/ (NOT home/.claude/), because install.sh symlinks that tree into the user's live
config and this is repo/CI-only tooling (CLAUDE.md).

Usage:
  python3 .github/scripts/run-skill-evals.py [--skill NAME] [--gate] [--dry-run]
                                             [--run-model M] [--judge-model M]
  --dry-run  assembles and prints the RUN + JUDGE prompts for each eval and exits 0 WITHOUT any
             model call — lets an author see exactly what would be sent (and verify this harness)
             with no key.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_GLOB = "home/.claude/skills/*/evals/evals.json"
AUTH_ENV_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")

DEFAULT_RUN_MODEL = "sonnet"    # runs the skill scenario — a capable tier, behavior under test
DEFAULT_JUDGE_MODEL = "opus"    # grades a prose rubric — a hard judgment call, top tier (rule #1)

# The judge's grading contract. It sees only (prompt, rubric, response) and must decide pass/fail
# against the rubric alone, returning STRICT JSON so the verdict parses deterministically.
JUDGE_SYSTEM = (
    "You are a strict grader for skill-behavior evals. You are given a user PROMPT, an "
    "EXPECTED-OUTPUT rubric describing what a correct response must do, and the model's actual "
    "RESPONSE. Decide whether the RESPONSE satisfies the rubric. Judge only against the rubric — "
    "not your own taste. Be strict: partial or hand-wavy compliance is a fail. Reply with ONE JSON "
    'object and nothing else: {"verdict": "pass" | "fail", "reason": "<one sentence>"}.'
)

# Appended to the skill's SKILL.md when running an eval: keep the skill's reasoning, forbid actions.
RUN_FRAMING = (
    "\n\n---\nThe skill above is ACTIVE for this request. Respond as that skill would. This is an "
    "evaluation harness: do NOT execute tools or take any real/irreversible action — produce only "
    "the response text (reasoning, questions, and the answer) the skill would give."
)

# Every tool that could touch the network, the filesystem, or spawn further work. An eval `prompt`
# is scenario content, not trusted instructions, so the RUN call must be reasoning-only: this is a
# denylist of every tool name Claude Code ships, not just the "obviously dangerous" ones, so a new
# tool added later doesn't silently reopen the gap that let WebFetch/WebSearch/Read exfiltrate data
# once ANTHROPIC_API_KEY is wired into CI (found in review of #140 before it ever went live).
DISALLOWED_RUN_TOOLS = (
    "Bash", "Edit", "Write", "Agent", "Task", "Read", "Grep", "Glob",
    "WebFetch", "WebSearch", "NotebookEdit",
)


def discover(skill_filter):
    """The evals.json fixtures to run, optionally filtered to one skill directory."""
    fixtures = sorted(REPO_ROOT.glob(FIXTURE_GLOB))
    if skill_filter:
        fixtures = [f for f in fixtures if f.parent.parent.name == skill_filter]
    return fixtures


def model_access_reason():
    """None if a real run is possible, else a human string explaining why we must skip."""
    if shutil.which("claude") is None:
        return "the `claude` CLI is not on PATH"
    if not any(os.environ.get(v) for v in AUTH_ENV_VARS):
        return "no auth token is set (" + " / ".join(AUTH_ENV_VARS) + ")"
    return None


def load_files_context(fixture_dir, files):
    """Inline any fixture `files` (relative to the eval dir) as context, or raise on a missing one.

    `files` entries come from evals.json, which a PR can add to — so an entry is untrusted input,
    not a trusted path. Reject anything that isn't a plain relative path inside fixture_dir: an
    absolute path (Path.__truediv__ discards the left side for an absolute right side) or a `../`
    escape would otherwise let a crafted evals.json read arbitrary files off the runner (or a local
    reviewer's machine via --dry-run, which needs no key at all).
    """
    if not files:
        return ""
    fixture_dir = fixture_dir.resolve()
    chunks = []
    for name in files:
        fpath = (fixture_dir / name).resolve()
        if fpath != fixture_dir and fixture_dir not in fpath.parents:
            raise ValueError(f"fixture file escapes its eval dir: {name}")
        if not fpath.exists():
            raise FileNotFoundError(f"fixture file not found: {name}")
        chunks.append(f"\n\n--- file: {name} ---\n{fpath.read_text()}")
    return "".join(chunks)


def build_run_prompt(prompt, files_context):
    """The user-turn text for the skill run: the scenario prompt plus any inlined fixture files."""
    return prompt + files_context


def build_judge_prompt(prompt, expected_output, response):
    """The user-turn text for the judge: the scenario, the rubric, and the actual response."""
    return (
        f"PROMPT:\n{prompt}\n\n"
        f"EXPECTED-OUTPUT (rubric):\n{expected_output}\n\n"
        f"RESPONSE:\n{response}\n"
    )


def call_claude(user_prompt, system_prompt, model, disallowed_tools=DISALLOWED_RUN_TOOLS):
    """Run one headless `claude -p` turn and return its final text, or raise on CLI failure.

    Isolated so the ONE piece that touches the model lives behind a single call: tools are disabled
    and output is the JSON envelope whose `result` field is the assistant's final text.
    """
    cmd = [
        "claude", "-p", user_prompt,
        "--model", model,
        "--output-format", "json",
        "--append-system-prompt", system_prompt,
        "--disallowedTools", *disallowed_tools,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:400]}")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"could not parse claude --output-format json envelope: {e}")
    result = envelope.get("result")
    if not isinstance(result, str):
        raise RuntimeError("claude JSON envelope has no string `result` field")
    return result


def extract_verdict(judge_text):
    """Pull the first JSON object out of the judge's reply and normalize it to (verdict, reason)."""
    start = judge_text.find("{")
    if start == -1:
        raise ValueError("judge returned no JSON object")
    obj, _ = json.JSONDecoder().raw_decode(judge_text[start:])
    verdict = str(obj.get("verdict", "")).strip().lower()
    if verdict not in ("pass", "fail"):
        raise ValueError(f"judge verdict is {obj.get('verdict')!r}, expected 'pass' or 'fail'")
    return verdict, str(obj.get("reason", "")).strip()


def grade_eval(fixture_dir, item, args):
    """Run one eval end-to-end; return a result dict {id, status, reason}. status in pass/fail/error."""
    skill_md = (fixture_dir.parent / "SKILL.md").read_text()
    files_context = load_files_context(fixture_dir, item.get("files") or [])
    run_prompt = build_run_prompt(item["prompt"], files_context)
    response = call_claude(run_prompt, skill_md + RUN_FRAMING, args.run_model)
    judge_text = call_claude(build_judge_prompt(item["prompt"], item["expected_output"], response),
                             JUDGE_SYSTEM, args.judge_model)
    verdict, reason = extract_verdict(judge_text)
    return {"id": item.get("id"), "status": verdict, "reason": reason}


def dry_run(fixtures, args):
    """Print the assembled RUN + JUDGE prompts for every eval, without any model call."""
    for fixture in fixtures:
        data = json.loads(fixture.read_text())
        skill = data.get("skill_name", fixture.parent.parent.name)
        for item in data.get("evals", []):
            fdir = fixture.parent
            try:
                files_context = load_files_context(fdir, item.get("files") or [])
            except (FileNotFoundError, ValueError) as e:
                print(f"[{skill} #{item.get('id')}] FILES ERROR: {e}")
                continue
            print(f"===== {skill} #{item.get('id')} — RUN (model={args.run_model}) =====")
            print(build_run_prompt(item.get("prompt", ""), files_context))
            print(f"----- {skill} #{item.get('id')} — JUDGE (model={args.judge_model}) -----")
            print(build_judge_prompt(item.get("prompt", ""), item.get("expected_output", ""),
                                     "<model response goes here>"))
            print()
    return 0


def main():
    parser = argparse.ArgumentParser(description="Run skill evals against a model and grade them.")
    parser.add_argument("--skill", help="only run this skill's evals")
    parser.add_argument("--gate", action="store_true", help="exit 1 on any FAIL (default: advisory)")
    parser.add_argument("--dry-run", action="store_true", help="print prompts, make no model calls")
    parser.add_argument("--run-model", default=DEFAULT_RUN_MODEL)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    args = parser.parse_args()

    fixtures = discover(args.skill)
    if not fixtures:
        print("skill-evals: no eval fixtures found"
              + (f" for skill {args.skill!r}" if args.skill else ""))
        return 0

    if args.dry_run:
        return dry_run(fixtures, args)

    reason = model_access_reason()
    if reason:
        print(f"skill-evals: SKIPPED — {reason}. This job is advisory; set a token (or run "
              f"--dry-run) to grade skills. See the script header for the gate-vs-advisory design.")
        return 0

    total = passed = failed = errored = 0
    for fixture in fixtures:
        data = json.loads(fixture.read_text())
        skill = data.get("skill_name", fixture.parent.parent.name)
        for item in data.get("evals", []):
            total += 1
            tag = f"{skill} #{item.get('id')}"
            try:
                res = grade_eval(fixture.parent, item, args)
            except Exception as e:  # a run/judge/parse error is an ERROR, never a silent pass
                errored += 1
                print(f"  ERROR: {tag} — {e}", file=sys.stderr)
                continue
            if res["status"] == "pass":
                passed += 1
                print(f"  PASS:  {tag} — {res['reason']}")
            else:
                failed += 1
                print(f"  FAIL:  {tag} — {res['reason']}")

    print(f"\nskill-evals: {passed} passed, {failed} failed, {errored} errored, of {total}")
    if args.gate and (failed or errored):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
