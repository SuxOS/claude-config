#!/usr/bin/env python3
"""Run the real-shape hook fixture corpus and assert each hook's exit-code contract (#117).

A large share of the hook bug history is one root cause: the hooks parse real Claude Code
tool-input / transcript JSON and repeatedly get the SHAPE wrong (#62, #80, #105, #108, #111,
#112). tests/test_hooks.sh already exercises the hooks, but with hand-authored synthetic JSON —
the same shape the author guessed. A wrong guess in the hook and a matching wrong guess in the
test then pass together, so the test cannot catch the very bug class it exists for.

This runner closes that: it drives each live hook under home/.claude/hooks/ against a committed
corpus captured in the REAL Claude Code envelope shape (tests/fixtures/), and asserts the
documented exit-code contract (2 = block, 0 = allow). If Claude Code's schema drifts and a hook
mis-models it, a fixture flips and CI fails here instead of the hook silently wedging a session
or neutering a gate at runtime. See tests/fixtures/README.md for the corpus layout and how to
regenerate/redact fixtures when the schema evolves.

The manifest (tests/fixtures/manifest.json) lists cases of two kinds:
  - "stdin"      : a full PreToolUse hook-input payload piped straight to the hook.
  - "transcript" : a Stop-hook transcript JSONL; the runner synthesizes the Stop envelope
                   ({stop_hook_active, transcript_path -> the fixture}) and pipes that.

Exit 0 = every case matched its expected exit code; exit 1 = one or more mismatched (each
printed with hook + fixture + expected/actual + description). Run: python3 tests/run_fixture_corpus.py
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # tests/
FIXTURES = HERE / "fixtures"
MANIFEST = FIXTURES / "manifest.json"
REPO_ROOT = HERE.parent
HOOKS = REPO_ROOT / "home" / ".claude" / "hooks"

# Redacted, deterministic values for the synthesized Stop envelope. The transcript_path is the
# one field the Stop hook actually reads to a file, so it is filled in per case at run time.
STOP_ENVELOPE_BASE = {
    "session_id": "00000000-0000-0000-0000-000000000000",
    "cwd": "/home/user/example-project",
    "hook_event_name": "Stop",
    "stop_hook_active": False,
}


def run_hook(hook_path, stdin_bytes):
    """Pipe stdin_bytes to the hook and return its exit code (stdout/stderr suppressed)."""
    proc = subprocess.run(
        [sys.executable, str(hook_path)],
        input=stdin_bytes,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode


def build_stdin(case):
    """The stdin payload bytes for a case: a raw PreToolUse fixture, or a synthesized Stop envelope."""
    if "stdin" in case:
        return (FIXTURES / case["stdin"]).read_bytes()
    if "transcript" in case:
        transcript = FIXTURES / case["transcript"]
        if not transcript.exists():
            raise FileNotFoundError(f"transcript fixture not found: {transcript}")
        envelope = dict(STOP_ENVELOPE_BASE, transcript_path=str(transcript))
        return json.dumps(envelope).encode()
    raise ValueError("case has neither 'stdin' nor 'transcript'")


def main():
    try:
        manifest = json.loads(MANIFEST.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"fixture corpus: cannot read manifest {MANIFEST} — {e}", file=sys.stderr)
        return 1

    cases = manifest.get("cases", [])
    if not cases:
        print("fixture corpus: manifest has no cases", file=sys.stderr)
        return 1

    fails = 0

    referenced = {
        (FIXTURES / (case["stdin"] if "stdin" in case else case["transcript"])).resolve()
        for case in cases
        if "stdin" in case or "transcript" in case
    }
    tracked = set((FIXTURES / "pretooluse").glob("*.json")) | set((FIXTURES / "transcripts").glob("*.jsonl"))
    orphans = sorted(f for f in tracked if f.resolve() not in referenced)
    for orphan in orphans:
        print(
            f"  FAIL: {orphan.relative_to(FIXTURES)} — fixture not referenced by any manifest case "
            "(dropped-in-but-unwired, never runs)",
            file=sys.stderr,
        )
        fails += 1

    for case in cases:
        src = case.get("stdin") or case.get("transcript") or "?"
        hook_name = case.get("hook", "?")
        hook_path = HOOKS / hook_name
        expect = case.get("expect_exit")
        desc = case.get("desc", "")

        if not hook_path.exists():
            print(f"  FAIL: {hook_name} <- {src} — hook not found at {hook_path}", file=sys.stderr)
            fails += 1
            continue

        try:
            stdin_bytes = build_stdin(case)
        except (FileNotFoundError, ValueError) as e:
            print(f"  FAIL: {hook_name} <- {src} — {e}", file=sys.stderr)
            fails += 1
            continue

        actual = run_hook(hook_path, stdin_bytes)
        if actual == expect:
            print(f"  ok: {hook_name} <- {src} (exit={actual}) — {desc}")
        else:
            print(
                f"  FAIL: {hook_name} <- {src} — expected exit={expect}, got exit={actual} — {desc}",
                file=sys.stderr,
            )
            fails += 1

    total = len(cases) + len(orphans)
    if fails:
        print(f"fixture corpus: {fails}/{total} case(s) FAILED", file=sys.stderr)
        return 1
    print(f"fixture corpus: all {total} case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
