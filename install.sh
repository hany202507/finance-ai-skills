#!/bin/sh
# finance-ai-skills: install skills (not the plugin) into ~/.claude/skills
# usage (macOS/Linux):  curl -fsSL https://raw.githubusercontent.com/hany202507/finance-ai-skills/main/install.sh | sh
set -e
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$dest"
curl -fsSL -o "$tmp/main.zip" https://github.com/hany202507/finance-ai-skills/archive/refs/heads/main.zip
unzip -q "$tmp/main.zip" -d "$tmp"
for d in "$tmp"/finance-ai-skills-main/skills/*/; do
  name="$(basename "$d")"
  rm -rf "$dest/$name"
  cp -R "$d" "$dest/$name"
  echo "installed: $dest/$name"
  if command -v python3 >/dev/null 2>&1 && [ -f "$dest/$name/requirements.txt" ]; then
    python3 -m pip install -q -r "$dest/$name/requirements.txt" && echo "python packages: ok"
  else
    echo "python3 not found: install Python 3.10+ and run  pip3 install pandas openpyxl"
  fi
done
echo "done. restart Claude Code."
