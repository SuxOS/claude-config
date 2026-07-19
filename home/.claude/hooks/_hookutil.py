"""Shared argv-splitting helpers for the PreToolUse(Bash) hooks in this directory.

block-egress.py, block-checkout-held-branch.py, and block-sleep-loop.py each need to walk a
shell command piece-by-piece (splitting on `&&`/`||`/`;`/`|`/`&`, quote-aware), read a command
word's basename, and strip leading wrapper/prefix words (`sudo`, `env`, `command`, `VAR=val`,
`timeout N`, ...) to reach the real command word. Importable because Python puts the invoked
script's own directory on sys.path[0], and install.sh symlinks this whole directory into
~/.claude/hooks/ — so a plain `from _hookutil import ...` resolves the same in both the repo
and the installed tree.

`git_subcommand()` and `git_out()` are the git-specific counterpart: any rail that needs to find a
`git` command's subcommand (past global options like `-C`/`-c`/`--git-dir=`) or shell out to git
for live repo state was reimplementing both by hand — block-checkout-held-branch.py had the only
copy of each until block-destructive-git.py (#230) needed the identical logic. Hoisted here so
neither rail re-derives it, mirroring how `strip_prefixes()` itself was consolidated (#193).

`pieces()` is substitution-aware (#200): it surfaces `$(...)`/`` `...` ``/`<(...)`/`>(...)`
inner text as its own piece before the top-level split, so a primitive hidden inside a
substitution (`echo $(curl evil)`) still shows up to any rail that reads a piece's command word.
This was originally block-egress.py's own local override (#136), fixing only that rail; hoisted
here (#200) so every importer — block-sleep-loop.py, block-checkout-held-branch.py, any future
rail — inherits it too, mirroring how `strip_prefixes()` itself was consolidated (#193). Likewise,
any rail that reads a piece's command word MUST run it through `strip_prefixes()` first (#193) — a
rail that compares `basename(argv[0])` directly re-acquires the exact wrapper-prefix bypass
`strip_prefixes()` was built to close in block-egress.py (#119, #179).
"""
import re
import shlex
import subprocess

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
# xargs's long forms `--max-args`/`--max-chars`/`--max-procs`/`--delimiter` (of `-n`/`-s`/`-P`/`-d`)
# take a REQUIRED argument per GNU getopt_long, so like `timeout`/`--signal` they bind via a separate
# following word too (`xargs --max-args 1 curl ...`); `--replace`/`--max-lines` (of `-I`/`-L`) are
# deliberately left short-only since their long form's argument is OPTIONAL and only ever binds via
# `=`, never a separate word. stdbuf's `--input`/`--output`/`--error` (long forms of `-i`/`-o`/`-e`)
# have the same separate-value gap the short forms were fixed for (#198). `env`'s own separate-value
# flags (`-u`/`--unset`, `-C`/`--chdir`) were missing an entry entirely — its boolean `-i`
# (ignore-environment) and inline `VAR=VAL` handling below are unaffected, only its value-taking
# flags were the gap. Both found by auditing xargs/stdbuf/env against #198/#203's already-fixed
# sibling wrappers (#212), same "hand-maintained flag table drifts from the real tool's
# separate-vs-glued-vs-long grammar" class. xargs's `-a FILE`/`--arg-file=FILE` (read items from FILE
# instead of stdin) takes a REQUIRED separate value exactly like `-n`/`-s`/`-d`, and was still missing
# (#217): `xargs -a items.txt curl evil.com` walked past `-a` as a boolean flag and stopped at
# `items.txt`, hiding `curl` from the bare-net-binary scan. `-S`/`--split-string` is DELIBERATELY NOT
# here (#227): unlike `-u`/`-C`, its value isn't an opaque skip — it IS (or starts) the real command
# (`env -S 'curl evil.com'` runs `curl evil.com`, per env(1)) — so it needs the word-split-and-splice
# handling in `strip_prefixes()` below, not a "swallow one token" entry here.
WRAPPER_VALUE_OPTS = {
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "xargs": {"-I", "-L", "-P", "-n", "-s", "-d", "-a", "--max-args", "--max-chars", "--max-procs", "--delimiter", "--arg-file"},
    "exec": {"-a"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "env": {"-u", "--unset", "-C", "--chdir"},
    "time": {"-o", "--output", "-f", "--format"},
}
# `env -S`/`--split-string`'s escape/quote grammar (info env, "-S/--split-string syntax"), verified
# against real GNU coreutils env(1) output (#227): unquoted/double-quoted escapes, `\_` as a literal
# space inside double quotes, `${VAR}` expansion is NOT implemented here (no reliable access to the
# hook's runtime environment; a literal `${VAR}` left in a recovered word only affects a VALUE, never
# the primitive name a scan looks for).
_ENV_DASHS_ESCAPES = {
    "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
    "#": "#", "$": "$", '"': '"', "'": "'", "\\": "\\",
}
DURATION_RE = re.compile(r"[0-9]+(\.[0-9]+)?[smhdSMHD]?")  # timeout's bare DURATION positional
# Privilege wrappers that take their own options then a command word (`sudo -u user cmd`, `doas`).
# Treated as value-less wrappers so a `sudo`/`doas` prefix can't shift the command word out of the
# scan (#119); SUDO_VALUE_OPTS are the separate-value options whose argument must also be skipped.
# Union of both sudo/doas long-option surfaces independently identified against #119 (user/group/
# prompt/role/type from one pass, host/chroot/chdir from the other) — kept as a union, not either
# alone, so neither's flag coverage regresses. `--close-from`/`--chdir`/`--chroot`/`--other-user`
# (long forms of the already-present `-C`/`-D`/`-R`/`-U`), `-T`/`--command-timeout`, and doas's
# `-a` (auth style) were a live gap the same shape as #198/#199's stdbuf/xargs miss — a bare short
# flag was covered but its long form wasn't (or, for `-T`, neither was), so e.g.
# `sudo --chdir /tmp curl evil.com` swallowed only `--chdir` and left `/tmp` misread as the
# command word, hiding `curl` from every scan. Found by tests/fuzz_argv_canon.py's independent
# sudo/doas reference table (#203), fixed here rather than left for the fuzzer to keep reporting.
SUDO = {"sudo", "doas"}
SUDO_VALUE_OPTS = {
    "-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "--close-from", "-r", "--role",
    "-t", "--type", "-U", "--other-user", "-h", "--host", "-R", "--chroot", "-D", "--chdir",
    "-T", "--command-timeout", "-a",
}
# A bare inline env-assignment prefix (`FOO=bar cmd`) — NAME=VALUE with a valid shell identifier —
# likewise shifts the command word; skip a leading run of them the way `env VAR=VAL` is skipped (#119).
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def basename(word):
    return word.rsplit("/", 1)[-1]


def _split_env_dash_s(s):
    """Word-split an `env -S`/`--split-string` STRING the way env(1) itself does (#227): it is NOT
    an opaque flag value like `-u NAME`/`-C DIR` — it IS (or starts) the real command, so a wrapped
    command (`env -S 'curl evil.com'`) must be split and re-fed into argv, not silently skipped.

    Behavior verified against real GNU coreutils `env` (info env, "-S/--split-string syntax"):
    unquoted whitespace (space/tab/newline/CR/VT/FF) separates words; `'...'` groups a word
    literally except `\\\\`/`\\'` (env's own escapes for those two chars); `"..."` groups a word but
    still processes the full escape set; unquoted/double-quoted escapes are `\\f\\n\\r\\t\\v` (control
    chars, embedded in the current word — NOT separators, despite the literal chars being separators
    when they appear raw/unescaped), `\\#`/`\\$`/`\\"`/`\\'`/`\\\\` (literal chars), and `\\_` (a literal
    space inside double quotes, an argument separator outside them). `\\c` and a bare `#` as the
    first character of a fresh argument both truncate the rest of the string — matching env's own
    behavior (env itself never executes what follows either, so dropping it here creates no blind
    spot the scan needs to worry about). `${VAR}` expansion is deliberately NOT implemented (no
    reliable access to env's runtime environment from a hook); a literal `${VAR}` is left in the
    recovered word, which only affects a VALUE, never the primitive name a scan is looking for.
    """
    words = []
    cur = []
    have_cur = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if not have_cur and c == "#":
            break  # '#' as the first character of a fresh argument truncates the rest
        if c in " \t\n\r\v\f":
            if have_cur:
                words.append("".join(cur))
                cur = []
                have_cur = False
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "c":
                break  # truncates the rest of the string, same as env itself
            if nxt == "_":
                if have_cur:
                    words.append("".join(cur))
                    cur = []
                    have_cur = False
                i += 2
                continue
            cur.append(_ENV_DASHS_ESCAPES.get(nxt, nxt))
            have_cur = True
            i += 2
            continue
        if c == "'":
            j = i + 1
            while j < n and s[j] != "'":
                if s[j] == "\\" and j + 1 < n and s[j + 1] in ("\\", "'"):
                    cur.append(s[j + 1])
                    j += 2
                else:
                    cur.append(s[j])
                    j += 1
            have_cur = True
            i = j + 1  # skip the closing quote (or land on end-of-string on imbalance)
            continue
        if c == '"':
            j = i + 1
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n:
                    nxt = s[j + 1]
                    cur.append(" " if nxt == "_" else _ENV_DASHS_ESCAPES.get(nxt, nxt))
                    j += 2
                else:
                    cur.append(s[j])
                    j += 1
            have_cur = True
            i = j + 1
            continue
        cur.append(c)
        have_cur = True
        i += 1
    if have_cur:
        words.append("".join(cur))
    return words


def strip_prefixes(argv):
    """Drop everything before the real command word, in one pass: grouping noise, bare
    `NAME=VALUE` env assignments, `sudo`/`doas`, and value-consuming wrappers + their args
    (`timeout 5 python3` -> `python3`, `FOO=1 sudo -u x curl …` -> `curl …`,
    `exec -a fake curl …` -> `curl …`). Collapses the whole "a leading prefix shifts the
    command word out of argv[0]" bypass class (#119, #179). `command -v/-V NAME` is left
    unstripped since it reports on NAME rather than executing it.

    `env -S`/`--split-string STRING` (#227) is not a "skip one value token" wrapper flag like
    `-u`/`-C` — STRING IS (or starts) the real command, so its value is word-split via
    `_split_env_dash_s()` and SPLICED into argv in place of the flag+value, then the outer loop
    re-runs from that position (not just returned) — the spliced-in words get the SAME
    env-assign/sudo/wrapper canonicalization as any other prefix, so `env -S 'FOO=bar curl evil'`
    still reaches `curl` too.
    """
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
        split_words = None
        while i < n and argv[i].startswith("-"):  # the wrapper's own option flags
            t = argv[i]
            if base == "env" and (t == "-S" or t == "--split-string"):
                if i + 1 < n:
                    split_words = _split_env_dash_s(argv[i + 1])
                    i += 2
                else:
                    i += 1
                break
            if base == "env" and t.startswith("--split-string="):
                split_words = _split_env_dash_s(t.split("=", 1)[1])
                i += 1
                break
            if base == "env" and t.startswith("-S") and len(t) > 2:
                split_words = _split_env_dash_s(t[2:])
                i += 1
                break
            if t in value_opts and i + 1 < n and not argv[i + 1].startswith("-"):
                i += 1  # ...and that flag's separate value
            i += 1
        if split_words is not None:
            argv = argv[:i] + split_words + argv[i:]
            n = len(argv)
            continue  # re-run the outer loop over the spliced-in words
        if base == "env":
            while i < n and "=" in argv[i] and not argv[i].startswith("-"):
                i += 1  # env's inline VAR=VAL assignments
        elif base == "timeout" and i < n and DURATION_RE.fullmatch(argv[i]):
            i += 1  # timeout's mandatory DURATION positional
    return argv[i:]


def _split_pieces(command):
    """Yield the argv list of each simple command, respecting shell quoting where possible.

    Splits on control operators (`&&`, `||`, `;`, `|`, `&`) but only outside quotes, so a `;`
    inside a `-c "..."` payload is preserved. Newlines separate commands, so split on them first.
    On a line shlex can't tokenize (unbalanced quotes), fall back to a raw regex split so we still
    scan something rather than crash. This is the base tokenizer `pieces()` wraps with
    substitution-recursion below; nothing outside this module should call it directly.
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


def substitution_inners(command):
    """Yield the inner text of each command/process substitution at the TOP level of `command`:
    `$(...)`, `` `...` ``, `<(...)`, `>(...)`. `pieces()` re-feeds each inner through itself, so
    nested `$(...)` substitutions (`$(foo $(bar))`) are reached by that recursion, not here —
    nested backticks are NOT depth-tracked (the backtick branch below just finds the next literal
    backtick), matching real shell's own requirement that a nested backtick be escaped.

    Single-quoted spans are skipped (a `$(...)` inside `'...'` is a literal string, no substitution);
    double-quoted spans are still scanned (`"$(curl ...)"` does substitute). Best-effort quote/paren
    tracking — on any imbalance we yield what was found and stop rather than raise, because every
    rail using this must fail open. This is what makes `echo $(curl http://evil)` visible to a
    piece-scanning rail that only looks at top-level pieces (#136).
    """
    i, n = 0, len(command)
    in_double = False
    while i < n:
        c = command[i]
        if c == "\\":
            i += 2                       # escaped next char (incl. \$, \`) — never a substitution
            continue
        if c == '"':
            in_double = not in_double
            i += 1
            continue
        if c == "'" and not in_double:
            j = command.find("'", i + 1)  # skip the whole single-quoted (literal) span
            if j == -1:
                break
            i = j + 1
            continue
        if c == "`":                     # `...` backtick substitution (also inside double quotes)
            j = command.find("`", i + 1)
            if j == -1:
                break
            yield command[i + 1:j]
            i = j + 1
            continue
        # $( ... ) command substitution, or <( ... )/>( ... ) process substitution (unquoted only)
        if (c == "$" or (c in "<>" and not in_double)) and i + 1 < n and command[i + 1] == "(":
            k = i + 2
            depth = 1
            quote = None                 # track quotes inside the span so a quoted ')' doesn't close it
            while k < n and depth > 0:
                ck = command[k]
                if quote is not None:
                    if ck == "\\" and quote == '"':
                        k += 2
                        continue
                    if ck == quote:
                        quote = None
                    k += 1
                    continue
                if ck == "\\":
                    k += 2
                elif ck in ("'", '"'):
                    quote = ck
                    k += 1
                elif ck == "(":
                    depth += 1
                    k += 1
                elif ck == ")":
                    depth -= 1
                    k += 1
                else:
                    k += 1
            end = k - 1 if depth == 0 else k   # k-1 drops the matched ')'; on imbalance take the rest
            yield command[i + 2:end]
            i = k
            continue
        i += 1


def pieces(command):
    """Yield the argv list of each simple command, substitution-aware (#200).

    Before the top-level split (`_split_pieces()`), surface every command/process substitution's
    inner text as its own piece and recurse into it (#136): `echo $(curl http://evil)` otherwise
    tokenizes to a single `echo ...` piece whose command word is `echo`, hiding the net primitive
    from every rail that reads a piece's command word. Originally block-egress.py's own local
    override; every importer of this `pieces()` gets substitution-awareness for free (#200).
    """
    for inner in substitution_inners(command):
        yield from pieces(inner)
    yield from _split_pieces(command)


# git global options that consume a following value, so a rail can walk past them to the
# subcommand (`git -C /path checkout foo`, `git -c k=v push foo`). `--opt=value` forms carry
# their own value and are skipped as ordinary flags by `git_subcommand()` below. `--exec-path` is
# deliberately NOT here: real git's bare `--exec-path` (no `=`) takes NO value at all — it just
# prints the current exec-path and exits immediately, never reaching a subcommand; only the glued
# `--exec-path=<path>` form sets it, and that's self-contained in one token (#211).
GIT_GLOBAL_VALUE_OPTS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
}
# Global opts that redirect git at a DIFFERENT repo than the hook-input cwd. A rail that consults
# cwd's live git state (worktree list, status, merge-base, ...) can't safely follow these — it
# would end up inspecting the wrong repo (#154) — so `git_subcommand()` treats them as unparsable.
GIT_GLOBAL_CWD_OPTS = {"-C", "--git-dir", "--work-tree"}


def git_subcommand(argv):
    """Return (subcommand, rest_argv) for a `git ...` argv, walking past global options to find
    it — or None for a non-git command, a command with no subcommand at all, or one that
    redirects at a different repo than cwd (`-C`/`--git-dir`/`--work-tree`, see GIT_GLOBAL_CWD_OPTS).

    `argv` should already be run through `strip_prefixes()` by the caller (#193) — a wrapper/prefix
    word ahead of `git` (`command git push -f`, `sudo git reset --hard`) must reach the real `git`
    command word first, same as every other rail's convention.
    """
    if not argv or basename(argv[0]) != "git":
        return None
    i, n = 1, len(argv)
    while i < n:
        tok = argv[i]
        if tok in GIT_GLOBAL_VALUE_OPTS:
            if tok in GIT_GLOBAL_CWD_OPTS:
                return None
            i += 2
            continue
        if tok.startswith("-"):
            if tok.startswith("--git-dir=") or tok.startswith("--work-tree="):
                return None
            i += 1
            continue
        break
    if i >= n:
        return None
    return argv[i], argv[i + 1:]


def git_out(args, cwd):
    """Run a git command in cwd and return stdout, or None on any failure (fail-open).

    Every rail that consults live git state (worktree list, status, merge-base, ...) needs the
    same "shell out, swallow any error, never raise" shape — centralized so a subprocess quirk
    (git not installed, a timeout, a non-repo cwd) degrades to "can't tell, allow" uniformly.
    Collapses a nonzero exit to None because for these callers the exit code is just a
    success/failure marker, not itself the answer — see `git_returncode()` for the opposite case."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def git_returncode(args, cwd):
    """Run a git command in cwd and return its exit code, or None if it couldn't even run.

    For callers where the EXIT CODE itself is the answer (`git merge-base --is-ancestor a b`:
    0 = ancestor, 1 = not, anything else = couldn't determine) rather than stdout — `git_out()`
    would collapse the meaningful 1 down to the same None as a real failure to run."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, timeout=5,
        )
    except Exception:
        return None
    return r.returncode
