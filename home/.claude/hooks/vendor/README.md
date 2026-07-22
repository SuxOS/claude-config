# vendor/

Third-party code vendored (not pip-installed) because `install.sh` symlinks
`home/.claude/hooks/` straight into `~/.claude/hooks/` with no dependency-install step
(`install.sh:1-91`) and this directory otherwise has zero third-party dependencies.

- **`bashlex/`** — [bashlex](https://github.com/idank/bashlex) 0.18, a pure-Python port of
  bash's own parser. Vendored unmodified from the PyPI sdist (`pip download bashlex==0.18
  --no-deps --no-binary :all:`); upstream license kept at `bashlex/LICENSE`. Note: upstream is
  GPLv3+ (`License: GPLv3+` in its PKG-INFO), not MIT as originally assumed when this vendoring
  was scoped (#388) — worth knowing before any future decision to redistribute this repo rather
  than use it as a private config tree.
  First step of a 3-step migration (#206/#280/#388) to replace the hand-rolled shlex+regex argv
  approximation in `_hookutil.py` with a real shell-grammar parser; no rail uses it yet.
