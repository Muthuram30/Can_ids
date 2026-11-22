# Optional PowerShell wrapper for the direct SSH runner. No GitHub push needed.
param(
    [string]$PiHost,
    [string]$Target,
    [switch]$Watch,
    [switch]$Adopt,
    [switch]$CodeOnly
)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskArgs = @()
if ($PiHost) { $taskArgs += @('--host', $PiHost) }
if ($Target) { $taskArgs += @('--target', $Target) }
if ($Watch) { $taskArgs += '--watch' }
if ($Adopt) { $taskArgs += '--adopt' }
if ($CodeOnly) { $taskArgs += '--code-only' }
& (Join-Path $taskRepo 'run_pi.cmd') @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'Pi sync failed; read the runner output.' }
