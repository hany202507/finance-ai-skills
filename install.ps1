# finance-ai-skills: install skills (not the plugin) into ~/.claude/skills
#                    and the korean-law MCP server into ~/.claude/mcp/korean-law
# usage (PowerShell):  irm https://raw.githubusercontent.com/hany202507/finance-ai-skills/main/install.ps1 | iex
$ErrorActionPreference = 'Stop'
$repo = 'hany202507/finance-ai-skills'
$dest = if ($env:CLAUDE_SKILLS_DIR) { $env:CLAUDE_SKILLS_DIR } else { Join-Path $HOME '.claude\skills' }
$mcpRoot = if ($env:CLAUDE_MCP_DIR) { $env:CLAUDE_MCP_DIR } else { Join-Path $HOME '.claude\mcp' }
$mcpDest = Join-Path $mcpRoot 'korean-law'
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('fas-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp, $dest, $mcpRoot | Out-Null
try {
    $zip = Join-Path $tmp 'main.zip'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$repo/archive/refs/heads/main.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $root = Join-Path $tmp 'finance-ai-skills-main'
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
    foreach ($d in Get-ChildItem -Directory (Join-Path $root 'skills')) {
        $target = Join-Path $dest $d.Name
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Copy-Item -Recurse $d.FullName $target
        Write-Host "installed: $target"
        $req = Join-Path $target 'requirements.txt'
        if (Test-Path $req) {
            if ($py) {
                & $py.Source -m pip install -q -r $req
                Write-Host "python packages: ok"
            } else {
                Write-Host "python not found: install Python 3.10+ and run  pip install -r $req"
            }
        }
    }

    # korean-law MCP (used by the tax and accounting review skills)
    if (Test-Path $mcpDest) { Remove-Item -Recurse -Force $mcpDest }
    Copy-Item -Recurse (Join-Path $root 'mcp\korean-law') $mcpDest
    Write-Host "installed: $mcpDest"
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) {
        Push-Location $mcpDest
        try { & $npm.Source install --omit=dev --silent } finally { Pop-Location }
        Write-Host "node packages: ok"
        Write-Host ""
        Write-Host "register once with your own law.go.kr OPEN API OC (https://open.law.go.kr):"
        Write-Host "  claude mcp add -s user korean-law -e LAW_OC=<YOUR_OC> -- node `"$mcpDest\index.js`""
    } else {
        Write-Host "node not found: install Node.js 18+ and run  npm install  in $mcpDest"
    }
    Write-Host "done. restart Claude Code."
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
