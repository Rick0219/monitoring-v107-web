# Prefer a recent installed Node; the Codex runtime is an optional local fallback.
$ErrorActionPreference = 'Stop'
$bundledNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$currentNode = (Get-Command node -ErrorAction SilentlyContinue).Source
$selectedNode = $currentNode
if ($currentNode) {
    $nodeVersion = & $currentNode -p 'process.versions.node'
    if ([version]$nodeVersion -lt [version]'20.19.0') { $selectedNode = $null }
}
if (-not $selectedNode -and (Test-Path -LiteralPath $bundledNode)) { $selectedNode = $bundledNode }
if (-not $selectedNode) { throw 'Node.js 20.19+ is required. Install Node.js LTS, then retry.' }
$env:PATH = (Split-Path -Parent $selectedNode) + ';' + $env:PATH

