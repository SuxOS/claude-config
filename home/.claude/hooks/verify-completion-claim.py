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

from _hookutil import load_hook_input

CLAIM = re.compile(
    r"\b(all set|done|fixed|resolved|passing|tests? pass|all green|shipped|merged|complete[d]?|"
    r"works now|working now|verified)\b",
    re.I,
)
# A verification actually happened if this turn's records show one of these being RUN — a
# Bash tool_use whose command matches, a SlashCommand tool_use invoking /verify|/bet|/run, or a
# Skill tool_use naming one of them. Checked against the tool_use blocks themselves (see
# verification_ran() below), never against the serialized transcript text — a text/substring
# match also fires on a mere MENTION of the command name in assistant prose ("I'll run npm test
# next") or inside an edited file's own content (e.g. a Python file whose new text contains the
# word "pytest"), neither of which is evidence the command actually ran (#83). `bash -n` is
# deliberately NOT in this set — it only parses a script for syntax errors, never executes it
# (see ci.yml's install-smoke job for the same distinction), so it is not real behavioral
# verification evidence (#329).
VERIFY_CMD = re.compile(
    r"\b(?:pytest|npm (?:run )?test|jest|vitest|go test|cargo test|"
    r"make test|tox|ruff|mypy|tsc|playwright|node .*test)\b",
    re.I,
)
VERIFY_SLASH = re.compile(r"^/(?:verify|bet|run)\b", re.I)
VERIFY_SKILLS = {"verify", "bet", "run"}
# Product-code edits (vs docs/config/tests) — a claim over these is the risky kind.
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java", ".c", ".cpp", ".sh", ".ipynb")


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


def verification_ran(records):
    """True if this turn's records show an actual verification tool call, not just a mention."""
    for r in records:
        msg = r.get("message") or r
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            tool_input = block.get("input") or {}
            if name == "Bash":
                command = tool_input.get("command")
                if isinstance(command, str) and VERIFY_CMD.search(command):
                    return True
            elif name == "SlashCommand":
                command = tool_input.get("command")
                if isinstance(command, str) and VERIFY_SLASH.search(command.strip()):
                    return True
            elif name == "Skill":
                skill = tool_input.get("skill")
                if isinstance(skill, str) and skill.lower() in VERIFY_SKILLS:
                    return True
    return False


def edited_file_paths(records):
    """Yield file_path values from Edit/Write/NotebookEdit tool_use blocks in this turn's
    records. NotebookEdit carries its path in `notebook_path`, not `file_path` (#250)."""
    for r in records:
        msg = r.get("message") or r
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            name = block.get("name")
            tool_input = block.get("input") or {}
            if name in ("Edit", "Write"):
                path = tool_input.get("file_path")
            elif name == "NotebookEdit":
                path = tool_input.get("notebook_path")
            else:
                continue
            if isinstance(path, str):
                yield path


def main():
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)
    if data.get("stop_hook_active"):  # already forced a continuation once; don't loop
        sys.exit(0)

    records = turn_lines(data.get("transcript_path", ""))
    if not records:
        sys.exit(0)

    edited_code = any(
        os.path.splitext(path)[1] in CODE_EXT for path in edited_file_paths(records)
    )
    final_text = ""
    for r in reversed(records):
        msg = r.get("message") or r
        c = msg.get("content")
        if msg.get("role") != "assistant" or not isinstance(c, (str, list)):
            continue
        if isinstance(c, str):
            final_text = c
        else:
            # Only the assistant's own prose (type=='text' blocks), never a tool_use block's
            # input — json.dumps()-ing the whole content list would also match a completion word
            # sitting inside a tool CALL (e.g. a Bash tool_use `git commit -m "fix: resolved..."`),
            # which is not a prose completion claim (#108). Mirrors verification_ran()'s
            # tool_use-only walk, just for the opposite block type.
            final_text = " ".join(
                block.get("text", "")
                for block in c
                if isinstance(block, dict) and block.get("type") == "text"
            )
        break

    if not edited_code:
        sys.exit(0)
    if not CLAIM.search(final_text):
        sys.exit(0)
    if verification_ran(records):
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
