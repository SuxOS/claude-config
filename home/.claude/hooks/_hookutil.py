"""Shared argv-splitting helpers for the PreToolUse(Bash) hooks in this directory.

block-egress.py and block-checkout-held-branch.py each need to walk a shell command
piece-by-piece (splitting on `&&`/`||`/`;`/`|`/`&`, quote-aware) and read a command word's
basename. Importable because Python puts the invoked script's own directory on sys.path[0],
and install.sh symlinks this whole directory into ~/.claude/hooks/ — so a plain `from
_hookutil import ...` resolves the same in both the repo and the installed tree.

Hooks with extra requirements (block-egress's substitution-expansion) wrap `pieces()` rather
than reimplementing it — see block-egress.py's own `pieces()`.
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


def basename(word):
    return word.rsplit("/", 1)[-1]


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
