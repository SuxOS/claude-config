#!/usr/bin/env bash
# Symlinks this repo's tracked config into ~/.claude. Idempotent.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/home/.claude"
DEST="$HOME/.claude"

mkdir -p "$DEST"

for item in CLAUDE.md skills commands; do
  src="$SRC/$item"
  dest="$DEST/$item"
  if [ -L "$dest" ]; then
    rm "$dest"
  elif [ -e "$dest" ]; then
    echo "refusing to overwrite non-symlink $dest — move it aside first" >&2
    exit 1
  fi
  ln -s "$src" "$dest"
  echo "linked: $dest -> $src"
done

echo
echo "settings.json is NOT symlinked (Claude Code rewrites it in place)."
echo "Reference copy at $SRC/settings.json — diff/merge manually as needed."
