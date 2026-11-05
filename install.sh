#!/bin/sh
# finance-ai-skills: install skills (not the plugin) into ~/.claude/skills
#                    the korean-law MCP server into ~/.claude/mcp/korean-law
#                    and the tax-source-guard hook into ~/.claude/hooks
# usage (macOS/Linux):  curl -fsSL https://raw.githubusercontent.com/hany202507/finance-ai-skills/main/install.sh | sh
# one group only:       curl -fsSL .../install.sh | sh -s -- audit     (tax, accounting, audit, career)
#                       or FAS_PLUGIN=audit in the environment. The groups are the plugins in .claude-plugin/marketplace.json
set -e
group="${1:-${FAS_PLUGIN:-}}"
case "$group" in
  ""|tax|accounting|audit|career) ;;
  *) echo "unknown group: $group (use tax, accounting, audit or career, or nothing for all skills)"; exit 1 ;;
esac
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mcpdest="${CLAUDE_MCP_DIR:-$HOME/.claude/mcp}/korean-law"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$dest"
curl -fsSL -o "$tmp/main.zip" https://github.com/hany202507/finance-ai-skills/archive/refs/heads/main.zip
unzip -q "$tmp/main.zip" -d "$tmp"
src="$tmp/finance-ai-skills-main"
if [ -z "$group" ]; then
  for d in "$src"/skills/*/; do basename "$d"; done > "$tmp/skills.txt"
else
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found: install Python 3.10+ to pick one group, or run without a group to install all skills"; exit 1
  fi
  python3 -c 'import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
p = [x for x in d["plugins"] if x["name"] == sys.argv[2]][0]
sys.stdout.buffer.write("".join(s.rsplit("/", 1)[1] + "\n" for s in p["skills"]).encode("utf-8"))' \
    "$src/.claude-plugin/marketplace.json" "$group" > "$tmp/skills.txt"
fi
while IFS= read -r name; do
  rm -rf "$dest/$name"
  cp -R "$src/skills/$name" "$dest/$name"
  echo "installed: $dest/$name"
  if [ -f "$dest/$name/requirements.txt" ]; then
    if command -v python3 >/dev/null 2>&1; then
      python3 -m pip install -q -r "$dest/$name/requirements.txt" && echo "python packages: ok"
    else
      echo "python3 not found: install Python 3.10+ and run  pip3 install -r $dest/$name/requirements.txt"
    fi
  fi
done < "$tmp/skills.txt"

# 2026-10-19 the law lookup skill was renamed. Remove its old install folder (exact old name, real folder only;
# a symlink is left alone) so the old skill does not show next to the new one.
# The name is written as UTF-8 bytes to keep this file ASCII.
old="$dest/$(printf '\353\262\225\353\240\271\354\241\260\355\232\214')"
if [ -d "$old" ] && [ ! -L "$old" ]; then
  rm -rf "$old"
  echo "removed: $old"
fi

# the law server, the tax hook and the law server check are for the tax and accounting review skills only
case "$group" in
  audit|career) echo "done. restart Claude Code."; exit 0 ;;
esac

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
  for k in head "taxdoctor-$td" "korean-law-$kl" "oc-$oc" "gomdori-$gl" tail; do
    awk -v k="[$k]" '{ sub(/\r$/, "") } $0 == k { p = 1; next } /^\[[a-z-]+\]$/ { p = 0 } p' "$src/install-check.txt" |
      sed "s|{MCP_INDEX}|$mcpdest/index.js|"
  done
fi
echo "done. restart Claude Code."
