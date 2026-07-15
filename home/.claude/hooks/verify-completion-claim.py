#!/usr/bin/env python3
"""Stop hook — the 'no completion claim without fresh evidence' rail from CLAUDE.md, enforced.

DISABLED BY DEFAULT. This is the high-value but higher-risk hook: a Stop hook that blocks
forces the model to keep working, and a false positive is disruptive. Arm it only after you
have watched it run and tuned the predicates — see settings.json for the one-line enable.

Fires ONLY when all three hold, to keep false positives near zero:
  1. the final assistant message makes a strong completion claim (done/fixed/passing/shipped),
  2. product code (not just docs/tests/config) was edited this turn, AND
  3. no verification command (test/build/verify/run) ran this turn.
Then it blocks the stop and reminds the model to produce fresh evidence. Fail-open on any
parse error — a hook bug must never wedge the session.
"""
import json
import re
import sys

CLAIM = re.compile(
    r"\b(all set|done|fixed|resolved|passing|tests? pass|all green|shipped|merged|complete[d]?|"
    r"works now|working now|verified)\b",
    re.I,
)
# A verification actually happened if the transcript shows one of these being run this turn.
VERIFY = re.compile(
    r"\b(pytest|npm (run )?test|npm test|jest|vitest|go test|cargo test|bash -n|"
    r"/verify\b|/bet\b|make test|tox|ruff|mypy|tsc\b|playwright|/run\b|\bnode .*test)\b",
    re.I,
)
# Product-code edits (vs docs/config/tests) — a claim over these is the risky kind.
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java", ".c", ".cpp", ".sh")


def turn_lines(transcript_path):
    """Yield the JSONL records for the most recent turn (since the last user message)."""
    try:
        with open(transcript_path) as f:
            records = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []
    # Walk back to the last user message; everything after is this turn.
    for i in range(len(records) - 1, -1, -1):
        role = (records[i].get("message") or {}).get("role") or records[i].get("role")
        if role == "user":
            return records[i + 1 :]
    return records


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("stop_hook_active"):  # already forced a continuation once; don't loop
        sys.exit(0)

    records = turn_lines(data.get("transcript_path", ""))
    if not records:
        sys.exit(0)

    blob = json.dumps(records)
    edited_code = bool(re.search(r'"(Edit|Write)"', blob)) and any(
        ext in blob for ext in CODE_EXT
    )
    final_text = ""
    for r in reversed(records):
        msg = r.get("message") or r
        if (msg.get("role") == "assistant") and isinstance(msg.get("content"), (str, list)):
            c = msg["content"]
            final_text = c if isinstance(c, str) else json.dumps(c)
            break

    if not edited_code:
        sys.exit(0)
    if not CLAIM.search(final_text):
        sys.exit(0)
    if VERIFY.search(blob):
        sys.exit(0)

    print(
        "Completion-claim rail: you claimed done/fixed/passing over edited product code, but no "
        "verification command ran this turn. Exercise the change (a test, /verify, or /bet) and "
        "read it pass before claiming it — 'should work' is not evidence.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
