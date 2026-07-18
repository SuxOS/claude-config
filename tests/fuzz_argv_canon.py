#!/usr/bin/env python3
"""Combinatorial property/differential fuzzer over the shared argv-canonicalization logic (#199).

The git history of this repo (see CLAUDE.md) is a long, still-ongoing pattern: `strip_prefixes()`
in `_hookutil.py` gets a bypass fixed one shell-syntax shape at a time (#105, #112, #119, #120,
#121, #131, #136, #144, #158, #179, #193, #196, #198, ...), each a human/agent noticing one
construct wasn't canonicalized and patching that one case. `tests/test_hooks.sh` only covers those
hand-picked shapes, so a NEW gap in an untested combination goes unnoticed until it bites.

This harness generates the combinatorial space of prefixes from an INDEPENDENT reference table
(REFERENCE_WRAPPER_VALUE_FLAGS below), hand-authored from each wrapper's own real documented
flags — deliberately NOT sourced from `_hookutil.WRAPPER_VALUE_OPTS` (the thing under test).
Generating from the production constant instead would make this a tautology: `_hookutil.py`'s own
stdbuf `-o`/`-i`/`-e` gap (#198) omitted those flags from `WRAPPER_VALUE_OPTS`, so a generator
driven by that same dict would never have produced a `stdbuf -o VAL cmd` case to catch it. An
independent, doc-derived table generates the case regardless of whether the implementation's own
bookkeeping agrees — which is exactly how this harness caught a live sibling gap in xargs's
`-n`/`-s`/`-d` (max-args/max-chars/delimiter) while it was being built (fixed alongside #198). The
wrapper WORD list (`WRAPPERS`) and the sudo/doas option set (`SUDO_VALUE_OPTS`) are still reused
from `_hookutil.py` — those two haven't shown this "missing flag" gap pattern historically, and
re-deriving every axis independently wasn't worth the time for this first version (see the scope
note at the end of this docstring).

Two ground-truth invariants:
  1. `strip_prefixes(prefix_tokens + REAL_ARGV) == REAL_ARGV` for every generated prefix — no
     wrapper/flag/env-assign/grouping combination may leave a fragment of itself (a flag value, a
     grouping token, ...) sitting in front of the real command word.
  2. For the subset of prefixes that join into a valid space-separated command string (grouping
     tokens excluded — `(`/`{`/`!` need a matching close to be valid shell, which is a shell-syntax
     concern this harness doesn't model), `block-egress.py`'s `offending()` still flags the
     known-sensitive real command (`curl`) as a bare net binary through that prefix.

On a violation, a simple delta-debugging shrink (repeatedly drop one prefix token at a time while
the invariant stays violated) reduces the failure to a minimal reproducing case before reporting it
— the same "give a minimal repro" property Hypothesis's shrinker provides.

Deliberately out of scope for this first version (real follow-up, not silently dropped): quoting
styles, command/process substitution, and wrapper STACKING beyond one sudo/doas layer + one
wrapper layer — each is a genuinely separate generator axis and would need its own invariant care
(e.g. `pieces()`'s substitution-recursion, not `strip_prefixes()` alone). This version's coverage
is still strictly larger than the hand-picked fixture corpus it supplements, not a replacement for
it. Exit 0 = no violation found; exit 1 = at least one, each printed with its minimal repro.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.join(HERE, "..", "home", ".claude", "hooks")
sys.path.insert(0, HOOKS_DIR)

from _hookutil import (  # noqa: E402
    LEADING_NOISE,
    SUDO,
    SUDO_VALUE_OPTS,
    WRAPPERS,
    strip_prefixes,
)


def _load_block_egress():
    """block-egress.py has a `-` in its filename, so it can't be `import`ed by name."""
    path = os.path.join(HOOKS_DIR, "block-egress.py")
    spec = importlib.util.spec_from_file_location("block_egress_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BLOCK_EGRESS = _load_block_egress()

REAL_ARGV = ["curl", "http://example.invalid/health"]
PLACEHOLDER_VALUE = "VAL"

# Ground truth from each wrapper's own docs/man page — see the module docstring for why this is
# kept independent of `_hookutil.WRAPPER_VALUE_OPTS` rather than imported from it. Wrappers with no
# value-consuming flags (time, nohup, command, builtin) are simply absent; `.get(w, ())` covers
# them, and `env`'s own value-ish forms (`-i`, inline `VAR=VAL`) are handled by WRAPPER_EXTRA_SUFFIXES
# below since they're not a plain "flag consumes the next bare token" shape.
REFERENCE_WRAPPER_VALUE_FLAGS = {
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "stdbuf": {"-i", "-o", "-e"},
    "xargs": {"-I", "-L", "-P", "-n", "-s", "-d"},
    "exec": {"-a"},
}

# Hand-declared shapes for the branches in strip_prefixes() that aren't expressible purely as a
# "flag consumes the next bare token" rule: timeout's mandatory bare DURATION positional, and env's
# run of inline `VAR=VAL` assignments (plus its unrelated `-i` boolean) after the wrapper word.
WRAPPER_EXTRA_SUFFIXES = {
    "timeout": [["5"], ["-s", "KILL", "5"], ["-sKILL", "5"]],
    "env": [["-i"], ["FOO=bar"], ["FOO=bar", "BAZ=qux"], ["-i", "FOO=bar"]],
}


def wrapper_variants():
    """Every prefix shape `strip_prefixes()` claims to strip through a WRAPPERS word. The wrapper
    WORD list comes from `_hookutil.WRAPPERS`; the value-consuming FLAGS come from the independent
    reference table above, not from `_hookutil.WRAPPER_VALUE_OPTS` (see module docstring)."""
    variants = []
    for w in sorted(WRAPPERS):
        variants.append([w])
        for opt in sorted(REFERENCE_WRAPPER_VALUE_FLAGS.get(w, ())):
            variants.append([w, opt, PLACEHOLDER_VALUE])  # separate-value form
            if opt.startswith("-") and not opt.startswith("--") and len(opt) == 2:
                variants.append([w, opt + PLACEHOLDER_VALUE])  # glued short-flag form
        for suffix in WRAPPER_EXTRA_SUFFIXES.get(w, []):
            variants.append([w] + suffix)
    return variants


def sudo_variants():
    variants = [[s] for s in sorted(SUDO)]
    for s in sorted(SUDO):
        for opt in sorted(SUDO_VALUE_OPTS):
            variants.append([s, opt, PLACEHOLDER_VALUE])
    return variants


GROUPING_PREFIXES = [[]] + [[tok] for tok in sorted(LEADING_NOISE)]
ENV_PREFIXES = [[], ["FOO=bar"], ["A=1", "B=2"]]


def generate_prefixes():
    """Yield (prefix_tokens, joinable) for every combination this harness covers. `joinable` is
    False for prefixes containing a grouping token (invariant 2 is skipped for those — see
    module docstring)."""
    priv_or_wrapper = [[]] + sudo_variants() + wrapper_variants()
    for grouping in GROUPING_PREFIXES:
        for env in ENV_PREFIXES:
            for prefix in priv_or_wrapper:
                tokens = grouping + env + prefix
                yield tokens, not grouping

    # Stacked prefixes (sudo/doas THEN a wrapper) get their own, smaller cross product — combining
    # decisions found separately can still miss the interaction (#193 was exactly this class).
    for sudo_pfx in sudo_variants():
        for wrap_pfx in wrapper_variants():
            yield sudo_pfx + wrap_pfx, True


def strip_prefixes_violation(prefix_tokens):
    return strip_prefixes(prefix_tokens + REAL_ARGV) != REAL_ARGV


def offending_violation(prefix_tokens):
    command = " ".join(prefix_tokens + REAL_ARGV)
    return not BLOCK_EGRESS.offending(command)


def shrink(prefix_tokens, violates):
    """Delta-debugging-lite: repeatedly drop one token while the invariant stays violated."""
    tokens = list(prefix_tokens)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(tokens):
            trial = tokens[:i] + tokens[i + 1:]
            if violates(trial):
                tokens = trial
                changed = True
            else:
                i += 1
    return tokens


def main():
    # Keyed on the SHRUNK minimal repro, not the raw generated prefix — many different generated
    # prefixes (e.g. every stdbuf MODE variant) can shrink to the same minimal failing case, and
    # deduping pre-shrink just prints that same minimal repro once per generated variant instead
    # of once total.
    violations = {}

    for prefix_tokens, joinable in generate_prefixes():
        if strip_prefixes_violation(prefix_tokens):
            minimal = tuple(shrink(prefix_tokens, strip_prefixes_violation))
            if ("strip", minimal) not in violations:
                got = strip_prefixes(list(minimal) + REAL_ARGV)
                violations[("strip", minimal)] = (
                    "strip_prefixes() invariant: prefix %r + %r should recover %r, got %r"
                    % (list(minimal), REAL_ARGV, REAL_ARGV, got)
                )

        if joinable and offending_violation(prefix_tokens):
            minimal = tuple(shrink(prefix_tokens, offending_violation))
            if ("offending", minimal) not in violations:
                violations[("offending", minimal)] = (
                    "block-egress offending() invariant: %r should flag %r as a bare net binary, "
                    "but offending() returned None" % (list(minimal), REAL_ARGV)
                )

    violations = list(violations.values())
    if violations:
        print(f"argv-canonicalization fuzzer: {len(violations)} violation(s) found:", file=sys.stderr)
        for v in violations:
            print(f"  FAIL: {v}", file=sys.stderr)
        return 1

    print("argv-canonicalization fuzzer: no violations found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
