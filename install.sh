#!/usr/bin/env bash
# Install the VAST agent skills for Claude Code, Cursor, OpenAI Codex and other Agent Skills clients.
#
#   ./install.sh                 link the skill into ~/.agents/skills (Codex, Cursor, others)
#                                and ~/.claude/skills (Claude Code)
#   ./install.sh --project DIR   install into a project instead: DIR/.agents/skills and DIR/.claude/skills
#   ./install.sh --copy          copy instead of symlink (e.g. on Windows, or to pin a version)
#   ./install.sh --uninstall     remove what this script installed
#
# Symlinks (the default) mean `git pull` in this repo updates every agent at once.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode=link
base="$HOME"
uninstall=false
while [ $# -gt 0 ]; do
  case "$1" in
    --project) base="$(cd "$2" && pwd)"; shift 2 ;;
    --copy) mode=copy; shift ;;
    --uninstall) uninstall=true; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

targets=("$base/.agents/skills" "$base/.claude/skills")
# Skill names from the earlier multi-skill layout, removed if this script installed them.
legacy=(vast-api vast-tenants-network vast-views-protocols vast-identity-access vast-data-protection
        vast-monitoring vast-database vast-event-broker vast-dataengine)

for target in "${targets[@]}"; do
  mkdir -p "$target"
  for old in "${legacy[@]}"; do
    dest="$target/$old"
    if [ -L "$dest" ] || [ -f "$dest/.vast-agent-skills" ]; then rm -rf "$dest"; echo "removed old $dest"; fi
  done
  for skill in "$here"/skills/*/; do
    name="$(basename "$skill")"
    dest="$target/$name"
    if $uninstall; then
      if [ -L "$dest" ] || [ -f "$dest/.vast-agent-skills" ]; then rm -rf "$dest"; echo "removed $dest"; fi
      continue
    fi
    if [ -e "$dest" ] && [ ! -L "$dest" ] && [ ! -f "$dest/.vast-agent-skills" ]; then
      echo "skip $dest: exists and was not installed by this script" >&2
      continue
    fi
    rm -rf "$dest"
    if [ "$mode" = link ]; then
      ln -s "${skill%/}" "$dest"
    else
      cp -R "${skill%/}" "$dest"
      touch "$dest/.vast-agent-skills"
    fi
    echo "$mode $name -> $dest"
  done
done

$uninstall || cat <<EOF

Installed. Skills load in new agent sessions (Codex and Cursor usually pick them up live).
The helper needs Python 3.8+. Connect it to a cluster with:
  export VMS_ADDRESS=<vms host> VMS_USER=<user> VMS_PASSWORD=<password>   # or VMS_TOKEN=<api token>
EOF
