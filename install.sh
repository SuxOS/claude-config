#!/usr/bin/env bash
# Symlinks this repo's tracked config into ~/.claude. Idempotent.
# On conflict with a pre-existing non-symlink, backs it up (*.bak-<epoch>) then links.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/home/.claude"
DEST="$HOME/.claude"

mkdir -p "$DEST"

items=(CLAUDE.md)
shopt -s dotglob
for entry in "$SRC"/*; do
  name="$(basename "$entry")"
  case "$name" in
    settings.json) continue ;;
    CLAUDE.md) continue ;;
  esac
  items+=("$name")
done
shopt -u dotglob

missing=()
for item in "${items[@]}"; do
  src="$SRC/$item"
  dest="$DEST/$item"
  if [ ! -e "$src" ]; then
    echo "skipping $item — not found at $src" >&2
    missing+=("$item")
    continue
  fi
  if [ -L "$dest" ]; then
    current="$(readlink "$dest")"
    if [ "$current" = "$src" ]; then
      echo "ok: $dest already -> $src"
      continue
    fi
    echo "repointing symlink $dest (was -> $current)" >&2
    rm "$dest"
  elif [ -e "$dest" ]; then
    backup="$dest.bak-$(date +%s)"
    echo "backing up existing $dest -> $backup" >&2
    mv "$dest" "$backup"
  fi
  ln -s "$src" "$dest"
  echo "linked: $dest -> $src"
done

# A missing source (renamed/moved file, bad merge, sparse checkout) is a hard failure —
# never exit 0 having silently skipped CLAUDE.md or any other tracked config.
if [ "${#missing[@]}" -gt 0 ]; then
  printf 'ERROR: source files not found, nothing linked for: %s\n' "${missing[*]}" >&2
  echo "Repo checkout looks incomplete — re-check out $SRC and re-run." >&2
  exit 1
fi

# settings.json is copied, not symlinked (Claude Code rewrites it in place).
settings_src="$SRC/settings.json"
settings_dest="$DEST/settings.json"
if [ -e "$settings_dest" ]; then
  echo
  echo "settings.json already exists at $settings_dest — not overwritten."
  echo "Reference copy at $settings_src — diff/merge manually as needed."
  if command -v jq >/dev/null 2>&1; then
    missing_deny="$(jq -n --slurpfile src "$settings_src" --slurpfile dest "$settings_dest" \
      '(($src[0].permissions.deny // []) - ($dest[0].permissions.deny // [])) | .[]' 2>/dev/null || true)"
    missing_hooks="$(jq -n --slurpfile src "$settings_src" --slurpfile dest "$settings_dest" \
      '(($src[0].hooks // {}) | [.. | objects | .command? // empty]) as $src_cmds |
       (($dest[0].hooks // {}) | [.. | objects | .command? // empty]) as $dest_cmds |
       ($src_cmds - $dest_cmds) | .[]' 2>/dev/null || true)"
    if [ -n "$missing_deny" ] || [ -n "$missing_hooks" ]; then
      echo
      echo "Your settings.json is missing security updates from the repo reference:"
      if [ -n "$missing_deny" ]; then
        while IFS= read -r rule; do
          echo "  missing permissions.deny rule: $rule"
        done <<< "$missing_deny"
      fi
      if [ -n "$missing_hooks" ]; then
        while IFS= read -r cmd; do
          echo "  missing hook command: $cmd"
        done <<< "$missing_hooks"
      fi
      echo "Merge these by hand from $settings_src."
    fi
  fi
elif [ -e "$settings_src" ]; then
  cp -n "$settings_src" "$settings_dest"
  echo
  echo "copied: $settings_dest (from reference $settings_src)"
  echo "settings.json is copied, not symlinked — Claude Code rewrites it in place."
fi
