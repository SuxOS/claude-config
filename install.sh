#!/usr/bin/env bash
# Symlinks this repo's tracked config into ~/.claude. Idempotent.
# On conflict with a pre-existing non-symlink, backs it up (*.bak-<epoch>) then links.
# --apply/--merge: when an existing settings.json is missing deny rules or hook commands
# present in the repo reference, patch them in (backing up first) instead of only printing.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/home/.claude"
# Two-account model: the human identity (m@) installs into ~/.claude; the bot identity (claude@)
# installs into ~/.claude-bot, selected either with --bot or by pointing CLAUDE_CONFIG_DIR at a
# *-bot directory. CLAUDE_CONFIG_DIR relocates the whole ~/.claude tree for a Claude Code CLI run
# (the desktop app does NOT honor it — the bot is CLI-only). See home/.claude/BOT-ACCOUNT.md.
DEST="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

apply_merge=false
bot=false
for arg in "$@"; do
  case "$arg" in
    --apply|--merge) apply_merge=true ;;
    --bot) bot=true ;;
  esac
done
# Auto-detect the bot identity from the destination dir name, so
# `CLAUDE_CONFIG_DIR=~/.claude-bot ./install.sh` needs no extra flag.
case "$(basename "$DEST")" in
  *-bot) bot=true ;;
esac
# Same locked-down guards (deny + hooks) either way — the bot just uses a leaner, headless
# plugin/notification set (settings.bot.json). See home/.claude/BOT-ACCOUNT.md.
if [ "$bot" = true ]; then
  settings_name="settings.bot.json"
  echo "installing BOT identity config into $DEST (settings variant: $settings_name)" >&2
else
  settings_name="settings.json"
fi

mkdir -p "$DEST"

items=(CLAUDE.md)
shopt -s dotglob
for entry in "$SRC"/*; do
  name="$(basename "$entry")"
  case "$name" in
    settings.json|settings.bot.json) continue ;;
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

# settings.json is copied, not symlinked (Claude Code rewrites it in place). The source is the
# identity's variant (settings.json for human, settings.bot.json for the bot); the destination is
# always named settings.json because that's the only filename Claude Code reads.
settings_src="$SRC/$settings_name"
settings_dest="$DEST/settings.json"
if [ -e "$settings_dest" ]; then
  echo
  echo "settings.json already exists at $settings_dest — not overwritten."
  echo "Reference copy at $settings_src — diff/merge manually as needed."
  if command -v jq >/dev/null 2>&1; then
    missing_deny="$(jq -rn --slurpfile src "$settings_src" --slurpfile dest "$settings_dest" \
      '(($src[0].permissions.deny // []) - ($dest[0].permissions.deny // [])) | .[]' 2>/dev/null || true)"
    missing_hooks="$(jq -rn --slurpfile src "$settings_src" --slurpfile dest "$settings_dest" \
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
      if [ "$apply_merge" = true ]; then
        backup="$settings_dest.bak-$(date +%s)"
        cp "$settings_dest" "$backup"
        # Union permissions.deny (append what's missing, keep everything already there —
        # including rules the user added that aren't in the repo reference) and, for hooks,
        # match on the (event, matcher) pair: append a missing hook command into an existing
        # matcher's hooks array, or append the whole matcher group when the event has no
        # matching matcher yet. Never drops a dest-only entry, so re-running is a no-op.
        jq -n --slurpfile src "$settings_src" --slurpfile dest "$settings_dest" '
          def merge_group($destEvent; $group):
            ($destEvent | map(.matcher)) as $matchers
            | ($matchers | index($group.matcher)) as $idx
            | if $idx == null then
                $destEvent + [$group]
              else
                $destEvent | .[$idx].hooks = (
                  (.[$idx].hooks // []) as $dh
                  | reduce ($group.hooks[]) as $h ($dh;
                      if any(.[]; .type == $h.type and .command == $h.command) then .
                      else . + [$h] end)
                )
              end;
          def merge_event($src; $dest; $event):
            ($dest[$event] // []) as $destEvent
            | reduce ($src[$event][]) as $group ($destEvent; merge_group(.; $group));
          def merge_hooks($src; $dest):
            reduce ($src | keys_unsorted[]) as $event ($dest;
              .[$event] = merge_event($src; $dest; $event)
            );
          ($dest[0].permissions.deny // []) as $existingDeny
          | $dest[0]
          | .permissions.deny = ($existingDeny + (($src[0].permissions.deny // []) - $existingDeny))
          | .hooks = merge_hooks($src[0].hooks // {}; $dest[0].hooks // {})
        ' > "$settings_dest.tmp"
        mv "$settings_dest.tmp" "$settings_dest"
        echo "Applied missing security updates to $settings_dest (backup: $backup)."
      else
        echo "Merge these by hand from $settings_src, or re-run with --apply to merge them in automatically."
      fi
    fi
  fi
elif [ -e "$settings_src" ]; then
  cp -n "$settings_src" "$settings_dest"
  echo
  echo "copied: $settings_dest (from reference $settings_src)"
  echo "settings.json is copied, not symlinked — Claude Code rewrites it in place."
else
  # Same hard-failure invariant as the missing=() check above: a missing source must never
  # be a silent no-op, even for settings.json's separately-handled copy-not-symlink path.
  printf 'ERROR: source files not found, nothing linked for: %s\n' "settings.json" >&2
  echo "Repo checkout looks incomplete — re-check out $SRC and re-run." >&2
  exit 1
fi
