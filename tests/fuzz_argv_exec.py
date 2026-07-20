#!/usr/bin/env python3
"""Execution-grounded differential fuzzer over `_hookutil.strip_prefixes()` (#228).

tests/fuzz_argv_canon.py checks strip_prefixes() against an INDEPENDENT hand-authored reference
table (REFERENCE_WRAPPER_VALUE_FLAGS/REFERENCE_SUDO_VALUE_FLAGS) instead of the production
constant it's testing — sound in principle (see that module's docstring), but a hand-authored
table can still be wrong in the same direction as the implementation, and no amount of running
that fuzzer would ever catch it: `env -S`/`--split-string` was in the table with the same "flag
consumes one opaque following token" shape as `-u`/`-C`, when real `env -S STRING` actually
shell-splits STRING and execs THAT as the command — both the table and `_hookutil.py` encoded the
identical wrong model, so the fuzzer's assertions passed even though the bypass was real (#227).

This harness checks ground truth instead of a second guess: it actually execs
`<prefix> <argv-echoing helper> a b` via `bash -c` for real (env, timeout, nice, xargs, stdbuf,
exec, command, sudo — the real binaries on this machine, not a model of them) and diffs the
helper's OBSERVED argv (tests/argv_echo_helper.py, chmod +x, invoked directly so the kernel's own
shebang handling preserves argv[0] exactly as given) against what `strip_prefixes()` predicts for
that same token list. No hand-authored table, however independently written, can substitute for
this — it is checking the implementation against the OS itself.

Scope, deliberately (#312 — splitting this out of #228 rather than letting the general mechanism
get blocked on one flag's bespoke semantics):
  - `env -S`/`--split-string` is EXCLUDED. Real `env -S STRING` re-splits STRING as the START of
    the actual command rather than treating it as an opaque trailing value, so the uniform "wrap
    the helper as a separate trailing argv" shape this harness generates can't model it at all —
    that's #227 (already filed, confirmed, a `_hookutil.py` fix), not a gap in this harness.
  - `time` is EXCLUDED. Bash's `time` is a shell KEYWORD, not the GNU coreutils binary
    `_hookutil.WRAPPER_VALUE_OPTS["time"]`'s flags (`-o`/`-f`) assume — `bash -c "time -o ... cmd"`
    doesn't invoke GNU time at all (`-o` gets parsed as the command name and fails), so real-exec'ing
    it via `bash -c` here would test a construction mismatch, not strip_prefixes() itself.
  - `builtin` is EXCLUDED. By definition it can only invoke an actual shell builtin (`builtin cd`,
    `builtin echo`), never an external program — there's no way to point it at an argv-echoing
    helper script at all, so this harness's method doesn't apply to it.
  - `xargs -I`/`-a`/`--arg-file` are EXCLUDED. `-I` (replace-str) mode only runs its command once
    per STDIN line and does nothing at all on empty stdin (unlike xargs' plain default, which runs
    once even with none) — this harness pipes no stdin, so `-I` cases never execute the helper
    to begin with. `-a`/`--arg-file` needs a real, populated file to read items from; faking one is
    more machinery than this first version is worth.
  - Only `sudo`/`doas` with NO flags, plus `-u`/`--user` (pointed at the invoking user — always
    valid, and passwordless `sudo -u $(whoami)` needs no real privilege escalation) are covered.
    Every other sudo/doas value flag (`-g`/`-r`/`-t`/`-R`/`-D`/`-T`/`-a`/...) needs a realistic,
    SYSTEM-DEPENDENT value (an existing group, an SELinux role, a chroot dir, a remote host) a
    generic CI runner can't reliably supply — faking one would test whether the fake was accepted,
    not whether strip_prefixes() is right. Broader sudo-flag coverage is a natural follow-up once
    each flag has a real value source, not a silent gap.
  - `doas` in particular often isn't installed at all (e.g. plain Ubuntu, this repo's own CI
    image) — see run_real(): a wrapper binary that can't even be found makes its case
    INCONCLUSIVE (skipped), never a reported violation.

Standalone ADVISORY job in CI (see .github/workflows/ci.yml, never folded into the required
`shellcheck` job — mirrors the skill-evals precedent documented in CLAUDE.md): this depends on
real system binaries' exact installed behavior, which is a strictly riskier dependency for a hard
merge gate than tests/fuzz_argv_canon.py's pure computation.

Exit 0 = no violation found (including "every generated case was inconclusive"); exit 1 = at
least one genuine mismatch between a real exec and strip_prefixes()'s prediction, each printed
with its minimal repro.
"""
import getpass
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.join(HERE, "..", "home", ".claude", "hooks")
sys.path.insert(0, HERE)
sys.path.insert(0, HOOKS_DIR)

from _hookutil import SUDO, WRAPPERS, strip_prefixes  # noqa: E402
import fuzz_argv_canon as canon  # noqa: E402

HELPER_PATH = os.path.join(HERE, "argv_echo_helper.py")
HELPER_ARGV = [HELPER_PATH, "a", "b"]

try:
    CURRENT_USER = getpass.getuser()
except Exception:
    CURRENT_USER = None

# Wrappers this harness's method can't apply to at all — see module docstring.
EXEC_EXCLUDED_WRAPPERS = {"time", "builtin"}

# Realistic (not merely well-typed) values for a value-consuming flag — unlike the pure-logic
# fuzzer's generic PLACEHOLDER_VALUE ("VAL"), a real binary validates some of these eagerly (a
# numeric adjustment, a buffering mode, an existing directory) and refuses to even exec the
# wrapped command on a bogus one, which would make every case using that flag inconclusive rather
# than a genuine check. A (wrapper, flag) pair absent here is deliberately not exec-tested — see
# the module docstring's scope note for exactly which and why.
EXEC_REALISTIC_VALUES = {
    ("timeout", "-s"): "KILL", ("timeout", "--signal"): "KILL",
    ("timeout", "-k"): "5", ("timeout", "--kill-after"): "5",
    ("nice", "-n"): "10", ("nice", "--adjustment"): "10",
    ("xargs", "-L"): "1", ("xargs", "-P"): "2",
    ("xargs", "-n"): "3", ("xargs", "-s"): "1000", ("xargs", "-d"): ",",
    ("xargs", "--max-args"): "3", ("xargs", "--max-chars"): "1000",
    ("xargs", "--max-procs"): "2", ("xargs", "--delimiter"): ",",
    ("exec", "-a"): "fakename",
    # stdbuf rejects line-buffering (`L`) on its INPUT stream ("line buffering stdin is
    # meaningless") — `0` (unbuffered) is the value real usage would pass there instead.
    ("stdbuf", "-i"): "0", ("stdbuf", "--input"): "0",
    ("stdbuf", "-o"): "L", ("stdbuf", "--output"): "L",
    ("stdbuf", "-e"): "L", ("stdbuf", "--error"): "L",
    ("env", "-u"): "SOME_VAR", ("env", "--unset"): "SOME_VAR",
    ("env", "-C"): "/tmp", ("env", "--chdir"): "/tmp",
}
# `timeout` mandatorily takes a bare DURATION positional after any flags — real `timeout <helper>`
# with no duration at all fails ("invalid time interval") before it ever reaches the helper.
EXEC_REQUIRED_SUFFIX = {"timeout": ["5"]}
# `stdbuf` requires at least one of -i/-o/-e; unlike every other wrapper here, the bare word alone
# isn't a valid invocation to real-exec at all.
EXEC_NO_BARE = {"stdbuf"}


def exec_wrapper_variants():
    """Real-exec-testable subset of fuzz_argv_canon.wrapper_variants(): every WRAPPERS word this
    harness can apply to (see EXEC_EXCLUDED_WRAPPERS) alone, plus each value-consuming flag paired
    with a value the real binary actually accepts (EXEC_REALISTIC_VALUES) rather than the
    pure-logic fuzzer's generic placeholder."""
    variants = []
    for w in sorted(WRAPPERS - EXEC_EXCLUDED_WRAPPERS):
        suffix = EXEC_REQUIRED_SUFFIX.get(w, [])
        if w not in EXEC_NO_BARE:
            variants.append([w] + suffix)
        for opt in sorted(canon.REFERENCE_WRAPPER_VALUE_FLAGS.get(w, ())):
            if (w, opt) not in EXEC_REALISTIC_VALUES:
                continue
            val = EXEC_REALISTIC_VALUES[(w, opt)]
            variants.append([w, opt, val] + suffix)
            if opt.startswith("-") and not opt.startswith("--") and len(opt) == 2:
                variants.append([w, opt + val] + suffix)  # glued short-flag form
    return variants


def exec_sudo_variants():
    """Real-exec-testable subset of fuzz_argv_canon.sudo_variants() — see module docstring for
    why only the bare word and `-u`/`--user` (pointed at the invoking user) are covered."""
    variants = [[s] for s in sorted(SUDO)]
    if CURRENT_USER:
        for s in sorted(SUDO):
            variants.append([s, "-u", CURRENT_USER])
            variants.append([s, "--user", CURRENT_USER])
    return variants


def run_real(prefix_tokens):
    """Actually exec `prefix_tokens + HELPER_ARGV` via bash and return the helper's observed argv
    (a list), or None if the case is inconclusive: the wrapper binary is missing, it rejected the
    case outright (bad exit code), or it never even invoked the helper (e.g. xargs -I on empty
    stdin) — never treated as a violation, only a genuine argv mismatch is."""
    command = " ".join(shlex.quote(t) for t in prefix_tokens + HELPER_ARGV)
    try:
        r = subprocess.run(
            ["bash", "-c", command],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    try:
        observed = json.loads(r.stdout)
    except Exception:
        return None
    return observed if isinstance(observed, list) else None


def exec_violation(prefix_tokens):
    observed = run_real(prefix_tokens)
    if observed is None:
        return False  # inconclusive — see run_real()
    return observed != strip_prefixes(prefix_tokens + HELPER_ARGV)


def main():
    violations = {}
    checked = 0
    inconclusive = 0

    for prefix_tokens in exec_wrapper_variants() + exec_sudo_variants():
        observed = run_real(prefix_tokens)
        if observed is None:
            inconclusive += 1
            continue
        checked += 1
        predicted = strip_prefixes(prefix_tokens + HELPER_ARGV)
        if observed != predicted:
            minimal = tuple(canon.shrink(prefix_tokens, exec_violation))
            if minimal not in violations:
                real = run_real(list(minimal))
                got = strip_prefixes(list(minimal) + HELPER_ARGV)
                violations[minimal] = (
                    "real-exec invariant: `%s` actually ran with argv %r, but strip_prefixes() "
                    "predicts %r" % (" ".join(list(minimal) + HELPER_ARGV), real, got)
                )

    print(
        f"argv-exec fuzzer: {checked} case(s) checked against real binaries, "
        f"{inconclusive} inconclusive (binary missing or rejected the case)"
    )

    violations = list(violations.values())
    if violations:
        print(f"argv-exec fuzzer: {len(violations)} violation(s) found:", file=sys.stderr)
        for v in violations:
            print(f"  FAIL: {v}", file=sys.stderr)
        return 1

    print("argv-exec fuzzer: no violations found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
