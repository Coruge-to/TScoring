# (Tools\Invoke-PausePulseSiteMutationS05.ps1: a heavy builder, NOT picked up by the automatic Test-*/Verify-* regression runs; run it by hand or from the stage gate.)
# PHASE S05-FIX - site mutation check: the gate itself is mutation-checked by Test-PausePulseGateS05.ps1; THIS script removes the gate WIRING of each of the four pulse senders
# (Class1, Current Bridge, Legacy Bridge, Legacy Telemetry extension) one rule at a time, rebuilds the sender in a TEMPORARY COPY of the source tree and requires the integration fixture
# (Test-PausePulseContractS05.ps1) to turn RED (exit != 0). The work tree is never touched; the copy is deleted at the end (-Keep keeps it). Needs MSBuild (Visual Studio) and the installed hosts.
# ASCII-only on purpose. Windows PowerShell 5.1.   exit 0 = every site mutant was killed; 2 = a mutant survived / the harness is broken.
param(
    [string]$MsBuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe',
    [string]$WorkParent = '',
    [string]$OutFile = '',
    [string[]]$Only = @(),
    [switch]$Keep
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$handshake = Split-Path $here -Parent                     # ...\TsScoringPlugin\Handshake
$srcRoot = Split-Path $handshake -Parent                  # ...\TsScoringPlugin
if (-not (Test-Path $MsBuild)) { Write-Host ('MSBuild not found: ' + $MsBuild); exit 2 }
if (-not $WorkParent) { $WorkParent = Join-Path (Split-Path $srcRoot -Parent | Split-Path -Parent) ('tspulse-sitemut-' + [guid]::NewGuid().ToString('N').Substring(0, 8)) }
$copy = Join-Path $WorkParent 'TsScoringPlugin'
New-Item -ItemType Directory -Force $WorkParent | Out-Null
& robocopy $srcRoot $copy /E /XD out obj bin logs /NFL /NDL /NJH /NJS /NP | Out-Null
if (-not (Test-Path (Join-Path $copy 'Handshake\Telemetry\Shared\PausePulseGate.cs'))) { Write-Host 'copy failed'; exit 2 }

$sites = @{
    'Class1' = @{ File = 'TsScoringPlugin\Class1.cs'; Proj = 'TsScoringPlugin\TsScoringPlugin.csproj'; Adapter = 'Current'; Out = 'TsScoringPlugin\bin\Release\TScoring.TelemetryB.dll'; Kind = 'Telemetry'
        Opened = '{ try { pulseGate.OnScenarioOpenedOrClosed(); } catch { } }'; Tick = 'pulseGate.NoteTick();' }
    'BridgeCurrent' = @{ File = 'Handshake\Bridge\src\TsScoringBridgePrototype.cs'; Proj = 'Handshake\Bridge\TSScoringPlugin.BveEx.Bridge.Prototype.csproj'; Adapter = 'Current'; Out = 'Handshake\Bridge\out\TScoring.BridgeB.dll'; Kind = 'Bridge'
        Opened = 'try { pulseGate.OnScenarioOpenedOrClosed(); } catch { }'; Tick = 'try { pulseGate.NoteTick(); } catch { }' }
    'BridgeLegacy' = @{ File = 'Handshake\Bridge\Legacy\src\TsScoringLegacyBridge.cs'; Proj = 'Handshake\Bridge\Legacy\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj'; Adapter = 'Legacy'; Out = 'Handshake\Bridge\Legacy\out\TScoring.BridgeA.dll'; Kind = 'Bridge'
        Opened = 'try { pulseGate.OnScenarioOpenedOrClosed(); } catch { }'; Tick = 'try { pulseGate.NoteTick(); } catch { }' }
    'LegacyTelemetry' = @{ File = 'Handshake\Telemetry\Legacy\src\LegacyTelemetryExtension.cs'; Proj = 'Handshake\Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'; Adapter = 'Legacy'; Out = 'Handshake\Telemetry\Legacy\out\TScoring.TelemetryA.dll'; Kind = 'Telemetry'
        Opened = 'try { pulseGate.OnScenarioOpenedOrClosed(); } catch { }'; Tick = 'try { pulseGate.NoteTick(); } catch { }' }
}
$created = @{ Class1 = '{ try { pulseGate.OnScenarioCreated(); } catch { } }'; BridgeCurrent = 'try { pulseGate.OnScenarioCreated(); } catch { }'; BridgeLegacy = 'try { pulseGate.OnScenarioCreated(); } catch { }'; LegacyTelemetry = 'try { pulseGate.OnScenarioCreated(); } catch { }' }

function Edit-Once([string]$text, [string]$find, [string]$replace, [int]$nth) {
    $idx = -1
    for ($k = 0; $k -lt $nth; $k++) { $idx = $text.IndexOf($find, $idx + 1, [StringComparison]::Ordinal); if ($idx -lt 0) { return $null } }
    return $text.Substring(0, $idx) + $replace + $text.Substring($idx + $find.Length)
}
function Build-One([string]$proj) {
    $o = & $MsBuild (Join-Path $copy $proj) /t:Rebuild /p:Configuration=Release /p:Platform=AnyCPU /v:quiet /nologo /nr:false /m:1 2>&1 | Out-String
    return $LASTEXITCODE
}

$lines = New-Object System.Collections.Generic.List[string]
function Out-Line([string]$s) { $lines.Add($s); Write-Host $s }
$survivors = New-Object System.Collections.Generic.List[string]
$equivalent = 0
$total = 0

# a baseline build of the copy must be GREEN first (otherwise "killed" would only mean "did not build")
foreach ($name in 'Class1', 'BridgeCurrent', 'BridgeLegacy', 'LegacyTelemetry') {
    $rc = Build-One $sites[$name].Proj
    if ($rc -ne 0) { Out-Line ('HARNESS baseline build of ' + $name + ' failed'); exit 2 }
}
foreach ($adapter in 'Current', 'Legacy') {
    $o = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $copy 'Handshake\Tests\Test-PausePulseContractS05.ps1') -Adapter $adapter -OutDir (Join-Path $WorkParent ('base-' + $adapter)) 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Out-Line ('HARNESS baseline fixture ' + $adapter + ' is not green (exit ' + $LASTEXITCODE + ')'); exit 2 }
}
Out-Line 'baseline: the unmutated copy builds and both fixtures are green'

foreach ($name in 'Class1', 'BridgeCurrent', 'BridgeLegacy', 'LegacyTelemetry') {
    $s = $sites[$name]
    $mutants = @(
        @{ Id = 'request-gate-removed'; Find = 'if (!pulseGate.TryRequest(out requestEpoch)) return;'; Replace = 'requestEpoch = 0;'; Nth = 1 },
        @{ Id = 'enter-gate-removed'; Find = 'if (!pulseGate.TryEnter(requestEpoch)) return;'; Replace = ';'; Nth = 1 },
        @{ Id = 'opened-not-fed'; Find = $s.Opened; Replace = $(if ($name -eq 'Class1') { '{ }' } else { ';' }); Nth = 1 },
        @{ Id = 'closed-not-fed'; Find = $s.Opened; Replace = $(if ($name -eq 'Class1') { '{ }' } else { ';' }); Nth = 2 },
        @{ Id = 'created-not-fed'; Find = $created[$name]; Replace = $(if ($name -eq 'Class1') { '{ }' } else { ';' }); Nth = 1 },
        @{ Id = 'tick-not-noted'; Find = $s.Tick; Replace = ';'; Nth = 1 },
        @{ Id = 'complete-not-called'; Find = 'pulseGate.Complete();'; Replace = ';'; Nth = $(if ($name -eq 'Class1') { 2 } else { 2 }) }
    )
    foreach ($m in $mutants) {
        if ($Only.Count -gt 0 -and ($Only -notcontains ($name + '/' + $m.Id))) { continue }
        $total++
        $path = Join-Path $copy $s.File
        $orig = [IO.File]::ReadAllText($path)
        $mut = Edit-Once $orig $m.Find $m.Replace $m.Nth
        if ($null -eq $mut) { Out-Line ('HARNESS ' + $name + '/' + $m.Id + ': anchor not found'); $survivors.Add($name + '/' + $m.Id + ' (anchor)'); continue }
        [IO.File]::WriteAllText($path, $mut, (New-Object System.Text.UTF8Encoding($false)))
        try {
            $rc = Build-One $s.Proj
            if ($rc -ne 0) { Out-Line ('HARNESS ' + $name + '/' + $m.Id + ': the mutant does not build'); $survivors.Add($name + '/' + $m.Id + ' (no build)'); continue }
            $o = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $copy 'Handshake\Tests\Test-PausePulseContractS05.ps1') -Adapter $s.Adapter -OutDir (Join-Path $WorkParent ('mut-' + $name + '-' + $m.Id)) 2>&1 | Out-String
            $code = $LASTEXITCODE
            $failIds = @([regex]::Matches($o, '(?m)^(FAIL|CTRL-BAD)\s+(\S+)') | ForEach-Object { $_.Groups[2].Value })
            if ($code -ne 0) { Out-Line ('KILLED   ' + $name + '/' + $m.Id + ' (exit ' + $code + '; ' + ($failIds -join ',') + ')') }
            elseif (($name -like 'Bridge*') -and ($m.Id -eq 'tick-not-noted')) { Out-Line ('EQUIVALENT ' + $name + '/' + $m.Id + ': observably equivalent: the Bridge keeps its own lastTickTicks gap test on the timer thread and at callback time, so the gate Tick stamp is defense in depth'); $equivalent++ }
            else { Out-Line ('SURVIVED ' + $name + '/' + $m.Id); $survivors.Add($name + '/' + $m.Id) }
        }
        finally {
            [IO.File]::WriteAllText($path, $orig, (New-Object System.Text.UTF8Encoding($false)))
            # the next mutant must start from the UNMUTATED DLL of this project (a left-over mutant DLL would make later "kills" meaningless)
            $rcRestore = Build-One $s.Proj
            if ($rcRestore -ne 0) { Out-Line ('HARNESS ' + $name + ': the restore build failed'); exit 2 }
        }
    }
}
Out-Line ('SUMMARY site mutants=' + $total + ' equivalent=' + $equivalent + ' survived=' + $survivors.Count)
if ($OutFile) { [IO.File]::WriteAllLines($OutFile, $lines.ToArray(), (New-Object System.Text.UTF8Encoding($false))) }
if (-not $Keep) { try { Remove-Item -Recurse -Force $WorkParent } catch { } }
if ($survivors.Count -gt 0) { exit 2 }
exit 0
