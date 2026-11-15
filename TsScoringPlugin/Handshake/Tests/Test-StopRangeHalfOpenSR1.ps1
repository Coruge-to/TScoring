param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)
# STOP RANGE = THE BVE OFFICIAL CONTRACT (Owner 2026-11-15) - offline BEHAVIOUR test of the SENDER half, Current AND Legacy, the SAME scenarios.
#
# The contract under test (BveTs.exe 5.8 and 6.0, static analysis: raw doubles, no rounding):
#     in range  =  v + margin1 <= loc < v + margin2          (v = the stop position, loc = the train position)
#     with d = v - loc (the HUD distance, short of the mark is positive):   -marginFront < d <= marginBack
#   * d == +marginBack (the short end) is IN: a stop made there (speed == 0.0) is the arrival candidate event, the target may switch;
#   * d == -marginFront (the overrun end) is OUT: no stop is made, no door flag / stop record, no arrival event, the target is NOT switched (not at once, not at the departure time, not when moving);
#   * the next double above +marginBack is OUT; the next double above -marginFront is IN; the next double below -marginFront is OUT;
#   * the speed condition (exactly 0.0) and the door-station rules are untouched.
# HOW: as Test-TimeFixB3.ps1 (the station part of the Class1.cs Tick is cut out of the SOURCE and compiled in memory; the Legacy side compiles the REAL LegacyStationTimeline.cs). ASCII only, Windows PowerShell 5.1.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$class1 = Join-Path $RepositoryRoot 'TsScoringPlugin\TsScoringPlugin\Class1.cs'
$tele = Join-Path $RepositoryRoot 'TsScoringPlugin\Handshake\Telemetry'
$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}

function Get-BlockText([string]$text, [string]$signature) {
    $start = $text.IndexOf($signature, [StringComparison]::Ordinal)
    if ($start -lt 0) { return $null }
    $open = $text.IndexOf('{', $start)
    if ($open -lt 0) { return $null }
    $depth = 0
    for ($p = $open; $p -lt $text.Length; $p++) {
        $c = $text[$p]
        if ($c -eq '{') { $depth++ }
        elseif ($c -eq '}') {
            $depth--
            if ($depth -eq 0) { return $text.Substring($start, $p - $start + 1) }
        }
    }
    return $null
}
function Get-StationPartStatement([string]$text) {
    $marker = 'int stationIndexBeforeAdvance = targetStationIndex;'
    $m = $text.IndexOf($marker, [StringComparison]::Ordinal)
    if ($m -lt 0) { return $null }
    if ($text.IndexOf($marker, $m + 1, [StringComparison]::Ordinal) -ge 0) { return $null }
    $head = 'if (targetStationIndex < stationList.Count)'
    $s = $text.LastIndexOf($head, $m, [StringComparison]::Ordinal)
    if ($s -lt 0) { return $null }
    return (Get-BlockText $text.Substring($s) $head)
}

$T = 36000000
$ARR = 36060000
$DEP = 36120000
function NextUp([double]$x) { return [BitConverter]::Int64BitsToDouble([BitConverter]::DoubleToInt64Bits($x) + 1) }      # x > 0 only
function NextDown([double]$x) { return [BitConverter]::Int64BitsToDouble([BitConverter]::DoubleToInt64Bits($x) - 1) }    # x > 0 only
function Show([double]$v) { return $v.ToString('R', [Globalization.CultureInfo]::InvariantCulture) }

Write-Host '--- the statement block is cut out of Class1.cs'
$source = [IO.File]::ReadAllText($class1, [Text.Encoding]::UTF8)
$stationPart = Get-StationPartStatement $source
$stationDataClass = Get-BlockText $source 'public class StationData'
Check 'S01 the station part of the Current Tick is found exactly once' ($null -ne $stationPart)
Check 'S02 the StationData class is found' ($null -ne $stationDataClass)
if (($null -eq $stationPart) -or ($null -eq $stationDataClass)) {
    Write-Host ''
    Write-Host ('STOPRANGE-SR1 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

$currentFixture = @'
using System;
using System.Collections.Generic;

namespace SR1Current
{
//STATIONDATA//

    public sealed class Probe
    {
        private List<StationData> stationList = new List<StationData>();
        private int targetStationIndex = 0;
        private bool hasDoorOpenedAtTarget = false;
        private int opStopDelayStartMs = -1;
        private int opStopMadeIndex = -1;
        private int terminalFrozenDiffSeconds = -999;
        private bool wasTerminalDoorOpened = false;
        private int stidxArrivalIndex = -1;
        private int stidxArrivalSeq = 0;
        private double outLoc = -1;
        private int outTime = -1;

        public void Add(string name, double loc, bool pass, bool terminal, int doorDir, int arrMs, int depMs, int stopMs, double marginMin, double marginMax)
        {
            StationData sd = new StationData();
            sd.Name = name; sd.Location = loc; sd.IsPass = pass; sd.IsTerminal = terminal; sd.DoorDir = doorDir;
            sd.ArrTime = arrMs; sd.DepTime = depMs; sd.RawArrTime = arrMs; sd.RawDepTime = depMs; sd.DefaultTime = -1; sd.InterpolatedTime = -1;
            sd.StoppageTime = stopMs; sd.MarginMin = Math.Abs(marginMin); sd.MarginMax = marginMax; sd.IsScoring = true; sd.HasTimeDef = true;
            stationList.Add(sd);
        }

        public void Begin(int index) { targetStationIndex = index; hasDoorOpenedAtTarget = false; opStopDelayStartMs = -1; opStopMadeIndex = -1; }

        public void Step(double location, double speed, int timeMs, bool areDoorsClosed)
        {
            int stidxTarget = -1;
            double nextStationLoc = -1;
            int nextStationTime = -1;
            int isPass = 0;
            int isTiming = 0;
            double marginBack = 5.0;
            double marginFront = 5.0;
//STATIONPART//
            outLoc = nextStationLoc;
            outTime = nextStationTime;
            if (isPass < 0 || isTiming < 0 || marginBack < 0 || marginFront < 0 || stidxTarget < -5) { outLoc = -999; }
        }

        public int Target { get { return targetStationIndex; } }
        public double NextLoc { get { return outLoc; } }
        public int NextTime { get { return outTime; } }
        public int ArrIdx { get { return stidxArrivalIndex; } }
        public int ArrSeq { get { return stidxArrivalSeq; } }
    }
}
'@
$currentFixture = $currentFixture.Replace('//STATIONDATA//', $stationDataClass).Replace('//STATIONPART//', $stationPart)
$compileError = $null
try {
    Add-Type -TypeDefinition $currentFixture -ReferencedAssemblies @('System.dll', 'System.Core.dll', 'Microsoft.CSharp.dll') -IgnoreWarnings
} catch {
    $compileError = $_.Exception.Message
}
Check 'S03 the cut-out Current station part compiles in memory (C# 5)' ($null -eq $compileError)
if ($null -ne $compileError) {
    Write-Host ('  compile error: ' + $compileError)
    Write-Host ''
    Write-Host ('STOPRANGE-SR1 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

Write-Host '--- the real Legacy sources are compiled with a fixture'
$work = Join-Path $env:TEMP ('ts-stoprange-sr1-' + [guid]::NewGuid().ToString('N'))
$legacyFixture = @'
using System;
using System.Collections.Generic;
using TSScoringPlugin.Telemetry;

public sealed class SR1LegacyProbe
{
    private LegacyStationTimeline t = new LegacyStationTimeline();
    private List<LegacyStationRaw> raw = new List<LegacyStationRaw>();
    private StationValues last;

    public void Add(string name, double loc, bool pass, bool terminal, int doorDir, int arrMs, int depMs, int stopMs, double marginMin, double marginMax)
    {
        LegacyStationRaw r = new LegacyStationRaw();
        r.Name = name; r.Location = loc; r.Pass = pass; r.IsTerminal = terminal; r.DoorSide = doorDir;
        r.ArrivalMs = arrMs; r.DepartureMs = depMs; r.DefaultMs = -1; r.StoppageMs = stopMs; r.MarginMin = marginMin; r.MarginMax = marginMax;
        raw.Add(r);
    }
    public void Seed(int index) { t.RequestTarget(index, raw[index].Location); }
    public void Begin(int index) { Seed(index); Step(500.0, 50.0, 36000000, true); }
    public void Step(double location, double speedKmh, int timeMs, bool doorsClosed)
    {
        last = t.Step(raw, raw.Count, location, speedKmh, timeMs, doorsClosed);
    }
    public int Target { get { return t.TargetIndex; } }
    public double NextLoc { get { return last.NextLoc; } }
    public int NextTime { get { return last.NextTime; } }
    public int ArrIdx { get { return t.ArrivalIndex; } }
    public int ArrSeq { get { return t.ArrivalSeq; } }
}
'@
$legacyReady = $false
$legacyError = $null
try {
    New-Item -ItemType Directory -Path $work | Out-Null
    $fixturePath = Join-Path $work 'SR1LegacyProbe.cs'
    [IO.File]::WriteAllText($fixturePath, $legacyFixture, (New-Object Text.UTF8Encoding($false)))
    # the Legacy project is C# 9 (LangVersion 9.0): the stale CodeDom (C# 5) route of the older tests can not compile it, so the REAL sources are compiled with the Roslyn csc of the Visual Studio MSBuild
    $csc = $null
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($root) { $csc = Get-ChildItem -Path (Join-Path $root 'Microsoft Visual Studio') -Recurse -Filter 'csc.exe' -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match 'MSBuild\\Current\\Bin\\Roslyn\\csc\.exe$' } | Select-Object -First 1 }
        if ($csc) { break }
    }
    if (-not $csc) { throw 'REFUSED: the Roslyn csc.exe of the Visual Studio MSBuild was not found' }
    $sources = @(
        (Join-Path $tele 'Legacy\src\LegacyStationTimeline.cs'),
        (Join-Path $tele 'Legacy\src\LegacyApi.cs'),
        (Join-Path $tele 'Shared\TelemetryContract.cs'),
        (Join-Path $tele 'Shared\StationListIdentity.cs'),
        (Join-Path $tele 'Shared\JumpWire.cs'),
        (Join-Path $tele 'Shared\PackageContract.cs'),
        (Join-Path $tele 'Shared\PseudoTurnbackQualifier.cs'),
        (Join-Path $tele 'Shared\PseudoTurnbackPairCodec.cs'),
        $fixturePath)
    $dll = Join-Path $work 'sr1legacy.dll'
    $cscArgs = @('/nologo', '/target:library', '/langversion:9.0', '/deterministic', '/warn:0', ('/out:' + $dll), '/reference:System.dll', '/reference:System.Core.dll') + $sources
    $cscOut = & $csc.FullName $cscArgs 2>&1 | Out-String
    if (-not (Test-Path -LiteralPath $dll)) { throw ('csc failed: ' + $cscOut) }
    [void][Reflection.Assembly]::LoadFrom($dll)
    $legacyReady = $true
} catch {
    $legacyError = $_.Exception.Message
    if ($_.Exception.PSObject.Properties['LoaderExceptions']) { $legacyError = $legacyError + ' ' + (($_.Exception.LoaderExceptions | ForEach-Object { $_.Message }) -join ' | ') }
}
Check 'S04 the real Legacy sources compile in memory with the fixture' $legacyReady
if (-not $legacyReady) {
    Write-Host ('  compile error: ' + $legacyError)
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host ''
    Write-Host ('STOPRANGE-SR1 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

# A idx0 @0, B idx1 @1000 (the station under test, DoorDir 0 unless said otherwise), C idx2 @1100, D idx3 @3000 (terminal)
# B: mmin = |MarginMin| = the SHORT side (marginBack), mmax = MarginMax = the PAST side (marginFront)
function NewProbe([string]$kind, [double]$mmin, [double]$mmax, [int]$bDoor = 0) {
    if ($kind -eq 'Legacy') { $p = New-Object SR1LegacyProbe } else { $p = New-Object SR1Current.Probe }
    $p.Add('A', 0.0, $false, $false, 1, -1, -1, 15000, 5.0, 5.0)
    $p.Add('B', 1000.0, $false, $false, $bDoor, $ARR, $DEP, 15000, $mmin, $mmax)
    $p.Add('C', 1100.0, $false, $false, 1, ($DEP + 30000), ($DEP + 60000), 15000, 5.0, 5.0)
    $p.Add('D', 3000.0, $false, $true, 1, ($DEP + 400000), -1, 15000, 5.0, 5.0)
    $p.Begin(1)
    $p.Step(500.0, 50.0, $T, $true)         # the list is built, the target is B, the vehicle runs with the doors closed
    return $p
}

# one boundary position: the stop attempt at `loc` (speed exactly 0.0), then standing past the scheduled time, then moving. Returns a signature string (so Current and Legacy can be compared).
function Attempt([string]$kind, [double]$mmin, [double]$mmax, [double]$loc) {
    $p = NewProbe $kind $mmin $mmax
    $p.Step($loc, 0.0, ($T + 1000), $true)
    $made = (($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1) -and ($p.NextTime -eq $DEP) -and ($p.Target -eq 1))
    $p.Step($loc, 0.0, ($DEP + 400), $true)          # standing past the scheduled time (+300 ms hold)
    $p.Step($loc, 0.0, ($DEP + 800), $true)
    $afterHold = $p.Target
    $q = NewProbe $kind $mmin $mmax
    $q.Step($loc, 0.0, ($T + 1000), $true)
    $q.Step($loc, 2.0, ($T + 2000), $true)          # moving after the stop: the target switches at once IF the stop was made
    $afterMove = $q.Target
    return ('made=' + $made + ' arrSeq=' + $p.ArrSeq + ' holdTarget=' + $afterHold + ' moveTarget=' + $afterMove + ' nextLoc=' + (Show $q.NextLoc))
}

$margins = @(@(2.0, 2.0), @(3.0, 2.0), @(2.0, 3.0), @(5.0, 5.0), @(0.5, 0.5))
$sig = @{}
foreach ($kind in @('Current', 'Legacy')) {
    Write-Host ('--- ' + $kind)
    $k = $kind
    foreach ($m in $margins) {
        $mb = [double]$m[0]; $mf = [double]$m[1]
        $tag = $k + ' mb=' + (Show $mb) + ' mf=' + (Show $mf) + ' '
        $shortEnd = 1000.0 - $mb                    # d = +marginBack exactly
        $overrunEnd = 1000.0 + $mf                  # d = -marginFront exactly
        $cases = @(
            @{ id = 'R1'; what = 'd = +marginBack (the short end)'; loc = $shortEnd; inside = $true },
            @{ id = 'R2'; what = 'nextafter(+marginBack, +inf) (beyond the short end)'; loc = (NextDown $shortEnd); inside = $false },
            @{ id = 'R3'; what = 'd = -marginFront (the overrun end)'; loc = $overrunEnd; inside = $false },
            @{ id = 'R4'; what = 'nextafter(-marginFront, +inf) (just inside the overrun end)'; loc = (NextDown $overrunEnd); inside = $true },
            @{ id = 'R5'; what = 'nextafter(-marginFront, -inf) (beyond the overrun end)'; loc = (NextUp $overrunEnd); inside = $false },
            @{ id = 'R0'; what = 'd = 0 (the mark)'; loc = 1000.0; inside = $true }
        )
        foreach ($cs in $cases) {
            $s = Attempt $k $mb $mf $cs.loc
            $sig[$k + '|' + $mb + '|' + $mf + '|' + $cs.id] = $s
            if ($cs.inside) {
                Check ($tag + $cs.id + ' ' + $cs.what + ' at loc ' + (Show $cs.loc) + ': the stop is made (arrival event, NEXTTIME = departure) and the target switches when the vehicle moves') (($s -like 'made=True arrSeq=1 holdTarget=2 moveTarget=2 *'))
            } else {
                Check ($tag + $cs.id + ' ' + $cs.what + ' at loc ' + (Show $cs.loc) + ': NO stop is made, no arrival event, the target B is kept at the hold time and when moving') (($s -like 'made=False arrSeq=0 holdTarget=1 moveTarget=1 *'))
            }
        }
    }

    # R6 the speed condition is untouched: a non-zero speed on the short end (inside the range) makes no stop
    foreach ($v in @([double]::Epsilon, 0.0001, 0.1, 5.0, -0.0001)) {
        $p = NewProbe $k 2.0 2.0
        $p.Step(998.0, $v, ($T + 1000), $true)
        $p.Step(998.0, $v, ($T + 2000), $true)
        Check ($k + ' R6 speed ' + (Show $v) + ' on the short end (inside the range) makes NO stop') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0) -and ($p.NextTime -eq $ARR))
    }

    # R7 a normal door station is door based and does NOT read the range: doors open within 100 m is the event, at d = -marginFront and just beyond both ends alike
    foreach ($loc in @(1002.0, (NextUp 1002.0), 998.0, (NextDown 998.0), 1000.0)) {
        $p = NewProbe $k 2.0 2.0 1
        $p.Step($loc, 0.0, ($T + 1000), $false)
        Check ($k + ' R7 door station, doors open at loc ' + (Show $loc) + ': the arrival event is door based (arr = B, arrseq = 1), range-independent') (($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1))
        $p.Step($loc, 0.0, ($T + 2000), $true)
        Check ($k + ' R7 door station, doors closed again at loc ' + (Show $loc) + ': the door based switch to C (unchanged)') ($p.Target -eq 2)
    }

    # R8 a stop that was made inside the range and then the train is moved past the overrun end does not switch back and does not re-judge (the existing record rules)
    $p = NewProbe $k 2.0 2.0
    $p.Step(1000.0, 0.0, ($T + 1000), $true)
    $p.Step(1002.0, 0.0, ($T + 2000), $true)           # still standing, now exactly on the overrun end (not a movement)
    Check ($k + ' R8 after a made stop the target is only switched by movement / the departure time (the range is not tested again)') (($p.Target -eq 1) -and ($p.ArrSeq -eq 1))
}

# R9 Current and Legacy give the SAME signature in every case
$diff = 0
foreach ($key in @($sig.Keys)) {
    if ($key.StartsWith('Current|')) {
        $other = 'Legacy' + $key.Substring(7)
        if ($sig[$key] -ne $sig[$other]) { $diff++; Write-Host ('  DIFF ' + $key + ' :: ' + $sig[$key] + ' <> ' + $sig[$other]) }
    }
}
Check ('R9 Current and Legacy give identical results in all ' + (($sig.Keys | Where-Object { $_.StartsWith('Current|') }).Count) + ' boundary cases') ($diff -eq 0)

# S05 / S06 the sources: the overrun end is not inside any judgement of the sender any more, the short end is
$legacySource = [IO.File]::ReadAllText((Join-Path $tele 'Legacy\src\LegacyStationTimeline.cs'), [Text.Encoding]::UTF8)
Check 'S05 Current: isInMargin = (distToStop > -marginFront && distToStop <= marginBack)' ($source.Contains('bool isInMargin = (distToStop > -marginFront && distToStop <= marginBack);'))
Check 'S06 Legacy: isInMargin = distToStop > -marginFront && distToStop <= marginBack' ($legacySource.Contains('bool isInMargin = distToStop > -marginFront && distToStop <= marginBack;'))
Check 'S07 no closed overrun end (>= -marginFront) is left in either sender' ((-not $source.Contains('>= -marginFront')) -and (-not $legacySource.Contains('>= -marginFront')))
Check 'S08 the range is judged in exactly one place per sender' ((([regex]::Matches($source, 'bool isInMargin')).Count -eq 1) -and (([regex]::Matches($legacySource, 'bool isInMargin')).Count -eq 1))

if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host ''
Write-Host ('STOPRANGE-SR1 PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -gt 0) { exit 1 }
exit 0
