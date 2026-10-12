param([ValidateRange(1024,65535)][int]$Port = 8007, [switch]$NoBrowser, [switch]$Lan)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe') -or -not (Test-Path -LiteralPath 'backend\app\frontend\index.html')) {
    throw 'Run install.ps1 first.'
}
& '.\.venv\Scripts\python.exe' scripts/setup_local.py
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed.' }
$launcherArguments = @('scripts/launch.py', '--port', $Port)
if ($NoBrowser) { $launcherArguments += '--no-browser' }
if ($Lan) { $launcherArguments += @('--host', '0.0.0.0') }
& "$PSScriptRoot\.venv\Scripts\python.exe" @launcherArguments
exit $LASTEXITCODE
