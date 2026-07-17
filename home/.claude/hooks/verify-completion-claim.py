#!/usr/bin/env python3
"""Stop hook — the 'no completion claim without fresh evidence' rail from CLAUDE.md, enforced.

DISABLED BY DEFAULT. This is the high-value but higher-risk hook: a Stop hook that blocks
forces the model to keep working, and a false positive is disruptive. Arm it only after you
have watched it run and tuned the predicates — see hooks/README.md for the one-line enable.

Fires ONLY when all three hold, to keep false positives near zero:
  1. the final assistant message makes a strong completion claim (done/fixed/passing/shipped),
  2. product code (not just docs/tests/config) was edited this turn, AND
  3. no verification command (test/build/verify/run) ran this turn.
Then it blocks the stop and reminds the model to produce fresh evidence. Fail-open on any
parse error — a hook bug must never wedge the session.
"""
import json
import os
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
    r"/verify\b|/bet\b|make test|tox|ruff|mypy|tsc\b|playwright|/run\b|\bnode .*test)\b"
    # Skill tool_use records serialize as {"name": "Skill", "input": {"skill": "verify", ...}}
    # (no leading slash on the skill name) and SlashCommand records as
    # {"name": "SlashCommand", "input": {"command": "/verify ..."}} — confirmed against a
    # live transcript capture (see #109). The literal /verify|/bet|/run patterns above only
    # match Bash commands typed with a leading slash and miss both of these.
    r'|"skill":\s*"(verify|bet|run)"|"command":\s*"/(verify|bet|run)\b',
    re.I,
)
# Product-code edits (vs docs/config/tests) — a claim over these is the risky kind.
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java", ".c", ".cpp", ".sh")


def is_tool_result(record):
    """True if a role:'user' record is actually a tool-result carrier, not a human prompt."""
    if "toolUseResult" in record:
        return True
    msg = record.get("message") or record
    content = msg.get("content")
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


def turn_lines(transcript_path):
    """Yield the JSONL records for the most recent turn (since the last genuine user message)."""
    try:
        with open(transcript_path) as f:
            records = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return []
    # Walk back to the last human user message, skipping tool-result records (also role:"user").
    for i in range(len(records) - 1, -1, -1):
        role = (records[i].get("message") or {}).get("role") or records[i].get("role")
        if role == "user" and not is_tool_result(records[i]):
            return records[i + 1 :]
    return records


def assistant_text_blocks(records):
    """Yield text content from assistant text blocks only — never tool_use inputs."""
    for r in records:
        msg = r.get("message") or r
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        yield text


def edited_file_paths(records):
    """Yield file_path values from Edit/Write tool_use blocks in this turn's records."""
    for r in records:
        msg = r.get("message") or r
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") in ("Edit", "Write"):
                path = (block.get("input") or {}).get("file_path")
                if isinstance(path, str):
                    yield path


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
    edited_code = any(
        os.path.splitext(path)[1] in CODE_EXT for path in edited_file_paths(records)
    )
    final_text = ""
    for r in reversed(records):
        msg = r.get("message") or r
        if (msg.get("role") == "assistant") and isinstance(msg.get("content"), (str, list)):
            final_text = "\n".join(assistant_text_blocks([r]))
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
