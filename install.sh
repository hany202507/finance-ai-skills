#!/bin/sh
# finance-ai-skills: install skills (not the plugin) into ~/.claude/skills
#                    and the korean-law MCP server into ~/.claude/mcp/korean-law
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
  echo ""
  echo "register once with your own law.go.kr OPEN API OC (https://open.law.go.kr):"
  echo "  claude mcp add -s user korean-law -e LAW_OC=<YOUR_OC> -- node \"$mcpdest/index.js\""
else
  echo "node not found: install Node.js 18+ and run  npm install  in $mcpdest"
fi
echo "done. restart Claude Code."
