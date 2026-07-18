"""Shared argv-splitting helpers for the PreToolUse(Bash) hooks in this directory.

block-egress.py, block-checkout-held-branch.py, and block-sleep-loop.py each need to walk a
shell command piece-by-piece (splitting on `&&`/`||`/`;`/`|`/`&`, quote-aware), read a command
word's basename, and strip leading wrapper/prefix words (`sudo`, `env`, `command`, `VAR=val`,
`timeout N`, ...) to reach the real command word. Importable because Python puts the invoked
script's own directory on sys.path[0], and install.sh symlinks this whole directory into
~/.claude/hooks/ — so a plain `from _hookutil import ...` resolves the same in both the repo
and the installed tree.

Hooks with extra requirements (block-egress's substitution-expansion) wrap `pieces()` rather
than reimplementing it — see block-egress.py's own `pieces()`. Likewise, any rail that reads a
piece's command word MUST run it through `strip_prefixes()` first (#193) — a rail that compares
`basename(argv[0])` directly re-acquires the exact wrapper-prefix bypass `strip_prefixes()` was
built to close in block-egress.py (#119, #179).
"""
import re
import shlex

# Shell control operators that separate simple commands. Splitting is done on shlex tokens
# (not the raw string) so a `;` inside a quoted payload (`-c "..."`) stays put. PUNCT drives
# shlex's quote-aware tokenizer; OPERATOR_RE recognises the operator tokens it produces.
PUNCT = ";|&<>()"
OPERATOR_RE = re.compile(r"^[;|&]+$")
# Fallback splitter used only when shlex can't tokenize a line (unbalanced quotes) — best effort.
SPLIT_RE = re.compile(r"&&|\|\||[;|&]")

# Leading tokens that merely group/subshell a command; skip them to reach the real command word.
LEADING_NOISE = {"(", "{", "!"}

# Leading wrappers stripped before reading the real command word. Superset of the set Claude Code
# strips (timeout/time/nice/nohup/stdbuf/xargs) plus `env`, a common interpreter-indirection form,
# and the shell builtins `command`/`exec`/`builtin` — the same "shift the command word out of
# argv[0]" shape (#179): `command curl evil.com` / `exec curl evil.com` reach the network exactly
# like a bare `curl evil.com` would, so they must land on the same real command word.
WRAPPERS = {"timeout", "time", "nice", "nohup", "stdbuf", "xargs", "env", "command", "exec", "builtin"}
# Wrapper option flags that consume a following value (so `timeout -s KILL 5 cmd` reaches `cmd`,
# and `exec -a name cmd` reaches `cmd` rather than stopping on the -a argv[0]-name value). Keyed
# per-wrapper (base name), NOT a single flat set, because the same flag letter means something
# different across wrappers: stdbuf's `-i`/`-o`/`-e` MODE flags take a separate value in their
# non-glued form (`stdbuf -o L cmd`, as opposed to the glued `-oL0` form) (#198), but `env -i` is
# an unrelated boolean flag (start with an empty environment) that must NOT swallow the next word
# (`env -i FOO=bar cmd`) — a shared global set can't hold both without one regressing the other.
# xargs's `-n`/`-s`/`-d` (max-args/max-chars/delimiter) had the same separate-value gap as stdbuf's
# (`xargs -n 5 curl ...` leaked the "5" in front of `curl`) — found by tests/fuzz_argv_canon.py
# (#199) generating the case independently of this dict while it was being built for #198.
WRAPPER_VALUE_OPTS = {
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "xargs": {"-I", "-L", "-P", "-n", "-s", "-d"},
    "exec": {"-a"},
    "stdbuf": {"-i", "-o", "-e"},
}
DURATION_RE = re.compile(r"[0-9]+(\.[0-9]+)?[smhdSMHD]?")  # timeout's bare DURATION positional
# Privilege wrappers that take their own options then a command word (`sudo -u user cmd`, `doas`).
# Treated as value-less wrappers so a `sudo`/`doas` prefix can't shift the command word out of the
# scan (#119); SUDO_VALUE_OPTS are the separate-value options whose argument must also be skipped.
# Union of both sudo/doas long-option surfaces independently identified against #119 (user/group/
# prompt/role/type from one pass, host/chroot/chdir from the other) — kept as a union, not either
# alone, so neither's flag coverage regresses.
SUDO = {"sudo", "doas"}
SUDO_VALUE_OPTS = {
    "-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "-r", "--role", "-t", "--type",
    "-U", "-h", "--host", "-R", "-D",
}
# A bare inline env-assignment prefix (`FOO=bar cmd`) — NAME=VALUE with a valid shell identifier —
# likewise shifts the command word; skip a leading run of them the way `env VAR=VAL` is skipped (#119).
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def basename(word):
    return word.rsplit("/", 1)[-1]


def strip_prefixes(argv):
    """Drop everything before the real command word, in one pass: grouping noise, bare
    `NAME=VALUE` env assignments, `sudo`/`doas`, and value-consuming wrappers + their args
    (`timeout 5 python3` -> `python3`, `FOO=1 sudo -u x curl …` -> `curl …`,
    `exec -a fake curl …` -> `curl …`). Collapses the whole "a leading prefix shifts the
    command word out of argv[0]" bypass class (#119, #179). `command -v/-V NAME` is left
    unstripped since it reports on NAME rather than executing it."""
    i, n = 0, len(argv)
    while i < n:
        tok = argv[i]
        if tok in LEADING_NOISE:
            i += 1
            continue
        if not tok.startswith("-") and ENV_ASSIGN_RE.match(tok):
            i += 1  # a bare VAR=VAL assignment sitting before the command word
            continue
        base = basename(tok)
        if base in SUDO:
            i += 1
            while i < n and argv[i].startswith("-"):  # sudo/doas own option flags
                if argv[i] in SUDO_VALUE_OPTS and i + 1 < n and not argv[i + 1].startswith("-"):
                    i += 1  # ...and that flag's separate value
                i += 1
            continue
        if base not in WRAPPERS:
            break
        if base == "command" and i + 1 < n and argv[i + 1] in ("-v", "-V"):
            break  # `command -v/-V NAME` reports NAME's path/type, it never executes it
        i += 1
        value_opts = WRAPPER_VALUE_OPTS.get(base, set())
        while i < n and argv[i].startswith("-"):  # the wrapper's own option flags
            if argv[i] in value_opts and i + 1 < n and not argv[i + 1].startswith("-"):
                i += 1  # ...and that flag's separate value
            i += 1
        if base == "env":
            while i < n and "=" in argv[i] and not argv[i].startswith("-"):
                i += 1  # env's inline VAR=VAL assignments
        elif base == "timeout" and i < n and DURATION_RE.fullmatch(argv[i]):
            i += 1  # timeout's mandatory DURATION positional
    return argv[i:]


def pieces(command):
    """Yield the argv list of each simple command, respecting shell quoting where possible.

    Splits on control operators (`&&`, `||`, `;`, `|`, `&`) but only outside quotes, so a `;`
    inside a `-c "..."` payload is preserved. Newlines separate commands, so split on them first.
    On a line shlex can't tokenize (unbalanced quotes), fall back to a raw regex split so we still
    scan something rather than crash.
    """
    for line in command.split("\n"):
        if not line.strip():
            continue
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=PUNCT)
            lex.whitespace_split = True
            toks = list(lex)
        except ValueError:
            for raw in SPLIT_RE.split(line):
                if raw.strip():
                    yield raw.split()
            continue
        argv = []
        for tok in toks:
            if OPERATOR_RE.match(tok):
                if argv:
                    yield argv
                argv = []
            else:
                argv.append(tok)
        if argv:
            yield argv
