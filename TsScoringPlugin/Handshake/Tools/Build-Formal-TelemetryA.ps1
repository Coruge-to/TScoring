# The ONE entry of the FORMAL TScoring.TelemetryA build (OD-X11 v2, Owner 2026-11-15). ASCII-only on purpose; Windows PowerShell 5.1.
#
#   .\Build-Formal-TelemetryA.ps1 -Commit <40-hex SHA> [-WorkParent <dir>] [-OutDir <dir>] [-LedgerPath <json>] [-Evidence <text>]
#
# The formal TelemetryA is a Release build of ONE source commit with the Legacy Jump execution ON, deterministic (PathMap fixed), made in TWO clean roots whose SHA-256 must match, and then checked FROM THE DLL ITSELF
# (capability, AssemblyMetadata, sidecar) by package\artifact_guard.py. There is NO LegacyJumpExec parameter: the property is fixed below, so a caller can never forget it, and a result that is not Jump ON is
# refused BEFORE anything can be deployed (it is moved to _rejected\ and the script exits non-zero). The Jump OFF diagnostic build is a different script (Build-Diag-TelemetryA-JumpOff.ps1) with a different output.
# Nothing here deploys, promotes or marks a stage in the ledger except the `build` entry when -LedgerPath is given.
param(
    [Parameter(Mandatory = $true)][string]$Commit,
    [string]$WorkParent = '',
    [string]$OutDir = '',
    [string]$LedgerPath = '',
    [string]$Evidence = '',
    [string]$RemoteRef = 'origin/refactor/state-transitions'
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $here))      # ...\Handshake\Tools -> repo root
$projRel = 'TsScoringPlugin\Handshake\Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'
$msbuildFixedArgs = '/t:Rebuild /p:Configuration=Release /p:Platform=AnyCPU /p:LegacyJumpExec=true /p:PathMap=<root>\=C:\ts-build\ /v:minimal /nologo /nr:false /m:1'
$python = 'C:\Python314\python.exe'
if (-not (Test-Path $python)) { $c = Get-Command python -ErrorAction SilentlyContinue; if ($null -ne $c) { $python = $c.Source } }

function Fail([string]$m) { Write-Host ('BUILD-FORMAL-FAIL: ' + $m); exit 1 }

# ---- parse check of this script itself (ParseError 0) ----------------------------------------------------------------------
$tok = $null; $err = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($MyInvocation.MyCommand.Path, [ref]$tok, [ref]$err)
if (@($err).Count -ne 0) { Fail 'this script has parse errors' }
if ($Commit -notmatch '^[0-9a-f]{40}$') { Fail 'Commit must be a full 40-hex SHA (lower case)' }
if ($null -eq $python -or -not (Test-Path $python)) { Fail 'python is not available' }
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
if (-not (Test-Path $msbuild)) { Fail ('MSBuild is not found: ' + $msbuild) }

# ---- the source commit: exists, no whitespace errors, package guard ACCEPT --------------------------------------------------
& git -C $repo cat-file -e ($Commit + '^{commit}')
if ($LASTEXITCODE -ne 0) { Fail ('commit not found in ' + $repo) }
& git -C $repo show --check --format=%H $Commit | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'git show --check reports whitespace errors in the commit' }
$onRemote = $false
& git -C $repo merge-base --is-ancestor $Commit $RemoteRef 2>$null
if ($LASTEXITCODE -eq 0) { $onRemote = $true }

if ([string]::IsNullOrEmpty($WorkParent)) { $WorkParent = Join-Path $env:TEMP ('ts-formal-build-' + $Commit.Substring(0, 8)) }
if ([string]::IsNullOrEmpty($OutDir)) { $OutDir = Join-Path $WorkParent 'formal' }
if ($OutDir.ToLowerInvariant().Contains('diag-jumpoff')) { Fail 'the formal output must not be under a diag-jumpoff folder' }
$scriptSha = (Get-FileHash -LiteralPath $MyInvocation.MyCommand.Path -Algorithm SHA256).Hash
$rejected = Join-Path $WorkParent '_rejected'
foreach ($d in @($OutDir, $rejected)) { New-Item -ItemType Directory -Force $d | Out-Null }

# ---- two clean roots ---------------------------------------------------------------------------------------------------------
$shas = @{}
$dllOf = @{}
foreach ($name in @('fa', 'fb')) {
    $root = Join-Path $WorkParent $name
    if (Test-Path $root) { Remove-Item -Recurse -Force $root }
    & git -c core.autocrlf=false clone -q --no-hardlinks $repo $root
    if ($LASTEXITCODE -ne 0) { Fail ('clone failed for ' + $name) }
    & git -C $root -c core.autocrlf=false checkout -q --detach $Commit
    if ($LASTEXITCODE -ne 0) { Fail ('checkout failed for ' + $name) }
    $head = (& git -C $root rev-parse HEAD).Trim()
    if ($head -ne $Commit) { Fail ('root ' + $name + ' is not at the commit') }
    if (@(& git -C $root status --porcelain).Count -ne 0) { Fail ('root ' + $name + ' is not clean') }
    & $python -I -B (Join-Path $root 'package\source_package.py') check --repo-root $root --mode commit --rev $Commit | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail ('package guard (source_package.py) did not ACCEPT root ' + $name) }
    $outPath = Join-Path $root 'out\'
    $objPath = Join-Path $root 'obj\'
    $args2 = @((Join-Path $root $projRel), '/t:Rebuild', '/p:Configuration=Release', '/p:Platform=AnyCPU', '/p:LegacyJumpExec=true', ('/p:PathMap=' + $root + '\=C:\ts-build\'),
        ('/p:OutputPath=' + $outPath), ('/p:IntermediateOutputPath=' + $objPath), '/v:minimal', '/nologo', '/nr:false', '/m:1')
    & $msbuild @args2
    if ($LASTEXITCODE -ne 0) { Fail ('MSBuild failed for root ' + $name) }
    $dll = Join-Path $outPath 'TScoring.TelemetryA.dll'
    if (-not (Test-Path $dll)) { Fail ('no DLL for root ' + $name) }
    $dllOf[$name] = $dll
    $shas[$name] = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash
}
$rootsMatched = ($shas['fa'] -eq $shas['fb'])
Write-Host ('root fa sha256=' + $shas['fa'])
Write-Host ('root fb sha256=' + $shas['fb'])
if (-not $rootsMatched) { Fail 'the two clean roots produced different SHA-256 (not deterministic)' }

# ---- stage the candidate, write the sidecar FROM the DLL, then the guard decides ---------------------------------------------
$stage = Join-Path $rejected ('candidate-' + $shas['fa'].Substring(0, 8))
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null
$candidate = Join-Path $stage 'TScoring.TelemetryA.dll'
Copy-Item -LiteralPath $dllOf['fa'] -Destination $candidate
$builtAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$guard = Join-Path $repo 'package\artifact_guard.py'
$remoteText = 'false'
if ($onRemote) { $remoteText = 'true' }
& $python -I -B $guard make-sidecar --dll $candidate --commit $Commit --msbuild-args $msbuildFixedArgs --script-sha256 $scriptSha --roots-matched true --source-on-remote $remoteText --built-at $builtAt
if ($LASTEXITCODE -ne 0) { Fail 'the sidecar could not be written (capability unreadable)' }
$ledgerArg = @()
if (-not [string]::IsNullOrEmpty($LedgerPath)) { $ledgerArg = @('--ledger', $LedgerPath) }
& $python -I -B $guard check --stage build --dll $candidate @ledgerArg
if ($LASTEXITCODE -ne 0) { Fail 'the artifact guard REJECTED the build (see the findings above): it stays under _rejected\ and must not be deployed' }

# ---- accepted as a formal CANDIDATE: publish into OutDir ----------------------------------------------------------------------
$final = Join-Path $OutDir 'TScoring.TelemetryA.dll'
Copy-Item -LiteralPath $candidate -Destination $final -Force
Copy-Item -LiteralPath ($candidate + '.capability.json') -Destination ($final + '.capability.json') -Force
if ((Get-FileHash -LiteralPath $final -Algorithm SHA256).Hash -ne $shas['fa']) { Fail 'the published DLL differs from the built one' }
$report = Join-Path $OutDir 'build-report.tsv'
$lines = @(
    "field`tvalue",
    ("sourceCommit`t" + $Commit), ("sourceOnRemoteAtBuild`t" + $onRemote), ("configuration`tRelease"), ("legacyJumpExec`ttrue"),
    ("sha256`t" + $shas['fa']), ("rootA`t" + $shas['fa']), ("rootB`t" + $shas['fb']), ("rootsMatched`t" + $rootsMatched),
    ("buildScriptSha256`t" + $scriptSha), ("msbuildArgs`t" + $msbuildFixedArgs), ("builtAtUtc`t" + $builtAt), ("guardStage`tbuild ACCEPT")
)
[System.IO.File]::WriteAllLines($report, $lines, (New-Object System.Text.UTF8Encoding($false)))
if (-not [string]::IsNullOrEmpty($LedgerPath)) {
    & $python -I -B $guard record --stage build --dll $final --ledger $LedgerPath --evidence $Evidence --at $builtAt
    if ($LASTEXITCODE -ne 0) { Fail 'the build entry could not be recorded in the ledger' }
}
Write-Host ('BUILD-FORMAL-OK sha256=' + $shas['fa'] + ' out=' + $OutDir)
exit 0
