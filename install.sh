#!/bin/sh
# finance-ai-skills: install skills (not the plugin) into ~/.claude/skills
#                    the korean-law MCP server into ~/.claude/mcp/korean-law
#                    and the tax-source-guard hook into ~/.claude/hooks
# usage (macOS/Linux):  curl -fsSL https://raw.githubusercontent.com/hany202507/finance-ai-skills/main/install.sh | sh
set -e
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mcpdest="${CLAUDE_MCP_DIR:-$HOME/.claude/mcp}/korean-law"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$dest"
curl -fsSL -o "$tmp/main.zip" https://github.com/hany202507/finance-ai-skills/archive/refs/heads/main.zip
unzip -q "$tmp/main.zip" -d "$tmp"
src="$tmp/finance-ai-skills-main"
for d in "$src"/skills/*/; do
  name="$(basename "$d")"
  rm -rf "$dest/$name"
  cp -R "$d" "$dest/$name"
  echo "installed: $dest/$name"
  if [ -f "$dest/$name/requirements.txt" ]; then
    if command -v python3 >/dev/null 2>&1; then
      python3 -m pip install -q -r "$dest/$name/requirements.txt" && echo "python packages: ok"
    else
      echo "python3 not found: install Python 3.10+ and run  pip3 install -r $dest/$name/requirements.txt"
    fi
  fi
done

# korean-law MCP (used by the tax and accounting review skills)
rm -rf "$mcpdest"
mkdir -p "$(dirname "$mcpdest")"
cp -R "$src/mcp/korean-law" "$mcpdest"
echo "installed: $mcpdest"
if command -v npm >/dev/null 2>&1; then
  (cd "$mcpdest" && npm install --omit=dev --silent) && echo "node packages: ok"
else
  echo "node not found: install Node.js 18+ and run  npm install  in $mcpdest"
fi
# tax-source-guard hook (used with the tax advisory skill)
hookdest="${CLAUDE_HOOKS_DIR:-$HOME/.claude/hooks}"
mkdir -p "$hookdest"
cp "$src/hooks/tax-source-guard.mjs" "$hookdest/tax-source-guard.mjs"
echo "installed: $hookdest/tax-source-guard.mjs"
echo "register the hook once in ~/.claude/settings.json (UserPromptSubmit). see README: tax hook"
# setup guide for the law lookup skills (same text as install.ps1 prints)
if [ -f "$src/install-guide.txt" ]; then
  sed "s|{MCP_INDEX}|$mcpdest/index.js|" "$src/install-guide.txt"
fi
echo "done. restart Claude Code."
