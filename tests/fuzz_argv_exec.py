#!/usr/bin/env python3
"""Execution-grounded differential fuzzer for `_hookutil.strip_prefixes()` (#228).

`tests/fuzz_argv_canon.py` deliberately generates its wrapper-flag cases from an INDEPENDENT
reference table rather than `_hookutil.WRAPPER_VALUE_OPTS` itself, so a gap in the production
code's own bookkeeping can't also blind the generator to it (see that module's docstring). That
principle has a hole: a hand-authored table can still encode the SAME wrong mental model as the
code under test, in the same direction — which is exactly what happened with env(1)'s
`-S`/`--split-string` (#227). Both `_hookutil.WRAPPER_VALUE_OPTS` and
`fuzz_argv_canon.REFERENCE_WRAPPER_VALUE_FLAGS` modeled `-S` as "a flag that consumes one opaque
following token", so a fuzzer generating `["env", "-S", "VAL", "curl", ...]` and asserting
`strip_prefixes(...) == ["curl", ...]` passed even though the real bypass — `-S`'s value being
shell-word-split into the START of the real command — existed the whole time. Independent-of-the-
production-constant is not the same as independent-of-the-author's-mental-model.

This harness closes that hole a different way: it doesn't hand-author an expectation at all. It
actually runs the real `env` binary (via a real shell, via `subprocess`) pointed at a tiny
argv-echoing helper script, observes what `env` ACTUALLY executed, and compares that to what
`strip_prefixes()` predicts from the exact same command string. The real OS/shell/coreutils
becomes the oracle instead of a second guess — there is nothing left here for a table author to
get wrong, because no table is involved in forming the expected answer.

Also runs a couple of already-covered wrappers (`timeout -s`, `nice -n`) through the same real-
execution machinery, as a sanity check that the comparison itself is sound and not merely tuned to
pass on `-S`.

Deliberately out of scope for this first version (real follow-up, not silently dropped — same
convention as fuzz_argv_canon.py's docstring):
  - xargs: doesn't exec-passthrough its command the way env/timeout/nice do — it reads stdin and
    batches/repeats invocations per `-n`/`-L`/`-P`. A genuinely different execution model that
    deserves its own harness, not a variant of this one.
  - sudo/doas: real privilege elevation needs a target user/group and passwordless sudo that this
    suite doesn't control — depending on that for a required CI gate would fail this test for
    reasons that have nothing to do with the code under test. `fuzz_argv_canon.py`'s independent-
    table coverage of both stands as-is.
  - stdbuf's `-i`/`-o`/`-e` and exec's `-a`: uncontroversially opaque values (a buffering mode
    letter, an argv[0] override) with no "value is itself a sub-command" shape like `-S`'s —
    grounding them in real execution would mostly re-prove what the independent table already gets
    right, not close a live gap.

Exit 0 = no violation found; exit 1 = at least one, each printed with the command that triggered it.
"""
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.join(HERE, "..", "home", ".claude", "hooks")
sys.path.insert(0, HOOKS_DIR)

from _hookutil import basename, pieces, strip_prefixes  # noqa: E402

ARGV_ECHO_SCRIPT = """#!/bin/sh
echo ARGV_ECHO_OK
for a in "$@"; do
  printf '%s\\n' "$a"
done
"""


def make_helper():
    """A tiny real, executable script that reports the argv it actually received — the ground
    truth this harness compares strip_prefixes()'s prediction against."""
    fd, path = tempfile.mkstemp(prefix="argv_echo_", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write(ARGV_ECHO_SCRIPT)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def run_real(command):
    """Execute `command` in a real shell; return the trailing argv the helper actually observed,
    or None if the helper never ran (the wrapper errored, or something else got exec'd)."""
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None
    lines = result.stdout.splitlines()
    if not lines or lines[0] != "ARGV_ECHO_OK":
        return None
    return lines[1:]


def predicted(command, helper):
    """What strip_prefixes() predicts for the real command word + trailing args, from the exact
    same raw command string real execution parsed — via the same pieces()/strip_prefixes() path
    every rail uses. Returns (says_helper_runs, trailing_args)."""
    for argv in pieces(command):
        stripped = strip_prefixes(argv)
        if stripped and basename(stripped[0]) == basename(helper):
            return True, stripped[1:]
    return False, []


def env_split_string_cases(helper):
    """Every documented -S/--split-string form (#227). Only the trailing args each case's shell
    text puts after `helper` — no separate hand-authored expectation of what `-S` does."""
    return [
        f"env -S '{helper} a1 a2'",
        f"env -S'{helper} a1 a2'",
        f'env --split-string="{helper} a1 a2"',
        f"env -S '{helper} a1' a2",
        f'env -S \'"{helper}" a1\'',
        f"env -S '{helper}\\_a1'",
        f"env -S 'env {helper} a1 a2'",
        f"env -S 'FOO=bar {helper} a1'",
    ]


def sanity_cases(helper):
    """Already-covered wrappers, run for real, checking this harness's own comparison machinery
    agrees with the independent-table coverage rather than only ever having been exercised on -S."""
    return [
        f"timeout -s TERM 5 {helper} a1",
        f"nice -n 5 {helper} a1",
    ]


def check(command, helper, violations):
    real_observed = run_real(command)
    real_says_runs = real_observed is not None
    pred_says_runs, pred_args = predicted(command, helper)

    if pred_says_runs != real_says_runs:
        violations.append(
            "%r: strip_prefixes() predicts the helper %s run, real execution says it %s ran"
            % (command, "does" if pred_says_runs else "does NOT",
               "actually" if real_says_runs else "never")
        )
        return
    if real_says_runs and pred_args != real_observed:
        violations.append(
            "%r: strip_prefixes() predicted trailing args %r, real execution observed %r"
            % (command, pred_args, real_observed)
        )


def main():
    helper = make_helper()
    try:
        violations = []
        for command in env_split_string_cases(helper) + sanity_cases(helper):
            check(command, helper, violations)
    finally:
        os.unlink(helper)

    if violations:
        print(f"argv-canon execution fuzzer: {len(violations)} violation(s) found:", file=sys.stderr)
        for v in violations:
            print(f"  FAIL: {v}", file=sys.stderr)
        return 1

    print("argv-canon execution fuzzer: no violations found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
