# Run on Windows in a LOCAL Can_ids checkout after committing your changes.
# Updates only to the exact local commit that is present on origin/main.
param([Parameter(Mandatory=$true)][string]$PiHost)
$ErrorActionPreference = 'Stop'
if ($PiHost -notmatch '^[a-zA-Z0-9_.@:-]+$' -or $PiHost.StartsWith('-')) {
    throw 'Use user@hostname (or user@IPv4).'
}
$taskRepo = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskRepo
try {
    $taskDirty = git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $taskDirty) { throw 'Commit or stash local changes first.' }
    git fetch origin main
    if ($LASTEXITCODE -ne 0) { throw 'Fetch failed.' }
    $taskCommit = git rev-parse HEAD
    $taskRemote = git rev-parse origin/main
    if ($taskCommit -ne $taskRemote) { throw 'Push your intended commit to origin/main first.' }
    ssh $PiHost "cd ~/Can_ids && bash scripts/update.sh $taskCommit"
    if ($LASTEXITCODE -ne 0) { throw 'Pi update failed; read the remote output.' }
} finally { Pop-Location }
