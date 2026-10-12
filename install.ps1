$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. "$PSScriptRoot\scripts\node-path.ps1"
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Creating Python environment failed.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r backend/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
& '.\.venv\Scripts\python.exe' scripts/setup_local.py
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed.' }
Set-Location -LiteralPath "$PSScriptRoot\frontend"
$npmCommand = (Get-Command npm.cmd).Source
$npmCli = Join-Path (Split-Path -Parent $npmCommand) 'node_modules\npm\bin\npm-cli.js'
if (Test-Path -LiteralPath 'package-lock.json') {
    & $selectedNode $npmCli ci --workspaces=false --no-audit --no-fund
} else {
    & $selectedNode $npmCli install --workspaces=false --no-audit --no-fund
}
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
& $selectedNode node_modules/typescript/bin/tsc -p tsconfig.build.json
if ($LASTEXITCODE -ne 0) { throw 'TypeScript check failed.' }
& $selectedNode node_modules/vite/bin/vite.js build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'Installed. Run start.ps1; initial credentials: data/首次登录.txt'

