# finance-ai-skills: install skills (not the plugin) into ~/.claude/skills
#                    the korean-law MCP server into ~/.claude/mcp/korean-law
#                    and the tax-source-guard hook into ~/.claude/hooks
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
    } else {
        Write-Host "node not found: install Node.js 18+ and run  npm install  in $mcpDest"
    }
    # tax-source-guard hook (used with the tax advisory skill)
    $hookRoot = if ($env:CLAUDE_HOOKS_DIR) { $env:CLAUDE_HOOKS_DIR } else { Join-Path $HOME '.claude\hooks' }
    New-Item -ItemType Directory -Force -Path $hookRoot | Out-Null
    $hookDest = Join-Path $hookRoot 'tax-source-guard.mjs'
    Copy-Item -Force (Join-Path $root 'hooks\tax-source-guard.mjs') $hookDest
    Write-Host "installed: $hookDest"
    Write-Host "register the hook once in ~/.claude/settings.json (UserPromptSubmit). see README: tax hook"
    # setup guide for the law lookup skills. The text lives in install-guide.txt (UTF-8) so this
    # script stays ASCII: Windows PowerShell 5.1 reads BOM-less UTF-8 .ps1 files as the ANSI code page
    $guide = Join-Path $root 'install-guide.txt'
    if (Test-Path $guide) {
        $text = [IO.File]::ReadAllText($guide, [Text.Encoding]::UTF8)
        Write-Host $text.Replace('{MCP_INDEX}', (Join-Path $mcpDest 'index.js'))
    }
    # law server check: korean-law (local MCP) and its LAW_OC are read from ~/.claude.json. TaxDoctor and the law
    # search connector are found there only when added from the terminal; Claude app connectors live in the account,
    # so they are printed as "check". The text lives in install-check.txt (UTF-8), one [section] per state
    $check = Join-Path $root 'install-check.txt'
    if (Test-Path $check) {
        $sec = @{}
        $cur = $null
        foreach ($line in [IO.File]::ReadAllLines($check, [Text.Encoding]::UTF8)) {
            if ($line -match '^\[([a-z-]+)\]$') { $cur = $Matches[1]; $sec[$cur] = New-Object Collections.Generic.List[string]; continue }
            if ($cur) { $sec[$cur].Add($line) }
        }
        $cfg = ''
        $cfgPath = Join-Path $HOME '.claude.json'
        if (Test-Path $cfgPath) { $cfg = [IO.File]::ReadAllText($cfgPath, [Text.Encoding]::UTF8) }
        $kl = [regex]::Match($cfg, '"korean-law"\s*:\s*\{')
        $oc = [bool]$env:LAW_OC
        if ($kl.Success) {
            $block = $cfg.Substring($kl.Index, [Math]::Min(600, $cfg.Length - $kl.Index))
            if ([regex]::IsMatch($block, '"LAW_OC"\s*:\s*"[^"<]+"')) { $oc = $true }
        }
        $keys = @('head',
            $(if ($kl.Success) { 'korean-law-ok' } else { 'korean-law-missing' }),
            $(if ($oc) { 'oc-ok' } else { 'oc-missing' }),
            $(if ($cfg -match 'taxdoctorai\.com') { 'taxdoctor-ok' } else { 'taxdoctor-check' }),
            $(if ($cfg -match 'mcp\.gomdori\.app') { 'gomdori-ok' } else { 'gomdori-check' }),
            'tail')
        $index = Join-Path $mcpDest 'index.js'
        foreach ($k in $keys) {
            if ($sec.ContainsKey($k)) { foreach ($l in $sec[$k]) { Write-Host $l.Replace('{MCP_INDEX}', $index) } }
        }
    }
    Write-Host "done. restart Claude Code."
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
