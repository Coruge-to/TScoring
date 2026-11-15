# The DIAGNOSTIC Jump OFF build of TScoring.TelemetryA (OD-X11 v2, Owner 2026-11-15). ASCII-only on purpose; Windows PowerShell 5.1.
#
#   .\Build-Diag-TelemetryA-JumpOff.ps1 -Commit <40-hex SHA> -DiagRoot <dir>
#
# Comparison / diagnosis only. The output is ALWAYS under <DiagRoot>\diag-jumpoff\ (the csproj refuses anything else), carries TScoring.BuildRole=DiagnosticJumpOff and a sidecar with formalCandidate=false.
# It is never deployed under the formal name, never promoted and is rejected by package\artifact_guard.py at every formal stage. Public packages must not contain it (use a dedicated folder).
param(
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$DiagRoot
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $here))
$projRel = 'TsScoringPlugin\Handshake\Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'
$python = 'C:\Python314\python.exe'
if (-not (Test-Path $python)) { $c = Get-Command python -ErrorAction SilentlyContinue; if ($null -ne $c) { $python = $c.Source } }
function Fail([string]$m) { Write-Host ('BUILD-DIAG-FAIL: ' + $m); exit 1 }
if ($Commit -notmatch '^[0-9a-f]{40}$') { Fail 'Commit must be a full 40-hex SHA' }
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
if (-not (Test-Path $msbuild)) { Fail 'MSBuild is not found' }
$work = Join-Path $DiagRoot 'src'
$out = Join-Path $DiagRoot 'diag-jumpoff\'
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $out | Out-Null
& git -c core.autocrlf=false clone -q --no-hardlinks $repo $work
& git -C $work -c core.autocrlf=false checkout -q --detach $Commit
if ($LASTEXITCODE -ne 0) { Fail 'checkout failed' }
$msbArgs = '/t:Rebuild /p:Configuration=Release /p:Platform=AnyCPU /p:LegacyJumpExec=false /p:TScoringDiagnosticJumpOff=true /v:minimal /nologo /nr:false /m:1'
& $msbuild (Join-Path $work $projRel) /t:Rebuild /p:Configuration=Release /p:Platform=AnyCPU /p:LegacyJumpExec=false /p:TScoringDiagnosticJumpOff=true ('/p:OutputPath=' + $out) ('/p:IntermediateOutputPath=' + (Join-Path $DiagRoot 'obj\')) /v:minimal /nologo /nr:false /m:1
if ($LASTEXITCODE -ne 0) { Fail 'MSBuild failed' }
$dll = Join-Path $out 'TScoring.TelemetryA.dll'
$scriptSha = (Get-FileHash -LiteralPath $MyInvocation.MyCommand.Path -Algorithm SHA256).Hash
& $python -I -B (Join-Path $repo 'package\artifact_guard.py') make-sidecar --dll $dll --commit $Commit --msbuild-args $msbArgs --script-sha256 $scriptSha --roots-matched false --source-on-remote false --diagnostic --built-at ((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
if ($LASTEXITCODE -ne 0) { Fail 'sidecar failed' }
Write-Host ('BUILD-DIAG-OK (Jump OFF, formalCandidate=false) ' + $dll)
exit 0
