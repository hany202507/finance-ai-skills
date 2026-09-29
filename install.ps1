# finance-ai-skills: install skills (not the plugin) into ~/.claude/skills
# usage (PowerShell):  irm https://raw.githubusercontent.com/hany202507/finance-ai-skills/main/install.ps1 | iex
$ErrorActionPreference = 'Stop'
$repo = 'hany202507/finance-ai-skills'
$dest = if ($env:CLAUDE_SKILLS_DIR) { $env:CLAUDE_SKILLS_DIR } else { Join-Path $HOME '.claude\skills' }
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('fas-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp, $dest | Out-Null
try {
    $zip = Join-Path $tmp 'main.zip'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$repo/archive/refs/heads/main.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $src = Join-Path $tmp 'finance-ai-skills-main\skills'
    foreach ($d in Get-ChildItem -Directory $src) {
        $target = Join-Path $dest $d.Name
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Copy-Item -Recurse $d.FullName $target
        Write-Host "installed: $target"
        $req = Join-Path $target 'requirements.txt'
        $py = Get-Command python -ErrorAction SilentlyContinue
        if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
        if ($py -and (Test-Path $req)) {
            & $py.Source -m pip install -q -r $req
            Write-Host "python packages: ok"
        } elseif (-not $py) {
            Write-Host "python not found: install Python 3.10+ and run  pip install pandas openpyxl"
        }
    }
    Write-Host "done. restart Claude Code."
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
