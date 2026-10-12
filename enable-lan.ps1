param([ValidateRange(1024,65534)][int]$Port = 8007)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Right-click enable-lan.cmd and choose Run as administrator. No firewall changes were made.'
}
$webPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runtimePath = (& $webPython -c 'import sys; print(sys._base_executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) { throw 'Python runtime not found.' }
$runtimePath = (Resolve-Path -LiteralPath $runtimePath).Path
$instance = (& $webPython -c 'import sys; sys.path.insert(0,"backend"); from app.runtime_identity import INSTANCE; print(INSTANCE)' 2>$null)
if ($LASTEXITCODE -ne 0) { throw 'Run this script from the V1.07-Web folder.' }
$ruleName = "MonitoringWeb-V107-LAN-$instance-$Port"
$backupPath = Join-Path $PSScriptRoot "data\lan-firewall-backup-$Port.json"
$changes = @()
foreach ($rule in (Get-NetFirewallRule -Direction Inbound -Enabled True -Action Block)) {
    $program = ($rule | Get-NetFirewallApplicationFilter).Program
    if ($program -ine $runtimePath) { continue }
    $ports = $rule | Get-NetFirewallPortFilter
    if ([string]$ports.Protocol -notin @('TCP','6')) { continue }
    if ([string]$ports.LocalPort -eq 'Any') {
        $changes += [pscustomobject]@{ Name=$rule.Name; LocalPort=@($ports.LocalPort) }
    }
}
# Preserve the original rules for review before making narrowly scoped changes.
if ($changes.Count -and -not (Test-Path -LiteralPath $backupPath)) {
    [pscustomobject]@{ Program=$runtimePath; Port=$Port; RuleName=$ruleName; OriginalRules=$changes } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $backupPath -Encoding UTF8
}
$existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    if (($existing | Get-NetFirewallApplicationFilter).Program -ine $runtimePath) { throw 'Existing rule belongs to another program.' }
    Set-NetFirewallRule -Name $ruleName -Enabled True -Action Allow -Direction Inbound -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Profile Any | Out-Null
} else {
    New-NetFirewallRule -Name $ruleName -DisplayName "Monitoring Web V1.07 LAN TCP $Port" -Direction Inbound -Action Allow -Enabled True -Program $runtimePath -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Profile Any | Out-Null
}
# An explicit Block wins over an Allow. Keep the existing Python TCP blocks on
# every other port, excluding only this web port. UDP rules are untouched.
foreach ($change in $changes) {
    Set-NetFirewallRule -Name $change.Name -Protocol TCP -LocalPort @("1-$($Port-1)", "$($Port+1)-65535") | Out-Null
}
Write-Host "Enabled LAN access for TCP $Port, this Python runtime, LocalSubnet only."
Write-Host 'Other Python ports and UDP rules are unchanged. Start start.cmd, then scan the chart QR code.'
Write-Host "Original rule details (when changed): $backupPath"
