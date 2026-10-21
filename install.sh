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

# 2026-10-19 the law lookup skill was renamed. Remove its old install folder (exact old name, real folder only;
# a symlink is left alone) so the old skill does not show next to the new one.
# The name is written as UTF-8 bytes to keep this file ASCII.
old="$dest/$(printf '\353\262\225\353\240\271\354\241\260\355\232\214')"
if [ -d "$old" ] && [ ! -L "$old" ]; then
  rm -rf "$old"
  echo "removed: $old"
fi

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
# law server check (same text and rules as install.ps1): korean-law and its LAW_OC from ~/.claude.json,
# TaxDoctor and the law search connector only when added from the terminal (app connectors print as "check")
if [ -f "$src/install-check.txt" ]; then
  cfg="$HOME/.claude.json"
  [ -f "$cfg" ] || cfg=/dev/null
  kl=missing; oc=missing; td=check; gl=check
  if grep -q '"korean-law"[[:space:]]*:[[:space:]]*{' "$cfg"; then
    kl=ok
    if grep -A12 '"korean-law"[[:space:]]*:[[:space:]]*{' "$cfg" | grep -q '"LAW_OC"[[:space:]]*:[[:space:]]*"[^"<][^"<]*"'; then oc=ok; fi
  fi
  if [ -n "${LAW_OC:-}" ]; then oc=ok; fi
  if grep -q 'taxdoctorai\.com' "$cfg"; then td=ok; fi
  if grep -q 'mcp\.gomdori\.app' "$cfg"; then gl=ok; fi
  for k in head "korean-law-$kl" "oc-$oc" "taxdoctor-$td" "gomdori-$gl" tail; do
    awk -v k="[$k]" '{ sub(/\r$/, "") } $0 == k { p = 1; next } /^\[[a-z-]+\]$/ { p = 0 } p' "$src/install-check.txt" |
      sed "s|{MCP_INDEX}|$mcpdest/index.js|"
  done
fi
echo "done. restart Claude Code."
