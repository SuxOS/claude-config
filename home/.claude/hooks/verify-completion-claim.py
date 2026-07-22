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

SHADOW MODE (#324): set VERIFY_COMPLETION_CLAIM_SHADOW=1 (e.g. in the settings.json `command`
string) to wire this as a live Stop hook that never blocks — every evaluated turn appends a
JSON line (transcript_path, would_fire, reason) to VERIFY_COMPLETION_CLAIM_LOG (default
~/.claude/verify-completion-claim.log) instead of exiting 2. Watch that log across real
sessions to tune the predicates before ever arming the hook for real.
"""
import json
import os
import re
import sys
import time

from _hookutil import basename, load_hook_input, pieces, strip_prefixes

SHADOW_LOG_DEFAULT = os.path.expanduser("~/.claude/verify-completion-claim.log")

CLAIM = re.compile(
    r"\b(all set|done|fixed|resolved|passing|passed|tests? pass|all green|shipped|merged|"
    r"complete[d]?|works now|working now|verified)\b",
    re.I,
)
# A negation word/contraction within a few tokens BEFORE a CLAIM hit means the claim is being
# denied, not made ("Not done yet", "isn't fixed") — a bare word-presence regex like CLAIM has no
# way to see that on its own (#332).
NEGATION_RE = re.compile(
    r"\b(?:not|never|no longer|isn't|wasn't|aren't|weren't|doesn't|didn't|won't|wouldn't|"
    r"couldn't|shouldn't|can't|cannot|hasn't|haven't|hadn't)\b",
    re.I,
)
NEGATION_WINDOW_WORDS = 6
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
#
# Matched by TOKENIZING the Bash command (`_hookutil.pieces()`/`strip_prefixes()`) and checking
# only the actual program/subcommand word of each simple command — never by substring-searching
# the whole command string. A substring search also false-matches quoted text that happens to
# contain a verify-shaped phrase, e.g. `git commit -am "fix node parsing edge case; closes flaky
# test issue"` matching the loose `node .*test` alternative even though only `git commit` ran
# (#333). This mirrors how VERIFY_SLASH is already anchored to the start of a slash command
# rather than searched anywhere in it.
VERIFY_SIMPLE_CMDS = {"pytest", "jest", "vitest", "tox", "ruff", "mypy", "tsc", "playwright"}
VERIFY_SUBCOMMANDS = {"go": "test", "cargo": "test", "make": "test"}
VERIFY_SLASH = re.compile(r"^/(?:verify|bet|run)\b", re.I)
VERIFY_SKILLS = {"verify", "bet", "run"}


def _piece_verifies(argv):
    """True if this single simple command's argv (post wrapper-stripping) is a real verification
    command invocation, matched on its actual program/subcommand word rather than a substring."""
    argv = strip_prefixes(argv)
    if not argv:
        return False
    cmd = basename(argv[0]).lower()
    rest = [a.lower() for a in argv[1:]]
    if cmd in VERIFY_SIMPLE_CMDS:
        return True
    if cmd in VERIFY_SUBCOMMANDS:
        return bool(rest) and rest[0] == VERIFY_SUBCOMMANDS[cmd]
    if cmd == "npm":
        if rest and rest[0] == "test":
            return True
        return len(rest) >= 2 and rest[0] == "run" and rest[1] == "test"
    if cmd == "node":
        return any("test" in a for a in rest)
    return False


def command_verifies(command):
    """True if any simple command inside this Bash `command` string is a real verification
    command — tokenized via `_hookutil.pieces()`, substitution-aware, one simple command at a
    time, rather than substring-matched against the raw string (#333)."""
    try:
        for argv in pieces(command):
            if _piece_verifies(argv):
                return True
    except Exception:
        return False
    return False
# Product-code edits (vs docs/config/tests) — a claim over these is the risky kind.
CODE_EXT = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".rb", ".java", ".kt",
    ".swift", ".scala", ".php", ".c", ".cpp", ".sh", ".ipynb", ".html", ".css", ".scss",
)


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


# Signals a Bash tool_result carries a FAILED verification run, checked in addition to the
# `is_error` field a failed tool call itself sets — a test runner exits nonzero on a failure but
# Claude Code doesn't necessarily mark that as `is_error` (it's a normal, non-crashing tool
# result), so the transcript's own content is the only place the failure shows up (#362): a
# pytest-style "N failed" summary line or an unhandled traceback.
RESULT_FAILED = re.compile(r"\b[1-9]\d*\s+failed\b|\bFAILED\b|Traceback \(most recent call last\)")


def _result_text(result):
    content = result.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _result_failed(result):
    """True if a tool_result block indicates the command it answers actually failed — checked
    before crediting a matching Bash invocation as real verification evidence (#362): the hook
    must confirm a passing result was read, not just that a verify-shaped command was run."""
    if not isinstance(result, dict):
        return False
    if result.get("is_error") is True:
        return True
    return bool(RESULT_FAILED.search(_result_text(result)))


def _tool_results_by_id(records):
    """Map tool_use_id -> its tool_result block, across this turn's records."""
    results = {}
    for r in records:
        msg = r.get("message") or r
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str):
                    results[tool_use_id] = block
    return results


def verification_ran(records):
    """True if this turn's records show an actual verification tool call that SUCCEEDED, not
    just a mention and not a command that ran but failed — checked for Bash (#362) and, the same
    way, for SlashCommand/Skill invocations of /verify|/bet|/run (#418): a matching invocation
    whose own tool_result reports failure is not evidence either."""
    results_by_id = _tool_results_by_id(records)
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
                if not isinstance(command, str) or not command_verifies(command):
                    continue
                result = results_by_id.get(block.get("id"))
                if result is not None and _result_failed(result):
                    continue
                return True
            elif name == "SlashCommand":
                command = tool_input.get("command")
                if not isinstance(command, str) or not VERIFY_SLASH.search(command.strip()):
                    continue
                result = results_by_id.get(block.get("id"))
                if result is not None and _result_failed(result):
                    continue
                return True
            elif name == "Skill":
                skill = tool_input.get("skill")
                if not isinstance(skill, str) or skill.lower() not in VERIFY_SKILLS:
                    continue
                result = results_by_id.get(block.get("id"))
                if result is not None and _result_failed(result):
                    continue
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


def _negated(text, match_start):
    """True if a negation word (not/isn't/wasn't/doesn't/...) appears within
    NEGATION_WINDOW_WORDS words immediately before `match_start` — 'Not done yet' or 'isn't
    fixed' deny completion rather than claim it, even though the bare trigger word (done/fixed)
    is still there for CLAIM's word-presence match to find (#332)."""
    before_words = text[:match_start].split()
    tail = " ".join(before_words[-NEGATION_WINDOW_WORDS:])
    return bool(NEGATION_RE.search(tail))


def has_unnegated_claim(text):
    """True if CLAIM matches somewhere in `text` that isn't immediately preceded by a negation
    (#332) — a message can contain a trigger word while explicitly denying completion."""
    return any(not _negated(text, m.start()) for m in CLAIM.finditer(text))


def evaluate(records, edited_code, final_text):
    """Return (would_fire, reason) for the completion-claim predicate over this turn."""
    if not edited_code:
        return False, "no product-code edit this turn"
    if not has_unnegated_claim(final_text):
        return False, "no completion claim in the final assistant message"
    if verification_ran(records):
        return False, "a verification command ran this turn"
    return True, "completion claim over edited product code with no verification command"


SHADOW_LOG_MAX_LINES = 5000


def _rotate_shadow_log(log_path):
    """Truncate the log to its last SHADOW_LOG_MAX_LINES lines once it grows past that, so a
    long-running shadow-mode session doesn't grow the file unbounded."""
    try:
        with open(log_path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    if len(lines) <= SHADOW_LOG_MAX_LINES:
        return
    with open(log_path, "w") as f:
        f.writelines(lines[-SHADOW_LOG_MAX_LINES:])


def log_shadow(log_path, transcript_path, would_fire, reason):
    """Append a structured shadow-mode decision line. Never raises — a logging failure must not
    turn a shadow (non-blocking) run into a wedged session."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "transcript_path": transcript_path,
        "would_fire": would_fire,
        "reason": reason,
    }
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        _rotate_shadow_log(log_path)
    except Exception:
        pass


def main():
    shadow = os.environ.get("VERIFY_COMPLETION_CLAIM_SHADOW", "").strip().lower() in (
        "1", "true", "yes",
    )
    log_path = os.environ.get("VERIFY_COMPLETION_CLAIM_LOG") or SHADOW_LOG_DEFAULT

    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)
    if data.get("stop_hook_active"):  # already forced a continuation once; don't loop
        sys.exit(0)

    transcript_path = data.get("transcript_path", "")
    records = turn_lines(transcript_path)
    if not records:
        sys.exit(0)

    edited_code = any(
        os.path.splitext(path)[1].lower() in CODE_EXT for path in edited_file_paths(records)
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

    would_fire, reason = evaluate(records, edited_code, final_text)

    if shadow:
        log_shadow(log_path, transcript_path, would_fire, reason)
        sys.exit(0)

    if not would_fire:
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
