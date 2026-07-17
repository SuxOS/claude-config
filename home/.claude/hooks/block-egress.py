#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) — raise the egress speed bump the security stream points at.

Under `defaultMode: bypassPermissions` only `permissions.deny` enforces, and per-binary denies
CANNOT be a real network-egress boundary while `python3`/`node`/`npx` stay on the allow list
(see docs/security-model.md and settings.README.md — the interpreters open sockets themselves,
so denying `curl`/`wget` proves nothing). This hook inspects the Bash command's argv BEFORE it
runs and blocks the two OBVIOUS, common egress forms those docs name that no deny rule can catch:

  1. INTERPRETER / SHELL inline-code egress one-liners — the argument to an interpreter's
     inline-eval flag (`python3 -c 'import urllib.request; ...'`, `node -e 'fetch(...)'`,
     `ruby/perl -e`, `php -r`, `bash -c '... curl ...'`) scanned for a named outbound primitive;
  2. `gh api` WRITES in any argv position — `gh api /repos/O/R -X DELETE` slips past the prefix
     deny because the write flag follows the URL (security-model.md:28); parsing argv sees the
     method wherever it sits, and flags gh's implicit-POST field flags too.

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
import shlex
import sys

# Shell control operators that separate simple commands. We split a line into pieces at these so
# `foo && python3 -c '...'` is inspected piece-by-piece — but only OUTSIDE quotes (a `;` inside a
# `-c "..."` payload must stay put), which is why splitting is done on shlex tokens, not the raw
# string. PUNCT drives shlex's quote-aware tokenizer; OPERATOR_RE recognises the operator tokens.
PUNCT = ";|&<>()"
OPERATOR_RE = re.compile(r"^[;|&]+$")
# Fallback splitter used only when shlex can't tokenize a line (unbalanced quotes) — best effort.
SPLIT_RE = re.compile(r"&&|\|\||[;|&]")
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
SUDO_WRAPPERS = {"sudo", "doas"}
SUDO_VALUE_OPTS = {"-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "-r", "--role", "-t", "--type", "-U"}
# A bare inline env-assignment prefix (`FOO=bar cmd`) — NAME=VALUE with a valid shell identifier —
# likewise shifts the command word; skip a leading run of them the way `env VAR=VAL` is skipped (#119).
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Per-interpreter inline-code flags. Only the flags that actually take *code* — `-c` is code for
# python/shell but a syntax check for node/ruby/perl, so it is NOT listed for those; `-p` prints
# code for node but is a loop wrapper for perl. Getting this per-family right avoids blocking an
# innocent `perl -n file.log`. perl/ruby also bundle the eval flag (`-pe`, `-ne`) — handled below.
INLINE_FLAGS = {
    "python": {"-c"}, "python2": {"-c"}, "python3": {"-c"},
    "node": {"-e", "--eval", "-p", "--print"}, "nodejs": {"-e", "--eval", "-p", "--print"},
    "bun": {"-e", "--eval", "-p", "--print"}, "deno": {"-e", "--eval"},
    "ruby": {"-e"}, "perl": {"-e", "-E"}, "php": {"-r"},
    "bash": {"-c"}, "sh": {"-c"}, "zsh": {"-c"}, "dash": {"-c"},
}
INTERPRETERS = set(INLINE_FLAGS)
PERL_BUNDLE_RE = re.compile(r"-[A-Za-z]*[eE]")  # perl/ruby `-pe`, `-ne`, `-nE`, ... (bundle ends in e/E)
# Versioned interpreter basenames (`python3.11`, `python2.7`, `perl5.36`, `ruby3.0`) are a normal,
# non-obfuscated invocation form present on most distros, but they miss the exact-basename
# INTERPRETERS lookup. VERSION_SUFFIX_RE strips a trailing `X` or `X.Y[.Z]` version so the family
# key can be recovered — else `python3.11 -c '...urllib...'` slips past the inline scan. (#112)
VERSION_SUFFIX_RE = re.compile(r"^([a-z]+)(\d+)(?:\.\d+)*$")

# Named outbound primitives across python / node / ruby / perl / php / shell. A match inside an
# inline-code payload means "this one-liner reaches the network" — the exfil/fetch the docs name.
NET_RE = re.compile(
    r"""
      urllib | urlopen | \brequests\b | httpx | urllib3 | http\.client | httplib
    | smtplib | ftplib | telnetlib | poplib | imaplib | paramiko
    | socket\.socket | socket\.create_connection | create_connection | asyncio\.open_connection
    | \bfetch\s*\( | XMLHttpRequest | axios | node-fetch | \bgot\s*\(
    | require\(\s*['"`](?:node:)?(?:http|https|net|tls|dgram)['"`]\s*\)
    | \bhttps?\.(?:get|request)\s*\( | \bnet\.(?:connect|createConnection)\s*\(
    | \btls\.connect\s*\( | Deno\.connect\s*\(
    | Net::HTTP | IO::Socket | \bLWP\b | HTTP::Tiny | HTTP::Request
    | fsockopen | stream_socket_client | curl_exec | curl_init
    | (?:file_get_contents|fopen)\s*\(\s*['"]https?:// | \bURI\.open\b | \bopen\s*\(\s*['"]https?://
    | \bcurl\b | \bwget\b | \bncat\b | \btelnet\b | /dev/tcp/
    """,
    re.VERBOSE,
)

# `gh api` write signals: an explicit mutating method, or gh's implicit-POST field/body flags.
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FIELD_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}


def basename(word):
    return word.rsplit("/", 1)[-1]


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


def strip_wrappers(argv):
    """Drop leading wrapper words + their args (`timeout 5 python3` -> `python3`), like CC does.

    Also skips a leading run of bare `NAME=VALUE` env assignments (`FOO=bar cmd`) and treats
    `sudo`/`doas` as value-less wrappers (consuming their own options, e.g. `-u user`), so an
    env-assignment or privilege prefix can't shift the real command word out of view (#119).
    """
    i, n = 0, len(argv)
    while i < n:
        tok = argv[i]
        if tok in LEADING_NOISE:
            i += 1
            continue
        if ENV_ASSIGN_RE.match(tok):
            i += 1  # bare inline env assignment: `FOO=bar cmd`
            continue
        base = basename(tok)
        if base in SUDO_WRAPPERS:
            i += 1
            while i < n and argv[i].startswith("-"):  # sudo/doas own options, e.g. `-u user`, `-E`
                if argv[i] in SUDO_VALUE_OPTS and i + 1 < n and not argv[i + 1].startswith("-"):
                    i += 1  # ...and that option's separate value
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
    """Yield the inline-code strings this interpreter argv runs (separate-arg and glued forms)."""
    flags = INLINE_FLAGS.get(cmd, set())
    perl_ruby = cmd in ("perl", "ruby")
    if cmd == "deno" and len(argv) >= 3 and argv[1] == "eval":
        yield " ".join(argv[2:])  # `deno eval CODE...`
    for j in range(1, len(argv)):
        tok = argv[j]
        head = tok.split("=", 1)[0]
        if tok in flags or (perl_ruby and PERL_BUNDLE_RE.fullmatch(tok)):
            if j + 1 < len(argv):
                yield argv[j + 1]
        elif "=" in tok and head in flags:
            yield tok.split("=", 1)[1]  # `--eval=CODE`
        else:
            # Glued single-dash bundle: the inline-flag letter may lead the bundle (`-c'code'` ->
            # token `-ccode`) OR sit mid-bundle behind value-less short opts (`-Ic'code'` -> token
            # `-Icimport...`). Split at the FIRST inline-flag letter and treat the remainder as the
            # code payload — the mid-bundle form otherwise slipped the scan entirely (#105/#120).
            letters = {f[1] for f in flags if len(f) == 2}
            if letters and tok.startswith("-") and not tok.startswith("--"):
                for k in range(1, len(tok)):
                    if tok[k] in letters:
                        if k + 1 < len(tok):
                            yield tok[k + 1:]
                        break


def gh_api_is_write(argv):
    """True if this `gh api ...` argv mutates state (explicit method or implicit-POST fields)."""
    method = None
    for j, tok in enumerate(argv):
        if tok in ("-X", "--method"):
            if j + 1 < len(argv):
                method = argv[j + 1].upper()
        elif tok.startswith("-X") and len(tok) > 2:
            method = tok[2:].upper()
        elif tok.startswith("--method="):
            method = tok.split("=", 1)[1].upper()
        elif tok in FIELD_FLAGS or tok.split("=", 1)[0] in FIELD_FLAGS:
            if method is None:
                method = "POST"  # gh defaults to POST when any field/body flag is present
        elif tok.startswith(("-f", "-F")) and len(tok) > 2:
            if method is None:
                method = "POST"  # glued short field flag: `-ftitle=x`, `-Fkey=@file` (mirror -X) (#121)
    return method in WRITE_METHODS


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


def offending(command):
    """Return a human reason string if any command piece is a blocked egress form, else None."""
    for argv in pieces(command):
        argv = strip_wrappers(argv)
        if not argv:
            continue
        cmd = canonical_interpreter(basename(argv[0]))

        if cmd in INTERPRETERS:
            for payload in inline_payloads(cmd, argv):
                if NET_RE.search(payload):
                    return (
                        f"an inline `{cmd}` one-liner that opens a network connection "
                        f"(matched an outbound primitive in its inline-code payload)"
                    )

        if cmd == "gh" and len(argv) >= 2 and argv[1] == "api" and gh_api_is_write(argv):
            return "a `gh api` call with a write method (POST/PUT/PATCH/DELETE or an implicit-POST field flag)"

    return None


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
        reason = offending(command)
    except Exception:
        sys.exit(0)  # never wedge the session on a hook bug

    if not reason:
        sys.exit(0)

    print(
        "Egress speed bump (PreToolUse): this Bash command was blocked because it looks like "
        f"{reason}. Direct network egress from an interpreter or a `gh api` write is not an "
        "approved path here (docs/security-model.md). If you need to fetch a URL use WebFetch/"
        "WebSearch; for GitHub reads use the read-only `gh` subcommands or a `gh api ... GET`. "
        "If this is a legitimate non-egress command that tripped a substring match, restructure "
        "it so the flagged token isn't present.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
