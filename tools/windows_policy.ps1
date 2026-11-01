param([ValidateSet('Install','Check','Remove')][string]$Mode = 'Check')
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this command as administrator after institutional approval.'
}
$root = Split-Path -Parent $PSScriptRoot
$sha = [Security.Cryptography.SHA256]::Create()
$tag = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant())))).Replace('-','').Substring(0,12)
if ($Mode -ne 'Remove') {
    $disabled = @(Get-NetFirewallProfile | Where-Object { $_.Enabled -ne $true })
    if ($disabled.Count -gt 0) { throw 'Windows Firewall profiles must be enabled by the institutional administrator.' }
}
foreach ($exe in @('python.exe','pythonw.exe')) {
    $program = Join-Path $root ('runtime\' + $exe)
    if (-not (Test-Path -LiteralPath $program)) { throw "Runtime missing: $exe" }
    foreach ($direction in @('Inbound','Outbound')) {
        $ruleName = "BudgetOfflineWeb-$tag-$exe-$direction"
        if ($Mode -eq 'Remove') {
            Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
            continue
        }
        if ($Mode -eq 'Install' -and -not (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Description 'Local web trial: block non-loopback IP communication for this packaged Python.' -Program $program -Direction $direction -Action Block -Enabled True -Profile Any -Protocol Any -RemoteAddress @('0.0.0.0-126.255.255.255','128.0.0.0-255.255.255.255','::/0') | Out-Null
        }
        $rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $ruleName -ErrorAction Stop
        $filter = $rule | Get-NetFirewallApplicationFilter
        if ($rule.Action -ne 'Block' -or $rule.Enabled -ne 'True' -or $rule.Direction -ne $direction -or $rule.Profile -ne 'Any' -or $filter.Program -ne $program) {
            throw "Firewall block rule not active: $ruleName"
        }
    }
}
Write-Host "BudgetOffline local firewall policy: $Mode completed. Physical isolation is a separate institutional control."
