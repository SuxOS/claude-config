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

from _hookutil import load_hook_input

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
VERIFY_CMD = re.compile(
    r"\b(?:pytest|npm (?:run )?test|jest|vitest|go test|cargo test|"
    r"make test|tox|ruff|mypy|tsc|playwright|node .*test)\b",
    re.I,
)
VERIFY_SLASH = re.compile(r"^/(?:verify|bet|run)\b", re.I)
VERIFY_SKILLS = {"verify", "bet", "run"}
# Product-code edits (vs docs/config/tests) — a claim over these is the risky kind.
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java", ".c", ".cpp", ".sh", ".ipynb")
# A Bash command can also write product code (sed -i, tee, a `>`/`>>` redirect, a heredoc `cat >`)
# without ever going through Edit/Write/NotebookEdit — invisible to edited_file_paths()'s tool_use
# scan otherwise (#369). Conservative on purpose: a miss just falls through to "no code edit" (a
# harmless allow, matching this file's fail-open philosophy), so only fairly confident shapes match.
_CODE_EXT_ALT = "|".join(re.escape(ext) for ext in CODE_EXT)
_CODE_TOKEN = r"['\"]?(\S+(?:" + _CODE_EXT_ALT + r"))['\"]?"
BASH_REDIRECT_TARGET = re.compile(r">{1,2}\s*" + _CODE_TOKEN)
BASH_TEE_TARGET = re.compile(r"\btee\b(?:\s+-a\b)?\s+" + _CODE_TOKEN)
# sed -i's file operand trails its (often quoted, slash-heavy) script argument — rather than
# parse sed's own grammar, just check the LAST whitespace-separated token of the command, which
# is where the target file sits for the overwhelmingly common `sed -i 's/x/y/' file.py` shape.
BASH_SED_I = re.compile(r"\bsed\b\s+-i\S*\b")


def bash_writes_code(command):
    """True if a Bash command looks like it writes to a product-code file — a redirect, `tee`,
    or `sed -i` target with one of CODE_EXT's extensions."""
    if BASH_REDIRECT_TARGET.search(command) or BASH_TEE_TARGET.search(command):
        return True
    if BASH_SED_I.search(command):
        last_token = command.split()[-1] if command.split() else ""
        if os.path.splitext(last_token.strip("'\""))[1] in CODE_EXT:
            return True
    return False


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
    records. NotebookEdit carries its path in `notebook_path`, not `file_path` (#250). Also
    yields a synthetic code-extension path for a Bash tool_use whose command writes to a
    product-code file via redirect/tee/sed -i (#369) — those never go through Edit/Write at
    all, so they'd otherwise be invisible to the caller's CODE_EXT check."""
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
            elif name == "Bash":
                command = tool_input.get("command")
                if isinstance(command, str) and bash_writes_code(command):
                    yield "<bash-write>.sh"
                continue
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
