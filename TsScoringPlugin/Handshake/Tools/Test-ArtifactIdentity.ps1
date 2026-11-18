# The Global Close identity check of the formal TelemetryA (OD-X11 v2, Owner 2026-11-15). ASCII-only on purpose; Windows PowerShell 5.1. Read-only: it changes nothing.
#
#   .\Test-ArtifactIdentity.ps1 -Dll <the promoted candidate DLL> -Deployed <the installed DLL> -RemoteRef origin/main [-Ledger <json>] [-Since 'yyyy-MM-dd HH:mm'] [-RollbackDll <asset>] [-OwnerApproval <id>]
#
# A Global Close of the formal TelemetryA PASSES only when ALL of these hold (each is printed as PASS / FAIL):
#   1  ACCEPTED SHA = DEPLOYED SHA = PROMOTED SHA   (ledger entries build -> accept -> deploy of the candidate, the installed file, the candidate)
#   2  ACCEPTED / DEPLOYED / PROMOTED CAPABILITIES are identical (the ledger entries, the installed DLL and the candidate DLL, read from the DLLs themselves)
#   3  the candidate is a formal Jump ON build (artifact_guard promote check ACCEPT: metadata = compiled-in flag = sidecar, BuildRole Formal, source commit on the remote)
#   4  no capability of the previous baseline is lost (unless an Owner approval id is given and recorded)
#   5  no BVE / python / observer process is left; no new WER / CrashDump of BveTs.exe or python since -Since
#   6  the rollback asset (if given) is registered with SHA and capability, and its rollback loses no capability without approval
# Exit code 0 = every check PASS, 1 = at least one FAIL.
param(
    [Parameter(Mandatory = $true)][string]$Dll,
    [Parameter(Mandatory = $true)][string]$Deployed,
    [string]$Ledger = '',
    [string]$RemoteRef = 'origin/main',
    [string]$Since = '',
    [string]$RollbackDll = '',
    [string]$OwnerApproval = ''
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $here))
$guard = Join-Path $repo 'package\artifact_guard.py'
if ([string]::IsNullOrEmpty($Ledger)) { $Ledger = Join-Path $repo 'package\capabilities\TScoring.TelemetryA.json' }
$python = 'C:\Python314\python.exe'
if (-not (Test-Path $python)) { $c = Get-Command python -ErrorAction SilentlyContinue; if ($null -ne $c) { $python = $c.Source } }
$script:fail = 0
function Result([string]$name, [bool]$ok, [string]$detail) {
    if ($ok) { Write-Host ('PASS ' + $name + ' ' + $detail) } else { Write-Host ('FAIL ' + $name + ' ' + $detail); $script:fail++ }
}
function Cap([string]$path) {
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'Read-TelemetryACapability.ps1') -Dll $path
    return ($out | Select-Object -Last 1 | ConvertFrom-Json)
}

$cand = Cap $Dll
$inst = Cap $Deployed
Result 'readable' ($cand.ok -and $inst.ok) ('candidate=' + $cand.error + ' deployed=' + $inst.error)
if ($cand.ok -and $inst.ok) {
    $led = Get-Content -LiteralPath $Ledger -Raw -Encoding UTF8 | ConvertFrom-Json
    $sha = $cand.sha256
    $stages = @{}
    foreach ($s in @('build', 'accept', 'deploy')) { $stages[$s] = @($led.history | Where-Object { $_.stage -eq $s -and $_.sha256 -eq $sha }) }
    Result '1 sha(ACCEPTED=DEPLOYED=PROMOTED)' (($stages['build'].Count -ge 1) -and ($stages['accept'].Count -ge 1) -and ($stages['deploy'].Count -ge 1) -and ($inst.sha256 -eq $sha)) ('candidate=' + $sha.Substring(0, 8) + ' deployed=' + $inst.sha256.Substring(0, 8) + ' ledger build/accept/deploy=' + $stages['build'].Count + '/' + $stages['accept'].Count + '/' + $stages['deploy'].Count)
    $same = ($cand.executionCompiledIn -eq $inst.executionCompiledIn) -and ($cand.featureBits -eq $inst.featureBits) -and ($cand.metadata.'TScoring.LegacyJumpExec' -eq $inst.metadata.'TScoring.LegacyJumpExec') -and ($cand.metadata.'TScoring.BuildRole' -eq $inst.metadata.'TScoring.BuildRole')
    $ledgerSame = $true
    foreach ($s in @('build', 'accept', 'deploy')) { foreach ($e in $stages[$s]) { if (($e.capabilities.featureBits -ne $cand.featureBits) -or ($e.capabilities.legacyJumpExec -ne ($cand.metadata.'TScoring.LegacyJumpExec' -eq 'true'))) { $ledgerSame = $false } } }
    Result '2 capabilities(ACCEPTED=DEPLOYED=PROMOTED)' ($same -and $ledgerSame) ('compiledIn=' + $cand.executionCompiledIn + ' featureBits=' + $cand.featureBits + ' role=' + $cand.metadata.'TScoring.BuildRole')
}
$g = & $python -I -B $guard check --stage promote --dll $Dll --deployed $Deployed --remote-ref $RemoteRef --ledger $Ledger @(if ($OwnerApproval) { '--owner-approval', $OwnerApproval })
Result '3+4 artifact guard promote (formal Jump ON, remote, no capability lost)' ($LASTEXITCODE -eq 0) (($g | Select-Object -First 1))
if ($LASTEXITCODE -ne 0) { $g | Select-Object -Skip 1 | ForEach-Object { Write-Host $_ } }
$procs = @(Get-Process -Name 'BveTs*', 'python', 'pythonw' -ErrorAction SilentlyContinue)
Result '5a processes' ($procs.Count -eq 0) ('left=' + $procs.Count)
if (-not [string]::IsNullOrEmpty($Since)) {
    $t0 = [datetime]::Parse($Since)
    $wer = @(Get-ChildItem 'C:\ProgramData\Microsoft\Windows\WER\ReportArchive', 'C:\ProgramData\Microsoft\Windows\WER\ReportQueue' -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $t0 -and $_.Name -match 'BveTs|python' })
    $dumps = @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'CrashDumps') -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $t0 -and $_.Name -match 'BveTs|python' })
    Result '5b WER / CrashDump since' (($wer.Count + $dumps.Count) -eq 0) ('wer=' + $wer.Count + ' dumps=' + $dumps.Count)
}
if (-not [string]::IsNullOrEmpty($RollbackDll)) {
    $r = & $python -I -B $guard check --stage rollback --dll $Dll --rollback-dll $RollbackDll --ledger $Ledger @(if ($OwnerApproval) { '--owner-approval', $OwnerApproval })
    Result '6 rollback asset' ($LASTEXITCODE -eq 0) (($r | Select-Object -First 1))
}
if ($script:fail -eq 0) { Write-Host 'ARTIFACT-IDENTITY PASS'; exit 0 }
Write-Host ('ARTIFACT-IDENTITY FAIL (' + $script:fail + ')')
exit 1
